"""
SHIKSHA — SQLite-backed student progress, session memory, and report cards.

Every live session is stored so SHIKSHA always knows:
  • Student profile (name, grade, age, parent)
  • What was taught in the last N sessions
  • What homework was assigned and when
  • Last homework check feedback

This context is injected into the system instruction before each live lesson,
so SHIKSHA never asks the student "what did we study last time?".
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai

from main import ASSISTANT_NAME, get_api_key, load_env_file

load_env_file()

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "shiksha.db"
JSON_SNAPSHOT_PATH = DATA_DIR / "students_snapshot.json"

ID_PREFIX = "S"
DEFAULT_TEXT_MODEL = "gemini-2.0-flash"
MAX_SESSIONS_IN_CONTEXT = 5   # how many past sessions SHIKSHA remembers live

# ── Persistent SQLite connection (WAL, single-writer, fast reads) ─────────────
# Opened once at startup; thread-safe because WAL allows concurrent readers.
_DB_CONN: sqlite3.Connection | None = None

def _conn() -> sqlite3.Connection:
    global _DB_CONN
    if _DB_CONN is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _DB_CONN = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _DB_CONN.row_factory = sqlite3.Row
        _DB_CONN.execute("PRAGMA journal_mode=WAL")
        _DB_CONN.execute("PRAGMA foreign_keys=ON")
        _DB_CONN.execute("PRAGMA synchronous=NORMAL")   # faster writes, safe with WAL
        _DB_CONN.execute("PRAGMA cache_size=-8000")     # 8 MB page cache
    return _DB_CONN

# Singleton genai client
_GENAI_CLIENT: genai.Client | None = None


def _client() -> genai.Client:
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        _GENAI_CLIENT = genai.Client(api_key=get_api_key())
    return _GENAI_CLIENT


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Database init ─────────────────────────────────────────────────────────────
def _init_db() -> None:
    db = _conn()
    with db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            student_id      TEXT PRIMARY KEY,
            child_name      TEXT NOT NULL,
            age             TEXT DEFAULT '',
            grade           TEXT DEFAULT '',
            parent_name     TEXT DEFAULT '',
            notes           TEXT DEFAULT '',
            latest_homework TEXT DEFAULT '',
            created_at      TEXT,
            updated_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id      TEXT NOT NULL,
            session_date    TEXT NOT NULL,
            summary         TEXT DEFAULT '',
            topics_json     TEXT DEFAULT '[]',
            child_msgs_json TEXT DEFAULT '[]',
            tutor_msgs_json TEXT DEFAULT '[]',
            interruptions   INTEGER DEFAULT 0,
            created_at      TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        );

        CREATE TABLE IF NOT EXISTS homework_log (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id        TEXT NOT NULL,
            board_content     TEXT DEFAULT '',
            generated_content TEXT DEFAULT '',
            assigned_at       TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        );

        CREATE TABLE IF NOT EXISTS homework_checks (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id         TEXT NOT NULL,
            assignment_preview TEXT DEFAULT '',
            feedback           TEXT DEFAULT '',
            checked_at         TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        );

        CREATE TABLE IF NOT EXISTS parent_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  TEXT NOT NULL,
            role        TEXT NOT NULL,
            text        TEXT NOT NULL,
            created_at  TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        );

        CREATE TABLE IF NOT EXISTS syllabus_progress (
            student_id  TEXT NOT NULL,
            topic_id    TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            updated_at  TEXT,
            PRIMARY KEY (student_id, topic_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        );

        CREATE TABLE IF NOT EXISTS parent_tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  TEXT NOT NULL,
            task_text   TEXT NOT NULL,
            subject     TEXT DEFAULT '',
            status      TEXT DEFAULT 'open',
            created_at  TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        );
        """)
    _migrate_schema_v2()


def _migrate_schema_v2() -> None:
    """Add columns/tables for older DB files."""
    db = _conn()
    cols = {r[1] for r in db.execute("PRAGMA table_info(students)").fetchall()}
    if "parent_summary" not in cols:
        db.execute("ALTER TABLE students ADD COLUMN parent_summary TEXT DEFAULT ''")
    if "current_topic_id" not in cols:
        db.execute("ALTER TABLE students ADD COLUMN current_topic_id TEXT DEFAULT ''")
    if "weak_subjects" not in cols:
        db.execute("ALTER TABLE students ADD COLUMN weak_subjects TEXT DEFAULT ''")
    db.commit()


