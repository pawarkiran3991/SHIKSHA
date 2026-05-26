"""SHIKSHA — FastAPI + Uvicorn Teaching Assistant"""

from __future__ import annotations

import time as _time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
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
    add_parent_task,
    answer_parent_message,
    build_student_session_context,
    clear_parent_messages,
    generate_report_card,
    get_progress_chart_data,
    get_student,
    list_parent_tasks,
    list_students,
    load_parent_messages,
    log_homework_assigned,
    log_homework_check,
    log_live_session,
    search_students,
    set_topic_progress,
    update_parent_task_status,
    upsert_student,
)
from session_store import COOKIE_NAME, ensure_session
from syllabus import GRADE_OPTIONS, first_pending_topic_id, get_topic_by_id, load_syllabus

load_env_file()

BASE_DIR = Path(__file__).resolve().parent
SYLLABUS_MEDIA = BASE_DIR / "data" / "syllabus"
STATIC_DIR = BASE_DIR / "static"

_students_cache: list[dict] = []
_students_cache_ts: float = 0.0
_STUDENTS_CACHE_TTL = 10.0

_LIVE_ASSISTANT: Any = None


def _cached_students() -> list[dict]:
    global _students_cache, _students_cache_ts
    if _time.monotonic() - _students_cache_ts > _STUDENTS_CACHE_TTL:
        _students_cache = list_students()
        _students_cache_ts = _time.monotonic()
    return _students_cache


def _invalidate_cache() -> None:
    global _students_cache_ts
    _students_cache_ts = 0.0


def _browser_session(request: Request) -> tuple[str, dict[str, Any]]:
    cookie = request.cookies.get(COOKIE_NAME)
    return ensure_session(cookie)


