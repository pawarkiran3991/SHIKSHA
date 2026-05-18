"""Multi-student progress tracking, IDs, and parent report cards for SHIKSHA."""

from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai

from main import ASSISTANT_NAME, get_api_key, load_env_file

load_env_file()

DATA_DIR = Path(__file__).resolve().parent / "data"
STUDENTS_PATH = DATA_DIR / "students.json"
ACTIVITIES_DIR = DATA_DIR / "activities"
CHATS_DIR = DATA_DIR / "chats"
HOMEWORK_DIR = DATA_DIR / "homework"
LEGACY_PROFILE_PATH = DATA_DIR / "student_profile.json"
LEGACY_ACTIVITY_PATH = DATA_DIR / "activity_log.json"
MAX_ACTIVITIES_PER_STUDENT = 80
MAX_SAVED_CHAT_MESSAGES = 100
ID_PREFIX = "SHK-"
DEFAULT_TEXT_MODEL = "gemini-2.0-flash"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVITIES_DIR.mkdir(parents=True, exist_ok=True)
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    HOMEWORK_DIR.mkdir(parents=True, exist_ok=True)


def _generate_id() -> str:
    chars = string.ascii_uppercase + string.digits
    for _ in range(50):
        suffix = "".join(secrets.choice(chars) for _ in range(6))
        candidate = f"{ID_PREFIX}{suffix}"
        if candidate not in load_registry()["students"]:
            return candidate
    raise RuntimeError("Could not generate a unique student ID.")


def load_registry() -> dict[str, Any]:
    _ensure_data_dir()
    _migrate_legacy_data()
    if not STUDENTS_PATH.exists():
        return {"students": {}}
    data = json.loads(STUDENTS_PATH.read_text(encoding="utf-8"))
    if "students" not in data:
        data["students"] = {}
    return data


def save_registry(registry: dict[str, Any]) -> None:
    _ensure_data_dir()
    STUDENTS_PATH.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _migrate_legacy_data() -> None:
    if STUDENTS_PATH.exists():
        return
    if not LEGACY_PROFILE_PATH.exists() and not LEGACY_ACTIVITY_PATH.exists():
        return

    profile: dict[str, Any] = {}
    if LEGACY_PROFILE_PATH.exists():
        profile = json.loads(LEGACY_PROFILE_PATH.read_text(encoding="utf-8"))

    name = (profile.get("child_name") or "Student").strip() or "Student"
    chars = string.ascii_uppercase + string.digits
    sid = f"{ID_PREFIX}{''.join(secrets.choice(chars) for _ in range(6))}"
    now = _now_iso()
    record = {
        "student_id": sid,
        "child_name": name,
        "age": profile.get("age", ""),
        "grade": profile.get("grade", ""),
        "parent_name": profile.get("parent_name", ""),
        "notes": profile.get("notes", ""),
        "created_at": now,
        "updated_at": now,
    }
    save_registry({"students": {sid: record}})

    if LEGACY_ACTIVITY_PATH.exists():
        old = json.loads(LEGACY_ACTIVITY_PATH.read_text(encoding="utf-8"))
        if isinstance(old, list) and old:
            _activity_path(sid).write_text(
                json.dumps(old, indent=2, ensure_ascii=False), encoding="utf-8"
            )


def _activity_path(student_id: str) -> Path:
    safe = student_id.replace("/", "_")
    return ACTIVITIES_DIR / f"{safe}.json"


def get_student(student_id: str) -> dict[str, Any] | None:
    registry = load_registry()
    return registry["students"].get(student_id)


def list_students() -> list[dict[str, Any]]:
    registry = load_registry()
    students = list(registry["students"].values())
    students.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return students


def search_students(query: str) -> list[dict[str, Any]]:
    """Search by ID or name (legacy — matches both)."""
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for student in search_students_by_mode(query, "Student ID") + search_students_by_mode(
        query, "Name"
    ):
        sid = student["student_id"]
        if sid not in seen:
            seen.add(sid)
            results.append(student)
    return results


