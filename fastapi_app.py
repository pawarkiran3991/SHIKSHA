"""SHIKSHA — FastAPI + Uvicorn Teaching Assistant"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from homework import (
    check_homework,
    create_docx_bytes,
    create_pdf_bytes,
    extract_upload_text_bytes,
    generate_homework_sheet,
)
from main import ASSISTANT_NAME, load_env_file
from progress import (
    answer_parent_message,
    build_student_session_context,
    generate_report_card,
    get_student,
    list_students,
    log_homework_assigned,
    log_homework_check,
    log_live_session,
    search_students,
    upsert_student,
)

# ── Simple in-memory cache for student list (invalidated on writes) ───────────
import time as _time

_students_cache: list[dict] = []
_students_cache_ts: float = 0.0
_STUDENTS_CACHE_TTL = 10.0   # seconds


def _cached_students() -> list[dict]:
    global _students_cache, _students_cache_ts
    if _time.monotonic() - _students_cache_ts > _STUDENTS_CACHE_TTL:
        _students_cache = list_students()
        _students_cache_ts = _time.monotonic()
    return _students_cache


def _invalidate_cache() -> None:
    global _students_cache_ts
    _students_cache_ts = 0.0

load_env_file()

BASE_DIR = Path(__file__).resolve().parent

# In-memory session store (single-user for now; extend to dict[session_id] for multi-user)
_SESSION: dict[str, Any] = {
    "active_student_id": "",
    "homework_board": "",
    "generated_homework": "",
    "grade_hint": "",
    "check_result": "",
    "submission_notes": "",
    "parent_chat": [],
    "report_card": "",
    "parent_report_notes": "",
    "assistant_status": "idle",
    "assistant_messages": [],
    "assistant_interruptions": 0,
    "assistant_model": "",
    "assistant_error": "",
}

_LIVE_ASSISTANT: Any = None  # LiveVoiceAssistant instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _LIVE_ASSISTANT
    from main import LiveVoiceAssistant
    _LIVE_ASSISTANT = LiveVoiceAssistant()
    yield
    if _LIVE_ASSISTANT and _LIVE_ASSISTANT.is_running():
        _LIVE_ASSISTANT.stop()


app = FastAPI(title="SHIKSHA Teaching Assistant", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _snap() -> dict[str, Any]:
    if _LIVE_ASSISTANT:
        return _LIVE_ASSISTANT.snapshot()
    return {
        "status": "idle",
        "messages": [],
        "interruptions": 0,
        "model": "",
        "error": "",
        "assistant_name": ASSISTANT_NAME,
    }


def _active_student() -> dict[str, Any] | None:
    sid = _SESSION["active_student_id"]
    return get_student(sid) if sid else None


def _homework_context() -> str:
    parts = []
    if _SESSION["homework_board"].strip():
        parts.append(_SESSION["homework_board"].strip())
    if _SESSION["generated_homework"].strip():
        parts.append("Latest generated homework sheet:\n")
        parts.append(_SESSION["generated_homework"].strip())
    return "\n\n".join(parts)


def _student_context() -> str:
    student = _active_student()
    if not student:
        return ""
    return build_student_session_context(student)


def _apply_lesson_context() -> None:
    if _LIVE_ASSISTANT:
        _LIVE_ASSISTANT.set_lesson_context(_homework_context(), _student_context())


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    snap = _snap()
    student = _active_student()
    # Starlette ≥0.29 / 1.x: request is first positional arg, NOT in context dict
    return templates.TemplateResponse(request, "index.html", {
        "assistant_name": ASSISTANT_NAME,
        "status": snap["status"],
        "messages": snap["messages"],
        "interruptions": snap["interruptions"],
        "model": snap["model"],
        "error": snap["error"],
        "student": student,
        "homework_board": _SESSION["homework_board"],
        "generated_homework": _SESSION["generated_homework"],
        "grade_hint": _SESSION["grade_hint"],
        "check_result": _SESSION["check_result"],
        "submission_notes": _SESSION["submission_notes"],
        "parent_chat": _SESSION["parent_chat"],
        "report_card": _SESSION["report_card"],
        "parent_report_notes": _SESSION["parent_report_notes"],
        "today": date.today().isoformat(),
        "students_list": _cached_students()[:20],
    })


# ── Live Session ────────────────────────────────────────────────────────────────

@app.post("/session/start")
async def session_start(
    child_name: str = Form(...),
    age: str = Form(""),
    grade: str = Form(""),
    parent_name: str = Form(""),
    student_id: str = Form(""),
):
    if not child_name.strip():
        return JSONResponse({"ok": False, "error": "Child name is required."})
    try:
        lookup = student_id.strip().upper() or None
        existing = get_student(lookup) if lookup else None
        sid = existing["student_id"] if existing else (lookup if lookup and get_student(lookup) else None)
        student = upsert_student(
            child_name=child_name,
            age=age,
            grade=grade,
            parent_name=parent_name,
            student_id=sid,
        )
        _SESSION["active_student_id"] = student["student_id"]
        _SESSION["homework_board"] = student.get("latest_homework", "") or _SESSION["homework_board"]
        _SESSION["generated_homework"] = student.get("latest_homework", "") or _SESSION["generated_homework"]
        _apply_lesson_context()
        _invalidate_cache()
        if _LIVE_ASSISTANT and not _LIVE_ASSISTANT.is_running():
            _LIVE_ASSISTANT.start()
        return JSONResponse({"ok": True, "student_id": student["student_id"], "name": student["child_name"]})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


@app.post("/session/stop")
async def session_stop():
    snap = _snap()
    if _LIVE_ASSISTANT and _LIVE_ASSISTANT.is_running():
        _LIVE_ASSISTANT.stop()
        sid = _SESSION["active_student_id"]
        if sid:
            log_live_session(sid, snap["messages"], snap["interruptions"])
    return JSONResponse({"ok": True})


@app.get("/session/status")
async def session_status():
    snap = _snap()
    return JSONResponse(snap)


# ── Homework ────────────────────────────────────────────────────────────────────

@app.post("/homework/save-board")
async def homework_save_board(board: str = Form(""), grade_hint: str = Form("")):
    _SESSION["homework_board"] = board
    _SESSION["grade_hint"] = grade_hint
    _apply_lesson_context()
    return JSONResponse({"ok": True})


@app.post("/homework/generate")
async def homework_generate():
    board = _SESSION["homework_board"].strip()
    if not board:
        return JSONResponse({"ok": False, "error": "Add details on the board first."})
    try:
        result = generate_homework_sheet(board, _SESSION["grade_hint"])
        _SESSION["generated_homework"] = result
        sid = _SESSION["active_student_id"]
        if sid:
            log_homework_assigned(sid, board, result)
            student = get_student(sid)
            if student:
                upsert_student(
                    child_name=student["child_name"],
                    age=student.get("age", ""),
                    grade=student.get("grade", ""),
                    parent_name=student.get("parent_name", ""),
                    notes=student.get("notes", ""),
                    latest_homework=result,
                    student_id=sid,
                )
        _apply_lesson_context()
        return JSONResponse({"ok": True, "homework": result})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


@app.post("/homework/update-generated")
async def homework_update_generated(content: str = Form("")):
    _SESSION["generated_homework"] = content
    _apply_lesson_context()
    return JSONResponse({"ok": True})


@app.post("/homework/clear")
async def homework_clear():
    _SESSION["homework_board"] = ""
    _SESSION["generated_homework"] = ""
    _apply_lesson_context()
    return JSONResponse({"ok": True})


@app.post("/homework/add-topic")
async def homework_add_topic(topic: str = Form(""), grade_hint: str = Form("")):
    if not topic.strip():
        return JSONResponse({"ok": False, "error": "Enter a topic first."})
    grade_str = grade_hint or _SESSION.get("grade_hint") or ""
    line = f"- {topic.strip()}{(' (Grade: ' + grade_str + ')') if grade_str else ''}"
    board = _SESSION["homework_board"]
    _SESSION["homework_board"] = (board + "\n" + line).strip() if board.strip() else line
    _apply_lesson_context()
    return JSONResponse({"ok": True, "board": _SESSION["homework_board"]})


@app.post("/homework/check")
async def homework_check(
    submission_notes: str = Form(""),
    file: UploadFile = File(None),
):
    assignment = _SESSION["generated_homework"] or _SESSION["homework_board"]
    submission_text = submission_notes
    image_parts = []
    if file and file.filename:
        raw = await file.read()
        extracted, image_parts = extract_upload_text_bytes(raw, file.filename, file.content_type or "")
        submission_text = f"{submission_text}\n\n{extracted}".strip()
    if not assignment.strip() and not submission_text and not image_parts:
        return JSONResponse({"ok": False, "error": "Add expected homework and submit work to check."})
    try:
        result = check_homework(
            assignment_context=assignment,
            submission_text=submission_text,
            image_parts=image_parts or None,
        )
        _SESSION["check_result"] = result
        sid = _SESSION["active_student_id"]
        if sid:
            log_homework_check(sid, assignment[:300], result)
        return JSONResponse({"ok": True, "result": result})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


@app.get("/homework/download-pdf")
async def homework_download_pdf():
    title = f"SHIKSHA Homework — {date.today().isoformat()}"
    body = _SESSION["generated_homework"]
    if not body:
        return JSONResponse({"error": "No homework generated yet."}, status_code=400)
    pdf_bytes = create_pdf_bytes(title, body)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=shiksha_homework.pdf"},
    )


@app.get("/homework/download-docx")
async def homework_download_docx():
    title = f"SHIKSHA Homework — {date.today().isoformat()}"
    body = _SESSION["generated_homework"]
    if not body:
        return JSONResponse({"error": "No homework generated yet."}, status_code=400)
    docx_bytes = create_docx_bytes(title, body)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=shiksha_homework.docx"},
    )


# ── Parent Corner ───────────────────────────────────────────────────────────────

@app.post("/parent/search")
async def parent_search(query: str = Form("")):
    if not query.strip():
        return JSONResponse({"ok": False, "error": "Enter a name or Student ID."})
    matches = search_students(query)
    if not matches:
        return JSONResponse({"ok": False, "error": "No student found."})
    return JSONResponse({"ok": True, "students": matches})


@app.post("/parent/load-student")
async def parent_load_student(student_id: str = Form(...)):
    student = get_student(student_id)
    if not student:
        return JSONResponse({"ok": False, "error": "Student not found."})
    _SESSION["active_student_id"] = student["student_id"]
    _SESSION["generated_homework"] = student.get("latest_homework", "")
    _SESSION["homework_board"] = student.get("latest_homework", "")
    _SESSION["parent_chat"] = []
    _SESSION["report_card"] = ""
    _apply_lesson_context()
    return JSONResponse({"ok": True, "student": student})


@app.post("/parent/chat")
async def parent_chat(message: str = Form(...)):
    sid = _SESSION["active_student_id"]
    student = get_student(sid) if sid else None
    if not student:
        return JSONResponse({"ok": False, "error": "Load a student first."})
    _SESSION["parent_chat"].append({"role": "parent", "text": message})
    try:
        reply = answer_parent_message(sid, message, _SESSION["parent_chat"][:-1])
        _SESSION["parent_chat"].append({"role": "assistant", "text": reply})
        return JSONResponse({"ok": True, "reply": reply})
    except Exception as exc:
        err = f"Sorry, I could not respond: {exc}"
        _SESSION["parent_chat"].append({"role": "assistant", "text": err})
        return JSONResponse({"ok": False, "error": err})


@app.post("/parent/clear-chat")
async def parent_clear_chat():
    _SESSION["parent_chat"] = []
    return JSONResponse({"ok": True})


@app.post("/parent/report")
async def parent_report(extra_notes: str = Form("")):
    sid = _SESSION["active_student_id"]
    if not sid:
        return JSONResponse({"ok": False, "error": "Load a student first."})
    try:
        result = generate_report_card(sid, extra_notes)
        _SESSION["report_card"] = result
        return JSONResponse({"ok": True, "report": result})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


@app.get("/parent/download-report-pdf")
async def parent_download_report_pdf():
    student = _active_student()
    report = _SESSION["report_card"]
    if not report:
        return JSONResponse({"error": "Generate a report first."}, status_code=400)
    child = (student or {}).get("child_name") or "student"
    title = f"SHIKSHA Report — {child} — {date.today().isoformat()}"
    pdf_bytes = create_pdf_bytes(title, report)
    fname = f"shiksha_report_{child.replace(' ', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.get("/export-json")
async def export_json_snapshot():
    """Download the latest students snapshot as JSON."""
    from progress import JSON_SNAPSHOT_PATH
    if not JSON_SNAPSHOT_PATH.exists():
        return JSONResponse({"error": "No snapshot yet."}, status_code=404)
    return Response(
        content=JSON_SNAPSHOT_PATH.read_bytes(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=shiksha_students.json"},
    )