def _with_cookie(response: Response, request: Request, session_id: str) -> Response:
    if request.cookies.get(COOKIE_NAME) != session_id:
        response.set_cookie(
            key=COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
    return response


def _json(request: Request, data: dict, session_id: str) -> JSONResponse:
    return _with_cookie(JSONResponse(data), request, session_id)


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


def _active_student(st: dict[str, Any]) -> dict[str, Any] | None:
    sid = st.get("active_student_id", "")
    return get_student(sid) if sid else None


def _homework_context(st: dict[str, Any]) -> str:
    parts = []
    if (st.get("homework_board") or "").strip():
        parts.append(st["homework_board"].strip())
    if (st.get("generated_homework") or "").strip():
        parts.append("Latest generated homework sheet:\n")
        parts.append(st["generated_homework"].strip())
    return "\n\n".join(parts)


def _student_context(st: dict[str, Any]) -> str:
    student = _active_student(st)
    if not student:
        return ""
    return build_student_session_context(student)


def _apply_lesson_context(st: dict[str, Any]) -> None:
    if _LIVE_ASSISTANT:
        _LIVE_ASSISTANT.set_lesson_context(_homework_context(st), _student_context(st))


def _teaching_slide_for_student(student: dict[str, Any] | None) -> dict[str, str]:
    if not student:
        return {"url": "", "caption": "", "topic_id": ""}
    grade = student.get("grade") or ""
    if not grade:
        return {"url": "", "caption": "", "topic_id": ""}
    from progress import get_syllabus_progress_map

    progress = get_syllabus_progress_map(student["student_id"])
    topic_id = student.get("current_topic_id") or first_pending_topic_id(grade, progress)
    if not topic_id:
        return {"url": "", "caption": "", "topic_id": ""}
    topic = get_topic_by_id(grade, topic_id)
    if not topic:
        return {"url": "", "caption": "", "topic_id": topic_id}
    pages = topic.get("pages") or []
    if not pages:
        return {
            "url": "",
            "caption": topic.get("title", ""),
            "topic_id": topic_id,
        }
    page = pages[0]
    file_path = (page.get("file") or "").strip()
    url = f"/syllabus-media/{file_path}" if file_path else ""
    return {
        "url": url,
        "caption": page.get("caption") or topic.get("title", ""),
        "topic_id": topic_id,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _LIVE_ASSISTANT
    from main import LiveVoiceAssistant

    _LIVE_ASSISTANT = LiveVoiceAssistant()
    yield
    if _LIVE_ASSISTANT and _LIVE_ASSISTANT.is_running():
        _LIVE_ASSISTANT.stop()


app = FastAPI(title="SHIKSHA Teaching Assistant", lifespan=lifespan)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if SYLLABUS_MEDIA.exists():
    app.mount("/syllabus-media", StaticFiles(directory=str(SYLLABUS_MEDIA)), name="syllabus-media")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/student/lookup")
async def student_lookup(request: Request, q: str = ""):
    if not q.strip():
        return JSONResponse({"found": False})
    s = get_student(q.strip().upper())
    if not s:
        matches = search_students(q.strip())
        if matches:
            s = matches[0]
    if s:
        return JSONResponse({"found": True, "student": s})
    return JSONResponse({"found": False})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    session_id, st = _browser_session(request)
    snap = _snap()
    student = _active_student(st)
    slide = _teaching_slide_for_student(student)
    chart = get_progress_chart_data(student["student_id"]) if student else {}
    parent_chat = (
        load_parent_messages(student["student_id"]) if student else st.get("parent_chat", [])
    )
    if student:
        st["parent_chat"] = parent_chat

    resp = templates.TemplateResponse(
        request,
        "index.html",
        {
            "assistant_name": ASSISTANT_NAME,
            "status": snap["status"],
            "messages": snap["messages"],
            "interruptions": snap["interruptions"],
            "model": snap["model"],
            "error": snap["error"],
            "student": student,
            "homework_board": st.get("homework_board", ""),
            "generated_homework": st.get("generated_homework", ""),
            "grade_hint": st.get("grade_hint", ""),
            "check_result": st.get("check_result", ""),
            "submission_notes": st.get("submission_notes", ""),
            "parent_chat": parent_chat,
            "report_card": st.get("report_card", ""),
            "parent_report_notes": st.get("parent_report_notes", ""),
            "today": date.today().isoformat(),
            "students_list": _cached_students()[:20],
            "grade_options": GRADE_OPTIONS,
            "teaching_image": slide.get("url", ""),
            "teaching_caption": slide.get("caption", ""),
            "progress_chart": chart,
        },
    )
    return _with_cookie(resp, request, session_id)


@app.post("/session/start")
async def session_start(
    request: Request,
    child_name: str = Form(...),
    age: str = Form(""),
    grade: str = Form(""),
    parent_name: str = Form(""),
    student_id: str = Form(""),
):
    session_id, st = _browser_session(request)
    if not child_name.strip():
        return _json(request, {"ok": False, "error": "Child name is required."}, session_id)
    try:
        lookup = student_id.strip().upper() or None
        existing = get_student(lookup) if lookup else None
        sid = existing["student_id"] if existing else None
        student = upsert_student(
            child_name=child_name,
            age=age,
            grade=grade,
            parent_name=parent_name,
            student_id=sid,
        )
        st["active_student_id"] = student["student_id"]
        st["homework_board"] = student.get("latest_homework", "") or st.get("homework_board", "")
        st["generated_homework"] = student.get("latest_homework", "") or st.get(
            "generated_homework", ""
        )
        slide = _teaching_slide_for_student(student)
        st["teaching_image"] = slide.get("url", "")
        st["teaching_caption"] = slide.get("caption", "")
        _apply_lesson_context(st)
        _invalidate_cache()
        if _LIVE_ASSISTANT and not _LIVE_ASSISTANT.is_running():
            _LIVE_ASSISTANT.start()
        return _json(
            request,
            {
                "ok": True,
                "student_id": student["student_id"],
                "name": student["child_name"],
                "teaching_image": slide.get("url", ""),
                "teaching_caption": slide.get("caption", ""),
            },
            session_id,
        )
    except Exception as exc:
        return _json(request, {"ok": False, "error": str(exc)}, session_id)


@app.post("/session/stop")
async def session_stop(request: Request):
    session_id, st = _browser_session(request)
    snap = _snap()
    if _LIVE_ASSISTANT and _LIVE_ASSISTANT.is_running():
        _LIVE_ASSISTANT.stop()
        sid = st.get("active_student_id", "")
        if sid:
            log_live_session(sid, snap["messages"], snap["interruptions"])
    return _json(request, {"ok": True}, session_id)


@app.get("/session/status")
async def session_status():
    return JSONResponse(_snap())


@app.get("/teaching/current")
async def teaching_current(request: Request):
    session_id, st = _browser_session(request)
    student = _active_student(st)
    slide = _teaching_slide_for_student(student)
    st["teaching_image"] = slide.get("url", "")
    st["teaching_caption"] = slide.get("caption", "")
    return _json(request, {"ok": True, **slide}, session_id)


@app.post("/homework/save-board")
async def homework_save_board(
    request: Request, board: str = Form(""), grade_hint: str = Form("")
):
    session_id, st = _browser_session(request)
    today = date.today().isoformat()
    board_with_date = board
    if board.strip() and today not in board:
        board_with_date = f"[Date: {today}]\n{board.strip()}"
    st["homework_board"] = board_with_date
    st["grade_hint"] = grade_hint
    _apply_lesson_context(st)
    return _json(request, {"ok": True, "board": board_with_date}, session_id)


@app.post("/homework/generate")
async def homework_generate(request: Request):
    session_id, st = _browser_session(request)
    board = (st.get("homework_board") or "").strip()
    if not board:
        return _json(request, {"ok": False, "error": "Add details on the board first."}, session_id)
    try:
        result = generate_homework_sheet(board, st.get("grade_hint", ""))
        st["generated_homework"] = result
        sid = st.get("active_student_id", "")
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
        _apply_lesson_context(st)
        return _json(request, {"ok": True, "homework": result}, session_id)
    except Exception as exc:
        return _json(request, {"ok": False, "error": str(exc)}, session_id)


@app.post("/homework/update-generated")
async def homework_update_generated(request: Request, content: str = Form("")):
    session_id, st = _browser_session(request)
    st["generated_homework"] = content
    _apply_lesson_context(st)
    return _json(request, {"ok": True}, session_id)


@app.post("/homework/clear")
async def homework_clear(request: Request):
    session_id, st = _browser_session(request)
    st["homework_board"] = ""
    st["generated_homework"] = ""
    _apply_lesson_context(st)
    return _json(request, {"ok": True}, session_id)


@app.post("/homework/add-topic")
async def homework_add_topic(
    request: Request, topic: str = Form(""), grade_hint: str = Form("")
):
    session_id, st = _browser_session(request)
    if not topic.strip():
        return _json(request, {"ok": False, "error": "Enter a topic first."}, session_id)
    grade_str = grade_hint or st.get("grade_hint") or ""
    today = date.today().isoformat()
    line = f"- {topic.strip()}{(' (Grade: ' + grade_str + ')') if grade_str else ''}"
    board = st.get("homework_board", "")
    if not board.strip():
        st["homework_board"] = f"[Date: {today}]\n{line}"
    else:
        if today not in board:
            st["homework_board"] = f"[Date: {today}]\n{board.strip()}\n{line}"
        else:
            st["homework_board"] = board.strip() + "\n" + line
    _apply_lesson_context(st)
    return _json(request, {"ok": True, "board": st["homework_board"]}, session_id)


@app.post("/homework/check")
async def homework_check(
    request: Request,
    submission_notes: str = Form(""),
    file: UploadFile = File(None),
):
    session_id, st = _browser_session(request)
    assignment = st.get("generated_homework") or st.get("homework_board") or ""
    submission_text = submission_notes
    image_parts = []
    if file and file.filename:
        raw = await file.read()
        extracted, image_parts = extract_upload_text_bytes(
            raw, file.filename, file.content_type or ""
        )
        submission_text = f"{submission_text}\n\n{extracted}".strip()
    if not assignment.strip() and not submission_text and not image_parts:
        return _json(
            request,
            {"ok": False, "error": "Add expected homework and submit work to check."},
            session_id,
        )
    try:
        result = check_homework(
            assignment_context=assignment,
            submission_text=submission_text,
            image_parts=image_parts or None,
        )
        st["check_result"] = result
        sid = st.get("active_student_id", "")
        if sid:
            log_homework_check(sid, assignment[:300], result)
        return _json(request, {"ok": True, "result": result}, session_id)
    except Exception as exc:
        return _json(request, {"ok": False, "error": str(exc)}, session_id)


@app.get("/homework/download-pdf")
async def homework_download_pdf(request: Request):
    _, st = _browser_session(request)
    body = st.get("generated_homework", "")
    if not body:
        return JSONResponse({"error": "No homework generated yet."}, status_code=400)
    title = f"SHIKSHA Homework — {date.today().isoformat()}"
    return Response(
        content=create_pdf_bytes(title, body),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=shiksha_homework.pdf"},
    )


@app.get("/homework/download-docx")
async def homework_download_docx(request: Request):
    _, st = _browser_session(request)
    body = st.get("generated_homework", "")
    if not body:
        return JSONResponse({"error": "No homework generated yet."}, status_code=400)
    title = f"SHIKSHA Homework — {date.today().isoformat()}"
    return Response(
        content=create_docx_bytes(title, body),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=shiksha_homework.docx"},
    )


@app.post("/parent/search")
async def parent_search(request: Request, query: str = Form("")):
    session_id, _ = _browser_session(request)
    if not query.strip():
        return _json(request, {"ok": False, "error": "Enter a name or Student ID."}, session_id)
    matches = search_students(query)
    if not matches:
        return _json(request, {"ok": False, "error": "No student found."}, session_id)
    return _json(request, {"ok": True, "students": matches}, session_id)


@app.post("/parent/load-student")
async def parent_load_student(request: Request, student_id: str = Form(...)):
    session_id, st = _browser_session(request)
    student = get_student(student_id)
    if not student:
        return _json(request, {"ok": False, "error": "Student not found."}, session_id)
    st["active_student_id"] = student["student_id"]
    st["generated_homework"] = student.get("latest_homework", "")
    st["homework_board"] = student.get("latest_homework", "")
    st["parent_chat"] = load_parent_messages(student["student_id"])
    st["report_card"] = ""
    slide = _teaching_slide_for_student(student)
    st["teaching_image"] = slide.get("url", "")
    st["teaching_caption"] = slide.get("caption", "")
    _apply_lesson_context(st)
    chart = get_progress_chart_data(student["student_id"])
    tasks = list_parent_tasks(student["student_id"])
    return _json(
        request,
        {
            "ok": True,
            "student": student,
            "parent_chat": st["parent_chat"],
            "chart": chart,
            "tasks": tasks,
            "teaching_image": slide.get("url", ""),
            "teaching_caption": slide.get("caption", ""),
        },
        session_id,
    )


@app.post("/parent/chat")
async def parent_chat(request: Request, message: str = Form(...)):
    session_id, st = _browser_session(request)
    sid = st.get("active_student_id", "")
    student = get_student(sid) if sid else None
    if not student:
        return _json(
            request,
            {"ok": False, "error": "Pehle student load karo (Parent Corner me search karo)."},
            session_id,
        )
    if not message.strip():
        return _json(request, {"ok": False, "error": "Message khali hai."}, session_id)
    history = st.get("parent_chat") or load_parent_messages(sid)
    try:
        reply = answer_parent_message(sid, message, history)
        if not reply:
            raise ValueError("Empty response from AI.")
        st["parent_chat"] = load_parent_messages(sid)
        return _json(request, {"ok": True, "reply": reply, "parent_chat": st["parent_chat"]}, session_id)
    except Exception as exc:
        return _json(request, {"ok": False, "error": f"Error: {exc}"}, session_id)


@app.post("/parent/clear-chat")
async def parent_clear_chat(request: Request):
    session_id, st = _browser_session(request)
    sid = st.get("active_student_id", "")
    if sid:
        clear_parent_messages(sid)
    st["parent_chat"] = []
    return _json(request, {"ok": True}, session_id)


@app.post("/parent/report")
async def parent_report(request: Request, extra_notes: str = Form("")):
    session_id, st = _browser_session(request)
    sid = st.get("active_student_id", "")
    if not sid:
        return _json(request, {"ok": False, "error": "Load a student first."}, session_id)
    try:
        result = generate_report_card(sid, extra_notes)
        st["report_card"] = result
        return _json(request, {"ok": True, "report": result}, session_id)
    except Exception as exc:
        return _json(request, {"ok": False, "error": str(exc)}, session_id)


@app.get("/parent/download-report-pdf")
async def parent_download_report_pdf(request: Request):
    _, st = _browser_session(request)
    student = _active_student(st)
    report = st.get("report_card", "")
    if not report:
        return JSONResponse({"error": "Generate a report first."}, status_code=400)
    child = (student or {}).get("child_name") or "student"
    title = f"SHIKSHA Report — {child} — {date.today().isoformat()}"
    fname = f"shiksha_report_{child.replace(' ', '_')}.pdf"
    return Response(
        content=create_pdf_bytes(title, report),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.get("/parent/chart")
async def parent_chart(request: Request):
    session_id, st = _browser_session(request)
    sid = st.get("active_student_id", "")
    if not sid:
        return _json(request, {"ok": False, "error": "No student loaded."}, session_id)
    return _json(request, {"ok": True, "chart": get_progress_chart_data(sid)}, session_id)


@app.get("/parent/tasks")
async def parent_tasks_list(request: Request):
    session_id, st = _browser_session(request)
    sid = st.get("active_student_id", "")
    if not sid:
        return _json(request, {"ok": True, "tasks": []}, session_id)
    return _json(request, {"ok": True, "tasks": list_parent_tasks(sid)}, session_id)


@app.post("/parent/tasks/add")
async def parent_tasks_add(
    request: Request,
    task_text: str = Form(...),
    subject: str = Form(""),
):
    session_id, st = _browser_session(request)
    sid = st.get("active_student_id", "")
    if not sid:
        return _json(request, {"ok": False, "error": "Load a student first."}, session_id)
    try:
        task = add_parent_task(sid, task_text, subject)
        return _json(request, {"ok": True, "task": task}, session_id)
    except Exception as exc:
        return _json(request, {"ok": False, "error": str(exc)}, session_id)


@app.post("/parent/tasks/update")
async def parent_tasks_update(
    request: Request,
    task_id: int = Form(...),
    status: str = Form("done"),
):
    session_id, st = _browser_session(request)
    update_parent_task_status(task_id, status)
    sid = st.get("active_student_id", "")
    tasks = list_parent_tasks(sid) if sid else []
    return _json(request, {"ok": True, "tasks": tasks}, session_id)


@app.post("/syllabus/topic-progress")
async def syllabus_topic_progress(
    request: Request,
    topic_id: str = Form(...),
    status: str = Form("in_progress"),
):
    session_id, st = _browser_session(request)
    sid = st.get("active_student_id", "")
    if not sid:
        return _json(request, {"ok": False, "error": "No student loaded."}, session_id)
    set_topic_progress(sid, topic_id, status)
    student = get_student(sid)
    slide = _teaching_slide_for_student(student)
    st["teaching_image"] = slide.get("url", "")
    st["teaching_caption"] = slide.get("caption", "")
    _apply_lesson_context(st)
    return _json(
        request,
        {"ok": True, "chart": get_progress_chart_data(sid), **slide},
        session_id,
    )


@app.get("/syllabus/topics")
async def syllabus_topics(request: Request):
    session_id, st = _browser_session(request)
    student = _active_student(st)
    if not student:
        return _json(request, {"ok": False, "topics": []}, session_id)
    from progress import get_syllabus_progress_map

    grade = student.get("grade") or ""
    progress = get_syllabus_progress_map(student["student_id"])
    topics = []
    for t in load_syllabus(grade).get("topics", []):
        tid = t.get("id", "")
        topics.append(
            {
                "id": tid,
                "title": t.get("title", tid),
                "subject": t.get("subject", ""),
                "status": progress.get(tid, "pending"),
            }
        )
    return _json(request, {"ok": True, "topics": topics, "grade": grade}, session_id)


@app.get("/export-json")
async def export_json_snapshot():
    from progress import JSON_SNAPSHOT_PATH

    if not JSON_SNAPSHOT_PATH.exists():
        return JSONResponse({"error": "No snapshot yet."}, status_code=404)
    return Response(
        content=JSON_SNAPSHOT_PATH.read_bytes(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=shiksha_students.json"},
    )