def search_students_by_mode(query: str, mode: str) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []
    if mode == "Student ID":
        student = get_student(q.upper())
        return [student] if student else []
    q_lower = q.lower()
    return [
        s
        for s in list_students()
        if q_lower in (s.get("child_name") or "").lower()
    ]


def _chat_path(student_id: str, kind: str) -> Path:
    safe = student_id.replace("/", "_")
    return CHATS_DIR / f"{safe}_{kind}.json"


def save_live_chat(student_id: str, messages: list[dict[str, str]]) -> None:
    if not student_id:
        return
    _ensure_data_dir()
    saved = [
        {"role": m["role"], "text": m["text"]}
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("text")
    ]
    _chat_path(student_id, "live").write_text(
        json.dumps(saved[-MAX_SAVED_CHAT_MESSAGES:], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_live_chat(student_id: str) -> list[dict[str, str]]:
    if not student_id:
        return []
    path = _chat_path(student_id, "live")
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def save_parent_chat(student_id: str, messages: list[dict[str, str]]) -> None:
    if not student_id:
        return
    _ensure_data_dir()
    _chat_path(student_id, "parent").write_text(
        json.dumps(messages[-50:], indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_parent_chat(student_id: str) -> list[dict[str, str]]:
    if not student_id:
        return []
    path = _chat_path(student_id, "parent")
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def student_summary_for_display(student_id: str) -> str:
    """Full progress text for parent UI after search."""
    return build_progress_context(student_id)


def upsert_student(
    child_name: str,
    age: str = "",
    grade: str = "",
    parent_name: str = "",
    notes: str = "",
    student_id: str | None = None,
) -> dict[str, Any]:
    registry = load_registry()
    name = child_name.strip()
    if not name:
        raise ValueError("Child name is required.")

    now = _now_iso()
    if student_id and student_id in registry["students"]:
        record = registry["students"][student_id]
        record.update(
            {
                "child_name": name,
                "age": age.strip(),
                "grade": grade.strip(),
                "parent_name": parent_name.strip(),
                "notes": notes.strip(),
                "updated_at": now,
            }
        )
    else:
        student_id = student_id or _generate_id()
        record = {
            "student_id": student_id,
            "child_name": name,
            "age": age.strip(),
            "grade": grade.strip(),
            "parent_name": parent_name.strip(),
            "notes": notes.strip(),
            "created_at": now,
            "updated_at": now,
        }
        registry["students"][student_id] = record

    save_registry(registry)
    return dict(registry["students"][student_id])


def load_activities(student_id: str) -> list[dict[str, Any]]:
    if not student_id:
        return []
    path = _activity_path(student_id)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def save_activities(student_id: str, activities: list[dict[str, Any]]) -> None:
    _ensure_data_dir()
    trimmed = activities[-MAX_ACTIVITIES_PER_STUDENT:]
    _activity_path(student_id).write_text(
        json.dumps(trimmed, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def log_activity(
    student_id: str,
    activity_type: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    if not student_id:
        return
    activities = load_activities(student_id)
    activities.append(
        {
            "timestamp": _now_iso(),
            "type": activity_type,
            "summary": summary[:500],
            "details": details or {},
        }
    )
    save_activities(student_id, activities)


def log_live_session(
    student_id: str, messages: list[dict[str, str]], interruptions: int
) -> None:
    user_lines = [m["text"] for m in messages if m.get("role") == "user"][-15:]
    assistant_lines = [m["text"] for m in messages if m.get("role") == "assistant"][-15:]
    if not user_lines and not assistant_lines:
        return
    summary = f"Live lesson: {len(user_lines)} child turns, {len(assistant_lines)} tutor turns."
    log_activity(
        student_id,
        "live_session",
        summary,
        {
            "interruptions": interruptions,
            "child_said": user_lines,
            "tutor_said": assistant_lines,
        },
    )


def log_homework_check(student_id: str, assignment_preview: str, feedback: str) -> None:
    log_activity(
        student_id,
        "homework_check",
        f"Homework reviewed. Feedback length: {len(feedback)} chars.",
        {
            "assignment_preview": assignment_preview[:300],
            "feedback": feedback[:2000],
        },
    )


def _homework_path(student_id: str) -> Path:
    safe = student_id.replace("/", "_")
    return HOMEWORK_DIR / f"{safe}.json"


def load_student_homework(student_id: str) -> dict[str, Any]:
    if not student_id:
        return {"board": "", "generated": "", "from_voice": ""}
    _ensure_data_dir()
    path = _homework_path(student_id)
    if not path.exists():
        return {"board": "", "generated": "", "from_voice": ""}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "board": data.get("board", ""),
        "generated": data.get("generated", ""),
        "from_voice": data.get("from_voice", ""),
    }


def save_student_homework(
    student_id: str,
    *,
    board: str | None = None,
    generated: str | None = None,
    from_voice: str | None = None,
) -> None:
    if not student_id:
        return
    _ensure_data_dir()
    current = load_student_homework(student_id)
    if board is not None:
        current["board"] = board
    if generated is not None:
        current["generated"] = generated
    if from_voice is not None:
        current["from_voice"] = from_voice
    current["updated_at"] = _now_iso()
    _homework_path(student_id).write_text(
        json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def extract_homework_from_messages(messages: list[dict[str, str]]) -> str:
    """Pull homework SHIKSHA gave during a live lesson (from assistant transcripts)."""
    chunks: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        lower = text.lower()
        has_homework_word = any(
            kw in lower
            for kw in (
                "homework",
                "home work",
                "aaj ka",
                "kal dikha",
                "kal laana",
                "assignment",
                "practice karo",
                "likh kar",
                "yaad karo",
                "task for",
            )
        )
        has_numbered_tasks = sum(
            1 for i in range(1, 8) if f"{i}." in text or f"{i})" in text
        ) >= 2
        if has_homework_word or (has_numbered_tasks and len(text) > 40):
            chunks.append(text)

    if not chunks:
        return ""

    seen: set[str] = set()
    unique: list[str] = []
    for chunk in chunks:
        if chunk not in seen:
            seen.add(chunk)
            unique.append(chunk)

    stamp = datetime.now().strftime("%d %b %Y, %H:%M")
    body = "\n\n---\n\n".join(unique[-4:])
    return f"## Homework from live class ({stamp})\n\n{body}"


def sync_voice_homework(student_id: str, messages: list[dict[str, str]]) -> str:
    """Update stored voice homework if lesson transcripts contain new assignments."""
    extracted = extract_homework_from_messages(messages)
    if not extracted.strip():
        return load_student_homework(student_id).get("from_voice", "")

    stored = load_student_homework(student_id)
    if extracted != stored.get("from_voice", ""):
        save_student_homework(student_id, from_voice=extracted)
        log_homework_assigned(
            student_id,
            extracted[:300],
            "",
        )
    return extracted


def log_homework_assigned(student_id: str, board: str, generated: str) -> None:
    text = generated or board
    if not text.strip() or not student_id:
        return
    log_activity(
        student_id,
        "homework_assigned",
        "New homework tasks assigned.",
        {"content_preview": text[:400]},
    )


def build_student_session_context(student: dict[str, Any]) -> str:
    name = student.get("child_name", "beta")
    return f"""## THIS CHILD (current live session)
- Student ID: {student.get("student_id")}
- Name: {name}
- Age: {student.get("age") or "unknown"}
- Class: {student.get("grade") or "unknown"}
- Parent: {student.get("parent_name") or "unknown"}

## SESSION START — YOU SPEAK TO THE CHILD FIRST (VERY IMPORTANT)
The child may feel nervous on mic. Do NOT stay silent waiting.
1. As soon as the session begins, YOU talk first with a big warm smile in your voice.
2. Greet {name} by name: "Hello {name}! I am Shiksha Di, your teacher friend!"
3. Ask 2–3 easy, fun questions BEFORE any hard lesson — e.g. How are you today? Did you eat something yummy? What is your favourite colour or game? Did you play outside?
4. Listen, praise, laugh lightly — make them feel safe and happy.
5. Say: "Don't be shy, beta — there is no wrong answer here. We will have fun!"
6. Only after they answer and relax, gently start today's lesson or homework."""


def build_progress_context(student_id: str) -> str:
    student = get_student(student_id) if student_id else None
    activities = load_activities(student_id) if student_id else []

    if not student:
        return "## Student profile\n(No student selected. Search by name or Student ID in Parent corner.)"

    lines = [
        "## Student profile",
        f"Student ID: {student.get('student_id')}",
        f"Name: {student.get('child_name')}",
        f"Age: {student.get('age') or '(not set)'}",
        f"Grade: {student.get('grade') or '(not set)'}",
        f"Parent: {student.get('parent_name') or '(not set)'}",
        f"Teacher notes: {student.get('notes') or '(none)'}",
        "",
        "## Activity history (newest last)",
    ]
    if not activities:
        lines.append("(No sessions recorded yet for this student.)")
    else:
        for item in activities[-25:]:
            ts = item.get("timestamp", "")[:10]
            lines.append(f"- [{ts}] {item.get('type')}: {item.get('summary')}")
            details = item.get("details") or {}
            if item.get("type") == "homework_check" and details.get("feedback"):
                lines.append(f"  Feedback excerpt: {details['feedback'][:400]}...")
            if item.get("type") == "live_session":
                child = details.get("child_said") or []
                if child:
                    lines.append(f"  Child said (sample): {' | '.join(child[-3:])}")
    return "\n".join(lines)


def _text_model() -> str:
    import os

    return os.getenv("GEMINI_TEXT_MODEL", DEFAULT_TEXT_MODEL).strip() or DEFAULT_TEXT_MODEL


def _client() -> genai.Client:
    return genai.Client(api_key=get_api_key())


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

Write a report card for {child} (ID: {sid}). If little data exists, say so honestly.

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

Be honest and kind. Do not invent scores without evidence."""

    response = _client().models.generate_content(model=_text_model(), contents=prompt)
    return (response.text or "").strip()


def answer_parent_message(
    student_id: str,
    parent_message: str,
    chat_history: list[dict[str, str]] | None = None,
    image_parts: list[Any] | None = None,
) -> str:
    student = get_student(student_id) if student_id else None
    if not student:
        raise ValueError("Student not found. Search by name or Student ID first.")

    context = build_progress_context(student_id)
    child = student.get("child_name") or "your child"
    sid = student.get("student_id") or "unknown"
    history = chat_history or []
    history_text = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in history[-8:])

    prompt = f"""You are {ASSISTANT_NAME}, speaking to a PARENT about their child.

Child: {child} | Student ID: {sid}

{context}

Recent chat:
{history_text or "(none)"}

Parent says:
{parent_message}

Reply warmly and professionally. Use the child's activity data and any attachment they sent.
If they attached homework or a photo, comment on what you see.
Do not invent test scores. Mention Student ID ({sid}) once if helpful."""

    contents: list[Any] = [prompt]
    if image_parts:
        contents.extend(image_parts)

    response = _client().models.generate_content(model=_text_model(), contents=contents)
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty response from AI. Check GEMINI_API_KEY and model name.")
    log_activity(
        student_id,
        "parent_chat",
        f"Parent asked: {parent_message[:120]}",
        {"reply_preview": text[:500]},
    )
    return text


# Backward-compatible helpers for code expecting load_profile / save_profile
def load_profile() -> dict[str, Any]:
    students = list_students()
    if students:
        return students[0]
    return {
        "child_name": "",
        "age": "",
        "grade": "",
        "parent_name": "",
        "notes": "",
        "student_id": "",
    }


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    sid = profile.get("student_id") or None
    return upsert_student(
        child_name=profile.get("child_name", ""),
        age=profile.get("age", ""),
        grade=profile.get("grade", ""),
        parent_name=profile.get("parent_name", ""),
        notes=profile.get("notes", ""),
        student_id=sid,
    )