_init_db()
_migrate_done = False


def _migrate_legacy_json() -> None:  # called at end of module after all functions are defined
    """One-time import of old JSON data into SQLite."""
    global _migrate_done
    if _migrate_done:
        return
    _migrate_done = True

    old_students = DATA_DIR / "students.json"
    if not old_students.exists():
        return
    try:
        raw = json.loads(old_students.read_text(encoding="utf-8"))
        students = raw.get("students", {})
        for sid, s in students.items():
            if get_student(sid):
                continue
                with _conn() as db:
                    db.execute(
                        """INSERT OR IGNORE INTO students
                           (student_id, child_name, age, grade, parent_name, notes,
                            latest_homework, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            s.get("student_id", sid),
                            s.get("child_name", ""),
                            s.get("age", ""),
                            s.get("grade", ""),
                            s.get("parent_name", ""),
                            s.get("notes", ""),
                            s.get("latest_homework", ""),
                            s.get("created_at", _now_iso()),
                            s.get("updated_at", _now_iso()),
                        ),
                    )

        # Migrate activity logs
        acts_dir = DATA_DIR / "activities"
        if acts_dir.exists():
            for act_file in acts_dir.glob("*.json"):
                sid = act_file.stem
                if not get_student(sid):
                    continue
                try:
                    acts = json.loads(act_file.read_text(encoding="utf-8"))
                    for a in (acts if isinstance(acts, list) else []):
                        atype = a.get("type", "")
                        details = a.get("details", {})
                        ts = a.get("timestamp", _now_iso())
                        date_str = ts[:10]
                        if atype == "live_session":
                            child_msgs = details.get("child_said", [])
                            tutor_msgs = details.get("tutor_said", [])
                            summary = a.get("summary", "")
                            with _conn() as db:
                                db.execute(
                                    """INSERT OR IGNORE INTO sessions
                                       (student_id, session_date, summary,
                                        child_msgs_json, tutor_msgs_json,
                                        interruptions, created_at)
                                       VALUES (?,?,?,?,?,?,?)""",
                                    (
                                        sid, date_str, summary,
                                        json.dumps(child_msgs),
                                        json.dumps(tutor_msgs),
                                        details.get("interruptions", 0),
                                        ts,
                                    ),
                                )
                        elif atype == "homework_assigned":
                            content = details.get("content_preview", "")
                            with _conn() as db:
                                db.execute(
                                    """INSERT OR IGNORE INTO homework_log
                                       (student_id, board_content, assigned_at)
                                       VALUES (?,?,?)""",
                                    (sid, content, ts),
                                )
                        elif atype == "homework_check":
                            with _conn() as db:
                                db.execute(
                                    """INSERT OR IGNORE INTO homework_checks
                                       (student_id, assignment_preview, feedback, checked_at)
                                       VALUES (?,?,?,?)""",
                                    (
                                        sid,
                                        details.get("assignment_preview", "")[:400],
                                        details.get("feedback", "")[:2000],
                                        ts,
                                    ),
                                )
                except Exception:
                    pass
    except Exception as e:
        print(f"[SHIKSHA] Legacy JSON migration skipped: {e}")


# ── ID generation ─────────────────────────────────────────────────────────────
def _generate_id() -> str:
    with _conn() as db:
        row = db.execute(
            "SELECT MAX(CAST(SUBSTR(student_id,2) AS INTEGER)) AS m "
            "FROM students WHERE student_id GLOB 'S[0-9]*'"
        ).fetchone()
    n = row["m"] if row and row["m"] is not None else 0
    return f"S{n + 1}"


# ── Student CRUD ──────────────────────────────────────────────────────────────
def get_student(student_id: str) -> dict[str, Any] | None:
    if not student_id:
        return None
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM students WHERE student_id = ?",
            (student_id.strip().upper(),),
        ).fetchone()
    return dict(row) if row else None


def list_students() -> list[dict[str, Any]]:
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM students ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def search_students(query: str) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    with _conn() as db:
        rows = db.execute(
            """SELECT * FROM students
               WHERE UPPER(student_id) = ?
                  OR LOWER(student_id) LIKE ?
                  OR LOWER(child_name) LIKE ?
               ORDER BY updated_at DESC""",
            (q.upper(), f"%{q.lower()}%", f"%{q.lower()}%"),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_student(
    child_name: str,
    age: str = "",
    grade: str = "",
    parent_name: str = "",
    notes: str = "",
    latest_homework: str = "",
    student_id: str | None = None,
) -> dict[str, Any]:
    name = child_name.strip()
    if not name:
        raise ValueError("Child name is required.")
    now = _now_iso()

    # Resolve by ID or find by name
    if not student_id:
        with _conn() as db:
            row = db.execute(
                "SELECT student_id FROM students WHERE LOWER(child_name) = ?",
                (name.lower(),),
            ).fetchone()
        if row:
            student_id = row["student_id"]

    sid_upper = (student_id or "").strip().upper()

    with _conn() as db:
        existing = db.execute(
            "SELECT student_id FROM students WHERE student_id = ?", (sid_upper,)
        ).fetchone() if sid_upper else None

        if existing:
            if latest_homework.strip():
                db.execute(
                    """UPDATE students SET child_name=?, age=?, grade=?, parent_name=?,
                       notes=?, latest_homework=?, updated_at=? WHERE student_id=?""",
                    (name, age.strip(), grade.strip(), parent_name.strip(),
                     notes.strip(), latest_homework.strip(), now, sid_upper),
                )
            else:
                db.execute(
                    """UPDATE students SET child_name=?, age=?, grade=?, parent_name=?,
                       notes=?, updated_at=? WHERE student_id=?""",
                    (name, age.strip(), grade.strip(), parent_name.strip(),
                     notes.strip(), now, sid_upper),
                )
            student_id = sid_upper
        else:
            new_sid = sid_upper or _generate_id()
            db.execute(
                """INSERT INTO students
                   (student_id, child_name, age, grade, parent_name, notes,
                    latest_homework, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (new_sid, name, age.strip(), grade.strip(), parent_name.strip(),
                 notes.strip(), latest_homework.strip(), now, now),
            )
            student_id = new_sid

    if grade.strip():
        try:
            init_syllabus_progress_for_grade(student_id, grade.strip())
        except Exception:
            pass

    _write_json_snapshot()
    return get_student(student_id)


# ── Session logging ───────────────────────────────────────────────────────────
def log_live_session(
    student_id: str, messages: list[dict[str, str]], interruptions: int
) -> None:
    if not student_id:
        return
    child_msgs = [m["text"] for m in messages if m.get("role") == "user"][-20:]
    tutor_msgs = [m["text"] for m in messages if m.get("role") == "assistant"][-20:]
    if not child_msgs and not tutor_msgs:
        return

    # Build a concise summary from tutor messages (no extra API call needed)
    sample = " | ".join(tutor_msgs[-6:])
    summary = f"Tutor covered: {sample[:500]}" if sample else "Session completed."

    with _conn() as db:
        db.execute(
            """INSERT INTO sessions
               (student_id, session_date, summary, topics_json,
                child_msgs_json, tutor_msgs_json, interruptions, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                student_id, _today(), summary, json.dumps([]),
                json.dumps(child_msgs), json.dumps(tutor_msgs),
                interruptions, _now_iso(),
            ),
        )


def log_homework_assigned(student_id: str, board: str, generated: str) -> None:
    if not student_id or not (board or generated).strip():
        return
    content = (generated or board).strip()
    with _conn() as db:
        db.execute(
            """INSERT INTO homework_log
               (student_id, board_content, generated_content, assigned_at)
               VALUES (?,?,?,?)""",
            (student_id, board, generated, _now_iso()),
        )
        # Keep latest_homework on student record for quick access
        db.execute(
            "UPDATE students SET latest_homework=?, updated_at=? WHERE student_id=?",
            (content[:2000], _now_iso(), student_id),
        )


def log_homework_check(student_id: str, assignment_preview: str, feedback: str) -> None:
    if not student_id:
        return
    with _conn() as db:
        db.execute(
            """INSERT INTO homework_checks
               (student_id, assignment_preview, feedback, checked_at)
               VALUES (?,?,?,?)""",
            (student_id, assignment_preview[:400], feedback[:2000], _now_iso()),
        )


# ── Context builders ──────────────────────────────────────────────────────────
def build_student_session_context(student: dict[str, Any]) -> str:
    """
    Rich memory context injected into SHIKSHA's system instruction before each
    live voice session.  SHIKSHA reads this and knows EXACTLY:
      - Who the student is
      - What was covered in the last N lessons
      - What homework was given last time
      - Whether homework was checked, and what the feedback was
    So she NEVER asks "what did we learn last time?" — she already knows.
    """
    sid = student.get("student_id", "")
    name = student.get("child_name") or "beta"

    with _conn() as db:
        # Last N sessions, newest first
        sessions = db.execute(
            """SELECT session_date, summary, child_msgs_json, tutor_msgs_json
               FROM sessions WHERE student_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (sid, MAX_SESSIONS_IN_CONTEXT),
        ).fetchall()

        # Most recent homework assigned
        last_hw = db.execute(
            """SELECT board_content, generated_content, assigned_at
               FROM homework_log WHERE student_id=?
               ORDER BY assigned_at DESC LIMIT 1""",
            (sid,),
        ).fetchone()

        # Most recent homework check
        last_check = db.execute(
            """SELECT feedback, checked_at
               FROM homework_checks WHERE student_id=?
               ORDER BY checked_at DESC LIMIT 1""",
            (sid,),
        ).fetchone()

    lines = [
        "## STUDENT PROFILE",
        f"- Student ID : {student.get('student_id')}",
        f"- Name       : {name}",
        f"- Age        : {student.get('age') or 'unknown'}",
        f"- Class/Grade: {student.get('grade') or 'unknown'}",
        f"- Parent     : {student.get('parent_name') or 'unknown'}",
    ]
    if student.get("notes"):
        lines.append(f"- Notes      : {student['notes']}")

    lines += [
        "",
        "## SESSION START — YOU SPEAK FIRST (ALWAYS)",
        f"The child may be nervous on mic. YOU always break the silence first.",
        f"1. Greet {name} warmly: \"Hello {name}! Main hoon Shiksha Di — aapki teacher!\"",
        f"2. Ask 2–3 easy fun questions before any lesson (favourite colour, what they ate, did they play).",
        f"3. Say: \"Koi bhi galat jawab nahi hai, beta — we will have so much fun today!\"",
        f"4. ONLY after they relax, start the lesson.",
    ]

    # ── Session history ──────────────────────────────────────────────────────
    if sessions:
        lines += [
            "",
            f"## YOUR MEMORY — LAST {len(sessions)} SESSIONS",
            f"⚠️ You ALREADY KNOW all this. Do NOT ask {name} 'what did we study last time?'",
            f"Instead say naturally: 'Last time we covered [topic] — let's quickly revisit!'",
            "",
        ]
        for i, s in enumerate(sessions):
            label = "LAST SESSION" if i == 0 else f"{i + 1} SESSIONS AGO"
            lines.append(f"### {label} — {s['session_date']}")
            lines.append(f"  Covered : {(s['summary'] or '(no summary)')[:400]}")
            try:
                child_said = json.loads(s["child_msgs_json"] or "[]")[-3:]
                if child_said:
                    lines.append(f"  Child said (sample): {' | '.join(child_said)}")
            except Exception:
                pass
            lines.append("")
    else:
        lines += [
            "",
            "## FIRST SESSION WITH THIS STUDENT",
            "No previous sessions recorded yet.",
            f"This is {name}'s FIRST lesson — introduce yourself warmly and spend extra time making them comfortable.",
        ]

    # ── Last homework ────────────────────────────────────────────────────────
    if last_hw:
        assigned_date = (last_hw["assigned_at"] or "")[:10]
        hw_content = (last_hw["generated_content"] or last_hw["board_content"] or "").strip()
        if hw_content:
            lines += [
                "## HOMEWORK GIVEN LAST TIME",
                f"Assigned on: {assigned_date}",
                hw_content[:600],
                "",
                f"⚠️ TODAY: Start by checking this homework with {name}!",
                f"Ask warmly: 'Beta, homework kiya? Chalo milke dekhte hain!'",
                "",
            ]

    # ── Last homework check ──────────────────────────────────────────────────
    if last_check:
        check_date = (last_check["checked_at"] or "")[:10]
        feedback_preview = (last_check["feedback"] or "").strip()[:300]
        if feedback_preview:
            lines += [
                "## LAST HOMEWORK CHECK RESULT",
                f"Checked on: {check_date}",
                f"Feedback  : {feedback_preview}",
                f"Reference : 'Last time your homework feedback said [result] — aaj aur better karenge!'",
                "",
            ]

    # Syllabus context (class + progress)
    grade = student.get("grade") or ""
    if grade:
        try:
            from syllabus import build_syllabus_context_for_prompt

            progress_map = get_syllabus_progress_map(sid)
            current_topic = student.get("current_topic_id") or ""
            lines += [
                "",
                build_syllabus_context_for_prompt(
                    grade, progress_map, current_topic or None
                ),
            ]
        except Exception:
            pass

    return "\n".join(lines)


# ── Parent chat persistence ───────────────────────────────────────────────────
def save_parent_message(student_id: str, role: str, text: str) -> None:
    if not student_id or not text.strip():
        return
    with _conn() as db:
        db.execute(
            """INSERT INTO parent_messages (student_id, role, text, created_at)
               VALUES (?,?,?,?)""",
            (student_id, role, text.strip(), _now_iso()),
        )
    refresh_parent_summary(student_id)


def load_parent_messages(student_id: str, limit: int = 50) -> list[dict[str, str]]:
    if not student_id:
        return []
    with _conn() as db:
        rows = db.execute(
            """SELECT role, text FROM parent_messages
               WHERE student_id=? ORDER BY id ASC LIMIT ?""",
            (student_id, limit),
        ).fetchall()
    return [{"role": r["role"], "text": r["text"]} for r in rows]


def clear_parent_messages(student_id: str) -> None:
    if not student_id:
        return
    with _conn() as db:
        db.execute("DELETE FROM parent_messages WHERE student_id=?", (student_id,))
        db.execute(
            "UPDATE students SET parent_summary='' WHERE student_id=?",
            (student_id,),
        )


def refresh_parent_summary(student_id: str) -> None:
    """Rule-based rolling memory for natural parent greetings (no extra API call)."""
    student = get_student(student_id)
    if not student:
        return
    msgs = load_parent_messages(student_id, limit=20)
    parent_lines = [m["text"] for m in msgs if m["role"] == "parent"][-3:]
    assistant_lines = [m["text"] for m in msgs if m["role"] == "assistant"][-3:]
    parts = [
        f"Child: {student.get('child_name')}. Class: {student.get('grade') or 'not set'}.",
    ]
    if parent_lines:
        parts.append("Last parent topics: " + " | ".join(parent_lines)[:400])
    if assistant_lines:
        parts.append("Last SHIKSHA advice: " + " | ".join(assistant_lines)[:400])
    if student.get("weak_subjects"):
        parts.append(f"Focus areas noted: {student['weak_subjects']}")
    summary = "\n".join(parts)
    with _conn() as db:
        db.execute(
            "UPDATE students SET parent_summary=?, updated_at=? WHERE student_id=?",
            (summary[:2000], _now_iso(), student_id),
        )


def get_parent_opening_hint(student_id: str) -> str:
    """Short hint for parent chat greeting style."""
    student = get_student(student_id)
    if not student:
        return ""
    summary = (student.get("parent_summary") or "").strip()
    if summary:
        return summary
    return f"First conversation with parent of {student.get('child_name')}."


# ── Syllabus progress ─────────────────────────────────────────────────────────
def get_syllabus_progress_map(student_id: str) -> dict[str, str]:
    if not student_id:
        return {}
    with _conn() as db:
        rows = db.execute(
            "SELECT topic_id, status FROM syllabus_progress WHERE student_id=?",
            (student_id,),
        ).fetchall()
    return {r["topic_id"]: r["status"] for r in rows}


def set_topic_progress(student_id: str, topic_id: str, status: str) -> None:
    if not student_id or not topic_id:
        return
    status = status if status in ("pending", "in_progress", "done") else "pending"
    with _conn() as db:
        db.execute(
            """INSERT INTO syllabus_progress (student_id, topic_id, status, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(student_id, topic_id) DO UPDATE SET
                 status=excluded.status, updated_at=excluded.updated_at""",
            (student_id, topic_id, status, _now_iso()),
        )
        if status == "in_progress":
            db.execute(
                "UPDATE students SET current_topic_id=?, updated_at=? WHERE student_id=?",
                (topic_id, _now_iso(), student_id),
            )


def init_syllabus_progress_for_grade(student_id: str, grade: str) -> None:
    """Ensure all topics from class syllabus exist as pending."""
    from syllabus import load_syllabus

    existing = set(get_syllabus_progress_map(student_id).keys())
    with _conn() as db:
        for t in load_syllabus(grade).get("topics", []):
            tid = t.get("id")
            if not tid or tid in existing:
                continue
            db.execute(
                """INSERT OR IGNORE INTO syllabus_progress
                   (student_id, topic_id, status, updated_at)
                   VALUES (?,?,?,?)""",
                (student_id, tid, "pending", _now_iso()),
            )


def get_progress_chart_data(student_id: str) -> dict[str, Any]:
    """Simple stats for parent UI chart."""
    grade = (get_student(student_id) or {}).get("grade", "")
    progress_map = get_syllabus_progress_map(student_id)
    done = sum(1 for s in progress_map.values() if s == "done")
    in_prog = sum(1 for s in progress_map.values() if s == "in_progress")
    pending = sum(1 for s in progress_map.values() if s == "pending")
    with _conn() as db:
        sessions_n = db.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE student_id=?", (student_id,)
        ).fetchone()["c"]
        checks_n = db.execute(
            "SELECT COUNT(*) AS c FROM homework_checks WHERE student_id=?", (student_id,)
        ).fetchone()["c"]
    return {
        "grade": grade,
        "syllabus_done": done,
        "syllabus_in_progress": in_prog,
        "syllabus_pending": pending,
        "live_sessions": sessions_n,
        "homework_checks": checks_n,
    }


