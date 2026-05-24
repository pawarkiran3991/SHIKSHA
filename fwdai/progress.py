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
EXCEL_PATH = DATA_DIR / "students.xlsx"
ACTIVITIES_DIR = DATA_DIR / "activities"
LEGACY_PROFILE_PATH = DATA_DIR / "student_profile.json"
LEGACY_ACTIVITY_PATH = DATA_DIR / "activity_log.json"
MAX_ACTIVITIES_PER_STUDENT = 80
ID_PREFIX = "S"
DEFAULT_TEXT_MODEL = "gemini-2.0-flash"

# Singleton client — created once, reused to avoid "client has been closed" errors
_GENAI_CLIENT: genai.Client | None = None


def _client() -> genai.Client:
    """Return the module-level genai.Client singleton, creating it on first call."""
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        _GENAI_CLIENT = genai.Client(api_key=get_api_key())
    return _GENAI_CLIENT


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVITIES_DIR.mkdir(parents=True, exist_ok=True)


def _generate_id() -> str:
    registry = load_registry()
    max_num = 0
    for sid in registry["students"]:
        if sid.startswith("S") and sid[1:].isdigit():
            max_num = max(max_num, int(sid[1:]))
    return f"S{max_num + 1}"


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
    _update_excel(registry)


def _update_excel(registry: dict[str, Any]) -> None:
    try:
        import pandas as pd
        students_list = list(registry.get("students", {}).values())
        if not students_list:
            return
        df = pd.DataFrame(students_list)
        cols = ["student_id", "child_name", "age", "grade", "parent_name", "notes", "latest_homework", "created_at", "updated_at"]
        cols = [c for c in cols if c in df.columns]
        df = df[cols]
        rename_dict = {
            "student_id": "Student ID",
            "child_name": "Child Name",
            "age": "Age",
            "grade": "Class/Grade",
            "parent_name": "Parent Name",
            "notes": "Teacher Notes",
            "latest_homework": "Latest Homework",
            "created_at": "Created At",
            "updated_at": "Updated At"
        }
        df = df.rename(columns=rename_dict)
        df.to_excel(EXCEL_PATH, index=False)
    except Exception as e:
        print(f"Error updating Excel: {e}")


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
    q = query.strip()
    if not q:
        return []
    q_lower = q.lower()
    results: list[dict[str, Any]] = []
    for student in list_students():
        sid = student.get("student_id", "")
        name = student.get("child_name", "")
        if sid.upper() == q.upper() or q_lower in sid.lower():
            results.append(student)
        elif q_lower in name.lower():
            results.append(student)
    return results


def upsert_student(
    child_name: str,
    age: str = "",
    grade: str = "",
    parent_name: str = "",
    notes: str = "",
    latest_homework: str = "",
    student_id: str | None = None,
) -> dict[str, Any]:
    registry = load_registry()
    name = child_name.strip()
    if not name:
        raise ValueError("Child name is required.")

    now = _now_iso()
    
    # Case-insensitive duplicate check by child name if registering a new profile
    if not student_id:
        name_lower = name.lower()
        for sid, s in registry["students"].items():
            if s.get("child_name", "").strip().lower() == name_lower:
                student_id = sid
                break

    if student_id and student_id in registry["students"]:
        record = registry["students"][student_id]
        updates = {
            "child_name": name,
            "age": age.strip(),
            "grade": grade.strip(),
            "parent_name": parent_name.strip(),
            "notes": notes.strip(),
            "updated_at": now,
        }
        if latest_homework.strip():
            updates["latest_homework"] = latest_homework.strip()
        record.update(updates)
    else:
        student_id = student_id or _generate_id()
        record = {
            "student_id": student_id,
            "child_name": name,
            "age": age.strip(),
            "grade": grade.strip(),
            "parent_name": parent_name.strip(),
            "notes": notes.strip(),
            "latest_homework": latest_homework.strip(),
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
    text_model = os.getenv("GEMINI_TEXT_MODEL", "").strip()
    if text_model:
        return text_model

    configured_model = os.getenv("GEMINI_MODEL", "").strip()
    if configured_model and "live" not in configured_model.lower():
        return configured_model

    return DEFAULT_TEXT_MODEL


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "resource_exhausted" in message or "quota" in message or "rate-limit" in message


def _fallback_report_card(
    student: dict[str, Any], context: str, extra_parent_notes: str = ""
) -> str:
    child = student.get("child_name") or "the student"
    sid = student.get("student_id") or "unknown"
    notes = extra_parent_notes.strip()
    recent_context = context.strip() or "No learning activity has been recorded yet."

    return f"""# Report Card - {child}
**Student ID:** {sid}
**Date:** {datetime.now().strftime("%d %B %Y")}
**Class / Age:** {student.get("grade") or "-"} / {student.get("age") or "-"}

## Dear Parents
SHIKSHA could not use the AI report writer right now because the Gemini quota is exhausted. This report is created from the saved student profile and activity log.

## Overall progress
{recent_context}

## Parent notes
{notes or "No extra parent notes were added."}

## Recommendations for home
- Keep short daily speaking practice with the child.
- Review homework and celebrate small improvements.
- Save this Student ID ({sid}) for future parent reports.

## Signature
{ASSISTANT_NAME}
"""


def _service_error_message(action: str) -> str:
    return (
        f"SHIKSHA could not {action} right now because the AI service returned an error. "
        "Please try again in a moment."
    )


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

    try:
        response = _client().models.generate_content(model=_text_model(), contents=prompt)
        return (response.text or "").strip()
    except Exception as exc:
        if _is_quota_error(exc):
            return _fallback_report_card(student, context, extra_parent_notes)
        raise RuntimeError(_service_error_message("generate the report card")) from exc


def answer_parent_message(
    student_id: str,
    parent_message: str,
    chat_history: list[dict[str, str]] | None = None,
) -> str:
    student = get_student(student_id) if student_id else None
    context = build_progress_context(student_id) if student_id else "No student loaded."
    child = (student or {}).get("child_name") or "your child"
    sid = (student or {}).get("student_id") or "unknown"
    history = chat_history or []
    history_text = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in history[-8:])

    prompt = f"""You are {ASSISTANT_NAME}, speaking to a PARENT about their child.

Child: {child} | Student ID: {sid}

{context}

Recent chat:
{history_text or "(none)"}

Parent says:
{parent_message}

Reply warmly and professionally. Use only evidence from the data above.
Mention the Student ID ({sid}) so parents can save it for next time."""

    try:
        response = _client().models.generate_content(model=_text_model(), contents=prompt)
        return (response.text or "").strip()
    except Exception as exc:
        if _is_quota_error(exc):
            return (
                f"I could not prepare a live parent reply right now because the Gemini API quota is exhausted. "
                f"Please try again after the quota resets. Student ID: {sid}."
            )
        raise RuntimeError(_service_error_message("answer the parent chat")) from exc


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
        latest_homework=profile.get("latest_homework", ""),
        student_id=sid,
    )
