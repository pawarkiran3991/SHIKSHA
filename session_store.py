"""Per-browser session state (cookie-backed) for multi-user FastAPI."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

COOKIE_NAME = "shiksha_sid"

_DEFAULT_STATE: dict[str, Any] = {
    "active_student_id": "",
    "homework_board": "",
    "generated_homework": "",
    "grade_hint": "",
    "check_result": "",
    "submission_notes": "",
    "parent_chat": [],
    "report_card": "",
    "parent_report_notes": "",
    "teaching_image": "",
    "teaching_caption": "",
}

_STORE: dict[str, dict[str, Any]] = {}


def new_session_id() -> str:
    return secrets.token_urlsafe(24)


def get_state(session_id: str | None) -> dict[str, Any]:
    if not session_id or session_id not in _STORE:
        sid = session_id or new_session_id()
        _STORE[sid] = {**_DEFAULT_STATE}
        return _STORE[sid]
    return _STORE[sid]


def ensure_session(session_id: str | None) -> tuple[str, dict[str, Any]]:
    if not session_id or session_id not in _STORE:
        sid = new_session_id()
        _STORE[sid] = {**_DEFAULT_STATE}
        return sid, _STORE[sid]
    return session_id, _STORE[session_id]