# ── Parent tasks ──────────────────────────────────────────────────────────────
def add_parent_task(student_id: str, task_text: str, subject: str = "") -> dict[str, Any]:
    if not student_id or not task_text.strip():
        raise ValueError("Task text required.")
    with _conn() as db:
        cur = db.execute(
            """INSERT INTO parent_tasks (student_id, task_text, subject, status, created_at)
               VALUES (?,?,?,?,?)""",
            (student_id, task_text.strip(), subject.strip(), "open", _now_iso()),
        )
        tid = cur.lastrowid
    return {"id": tid, "task_text": task_text.strip(), "subject": subject, "status": "open"}


def list_parent_tasks(student_id: str) -> list[dict[str, Any]]:
    if not student_id:
        return []
    with _conn() as db:
        rows = db.execute(
            """SELECT id, task_text, subject, status, created_at FROM parent_tasks
               WHERE student_id=? ORDER BY id DESC LIMIT 30""",
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_parent_task_status(task_id: int, status: str) -> None:
    if status not in ("open", "done"):
        status = "open"
    with _conn() as db:
        db.execute(
            "UPDATE parent_tasks SET status=? WHERE id=?",
            (status, task_id),
        )


def build_progress_context(student_id: str) -> str:
    """Full context for parent chat and report card generation."""
    student = get_student(student_id) if student_id else None
    if not student:
        return "## Student profile\n(No student selected. Search by name or Student ID.)"

    with _conn() as db:
        sessions = db.execute(
            """SELECT session_date, summary, child_msgs_json FROM sessions
               WHERE student_id=? ORDER BY created_at DESC LIMIT 25""",
            (student_id,),
        ).fetchall()
        hw_log = db.execute(
            """SELECT board_content, generated_content, assigned_at FROM homework_log
               WHERE student_id=? ORDER BY assigned_at DESC LIMIT 5""",
            (student_id,),
        ).fetchall()
        hw_checks = db.execute(
            """SELECT assignment_preview, feedback, checked_at FROM homework_checks
               WHERE student_id=? ORDER BY checked_at DESC LIMIT 5""",
            (student_id,),
        ).fetchall()

    parent_summary = (student.get("parent_summary") or "").strip()
    lines = [
        "## Student profile",
        f"Student ID : {student['student_id']}",
        f"Name       : {student['child_name']}",
        f"Age        : {student.get('age') or '(not set)'}",
        f"Grade      : {student.get('grade') or '(not set)'}",
        f"Parent     : {student.get('parent_name') or '(not set)'}",
        f"Notes      : {student.get('notes') or '(none)'}",
    ]
    if parent_summary:
        lines += ["", "## Memory from last parent conversations", parent_summary]
    if student.get("weak_subjects"):
        lines += ["", "## Subjects needing extra focus", student["weak_subjects"]]
    lines += ["", f"## Session history ({len(sessions)} total sessions recorded)"]
    for s in sessions:
        lines.append(f"  [{s['session_date']}] {(s['summary'] or '')[:200]}")

    if hw_log:
        lines += ["", "## Homework assigned (recent)"]
        for h in hw_log:
            d = (h["assigned_at"] or "")[:10]
            c = (h["generated_content"] or h["board_content"] or "")[:200]
            lines.append(f"  [{d}] {c}")

    if hw_checks:
        lines += ["", "## Homework checks (recent)"]
        for c in hw_checks:
            d = (c["checked_at"] or "")[:10]
            lines.append(f"  [{d}] {(c['feedback'] or '')[:200]}")

    grade = student.get("grade") or ""
    if grade:
        try:
            from syllabus import build_syllabus_context_for_prompt

            lines += [
                "",
                build_syllabus_context_for_prompt(grade, get_syllabus_progress_map(student_id)),
            ]
        except Exception:
            pass

    return "\n".join(lines)


# ── JSON snapshot — written instantly on every student create/update ───────────
def _write_json_snapshot() -> None:
    """
    Write a human-readable JSON file to data/students_snapshot.json.
    Pure stdlib — no pandas, no openpyxl — completes in <1 ms.
    Open this file in any text editor or VS Code to inspect all student data.
    """
    try:
        db = _conn()
        students = [dict(r) for r in db.execute(
            "SELECT * FROM students ORDER BY updated_at DESC"
        ).fetchall()]

        # Attach recent session count and last session date for quick reference
        for s in students:
            sid = s["student_id"]
            row = db.execute(
                "SELECT COUNT(*) AS total, MAX(session_date) AS last_date "
                "FROM sessions WHERE student_id=?", (sid,)
            ).fetchone()
            s["total_sessions"] = row["total"] if row else 0
            s["last_session_date"] = row["last_date"] if row else None

            hw = db.execute(
                "SELECT MAX(assigned_at) AS last FROM homework_log WHERE student_id=?",
                (sid,),
            ).fetchone()
            s["last_homework_assigned"] = (hw["last"] or "")[:10] if hw else None

        snapshot = {
            "exported_at": _now_iso(),
            "total_students": len(students),
            "students": students,
        }
        JSON_SNAPSHOT_PATH.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[SHIKSHA] JSON snapshot skipped: {e}")


# ── AI helpers ────────────────────────────────────────────────────────────────
# Models that are deprecated / no longer available via generateContent
_DEPRECATED_MODELS = {"gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro", "gemini-pro"}


def _text_model() -> str:
    # Prefer explicit text model env var
    m = os.getenv("GEMINI_TEXT_MODEL", "").strip()
    if m and m not in _DEPRECATED_MODELS:
        return m
    # Fall back to GEMINI_MODEL if it's a non-live, non-deprecated model
    m2 = os.getenv("GEMINI_MODEL", "").strip()
    if m2 and "live" not in m2.lower() and m2 not in _DEPRECATED_MODELS:
        return m2
    return DEFAULT_TEXT_MODEL


def _is_quota_err(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("resource_exhausted", "quota", "rate-limit"))


def generate_report_card(student_id: str, extra_parent_notes: str = "") -> str:
    student = get_student(student_id)
    if not student:
        raise ValueError("Student not found. Search by name or Student ID first.")
    context = build_progress_context(student_id)
    child = student.get("child_name") or "the student"
    sid = student.get("student_id")

    prompt = f"""You are {ASSISTANT_NAME}, writing a REPORT CARD for parents.

{context}

{f"Parent added notes: {extra_parent_notes}" if extra_parent_notes.strip() else ""}

Write a full, kind report card for {child} (ID: {sid}).

# Report Card — {child}
**Student ID:** {sid}
**Date:** {datetime.now().strftime("%d %B %Y")}
**Class / Age:** {student.get("grade") or "—"} / {student.get("age") or "—"}

## Dear Parents
## Overall progress
## Strengths
## Areas to improve
## Subjects & skills observed
## Homework & participation
## Behaviour & attitude
## Recommendations for home
## Teacher's message to the child
## Signature
{ASSISTANT_NAME}

Be honest and kind. Base everything only on recorded session data — do not invent scores."""

    try:
        r = _client().models.generate_content(model=_text_model(), contents=prompt)
        return (r.text or "").strip()
    except Exception as exc:
        if _is_quota_err(exc):
            return _fallback_report(student, context, extra_parent_notes)
        raise RuntimeError(f"Report card failed: {exc}") from exc


def _fallback_report(student: dict, context: str, notes: str = "") -> str:
    child = student.get("child_name") or "student"
    sid = student.get("student_id") or "unknown"
    return (
        f"# Report Card — {child}\n"
        f"**Student ID:** {sid}\n"
        f"**Date:** {datetime.now().strftime('%d %B %Y')}\n\n"
        f"*AI quota exhausted — report generated from saved session data.*\n\n"
        f"## Student activity\n{context}\n\n"
        f"## Parent notes\n{notes or 'None provided.'}\n\n"
        f"## Signature\n{ASSISTANT_NAME}\n"
    )


def answer_parent_message(
    student_id: str,
    parent_message: str,
    chat_history: list[dict[str, str]] | None = None,
) -> str:
    if not student_id:
        raise ValueError("No student selected. Please load a student first from Parent Corner.")
    student = get_student(student_id)
    if not student:
        raise ValueError(f"Student '{student_id}' not found in database.")
    context = build_progress_context(student_id)
    child = student.get("child_name") or "your child"
    sid = student.get("student_id") or "unknown"
    parent_memory = get_parent_opening_hint(student_id)
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['text']}" for m in (chat_history or [])[-8:]
    )
    is_greeting = any(
        w in parent_message.lower()
        for w in ("hello", "hi", "namaste", "shiksha", "how is", "kaise", "beti", "beta", "son", "daughter")
    )
    greeting_guide = ""
    if is_greeting and parent_memory:
        greeting_guide = (
            f"\nStart with a warm greeting to the parent by name if known. "
            f"Reference last conversation naturally: {parent_memory[:500]}\n"
            f"Mention child's progress in subjects where you have data. "
            f"Suggest what parents can focus on at home.\n"
        )

    prompt = f"""You are {ASSISTANT_NAME}, speaking to a PARENT about their child.

Child: {child} | Student ID: {sid}

{context}

Parent relationship memory:
{parent_memory or "(first parent chat — introduce yourself warmly)"}
{greeting_guide}

Recent chat:
{history_text or "(none)"}

Parent says:
{parent_message}

Reply warmly and professionally in clear English (Hinglish OK for warmth).
Use only evidence from the data above — do not invent test scores.
If parent asks about progress, mention strengths, weak areas, homework, and syllabus topics covered vs pending.
Always mention Student ID ({sid}) once if helpful."""

    try:
        r = _client().models.generate_content(model=_text_model(), contents=prompt)
        result = (r.text or "").strip()
        if not result:
            raise ValueError("AI returned empty response. Please try again.")
        save_parent_message(student_id, "parent", parent_message)
        save_parent_message(student_id, "assistant", result)
        return result
    except Exception as exc:
        if _is_quota_err(exc):
            return f"AI quota exhausted. Please try again in a few minutes. Student ID: {sid}."
        raise RuntimeError(f"Parent chat failed: {exc}") from exc


# ── Legacy compatibility ───────────────────────────────────────────────────────
def load_profile() -> dict[str, Any]:
    students = list_students()
    if students:
        return students[0]
    return {"child_name": "", "age": "", "grade": "", "parent_name": "",
            "notes": "", "student_id": ""}


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return upsert_student(
        child_name=profile.get("child_name", ""),
        age=profile.get("age", ""),
        grade=profile.get("grade", ""),
        parent_name=profile.get("parent_name", ""),
        notes=profile.get("notes", ""),
        latest_homework=profile.get("latest_homework", ""),
        student_id=profile.get("student_id") or None,
    )


def load_activities(student_id: str) -> list[dict[str, Any]]:
    """Legacy: returns sessions list."""
    if not student_id:
        return []
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM sessions WHERE student_id=? ORDER BY created_at ASC",
            (student_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Run legacy migration once all functions are available ──────────────────────
_migrate_legacy_json()
