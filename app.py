import time
from datetime import date

import streamlit as st

from homework import (
    check_homework,
    create_docx_bytes,
    create_pdf_bytes,
    extract_upload_text,
    generate_homework_sheet,
)
from main import ASSISTANT_NAME, LiveVoiceAssistant
from progress import (
    answer_parent_message,
    build_student_session_context,
    generate_report_card,
    get_student,
    load_live_chat,
    load_parent_chat,
    load_student_homework,
    log_homework_assigned,
    log_homework_check,
    log_live_session,
    save_live_chat,
    save_parent_chat,
    save_student_homework,
    search_students_by_mode,
    student_summary_for_display,
    sync_voice_homework,
    upsert_student,
)

SEARCH_BY_OPTIONS = ["Student ID", "Name"]

# --- Page Config ---
st.set_page_config(
    page_title="SHIKSHA — Teaching Assistant",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Custom CSS ---
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600&display=swap');

html, body, [class*="css"] {
    font-family: 'Outfit', sans-serif;
}

.main-title {
    background: linear-gradient(135deg, #38b2ac 0%, #4299e1 50%, #9f7aea 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 2.8rem;
    font-weight: 600;
    text-align: center;
    margin-bottom: 0.1rem;
    padding-top: 0.5rem;
}

.sub-title {
    text-align: center;
    color: #a0aec0;
    font-size: 1.05rem;
    margin-bottom: 1.5rem;
    font-weight: 300;
}

.badge-teach {
    display: inline-block;
    background: rgba(56, 178, 172, 0.15);
    color: #4fd1c5;
    border: 1px solid rgba(56, 178, 172, 0.35);
    border-radius: 999px;
    padding: 4px 14px;
    font-size: 0.85rem;
    margin: 0 4px;
}

.status-box {
    background: rgba(30, 41, 59, 0.4);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
}

.status-dot {
    height: 12px;
    width: 12px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 12px;
}

.status-idle { background-color: #718096; }
.status-starting { background-color: #ecc94b; animation: pulse-yellow 1.5s infinite; }
.status-running { background-color: #48bb78; animation: pulse-green 1.5s infinite; }
.status-stopped { background-color: #ed8936; }
.status-error { background-color: #fc8181; }

@keyframes pulse-green {
    0% { box-shadow: 0 0 0 0 rgba(72, 187, 120, 0.7); }
    70% { box-shadow: 0 0 0 10px rgba(72, 187, 120, 0); }
    100% { box-shadow: 0 0 0 0 rgba(72, 187, 120, 0); }
}

@keyframes pulse-yellow {
    0% { box-shadow: 0 0 0 0 rgba(236, 201, 75, 0.7); }
    70% { box-shadow: 0 0 0 10px rgba(236, 201, 75, 0); }
    100% { box-shadow: 0 0 0 0 rgba(236, 201, 75, 0); }
}

.homework-board {
    background: rgba(26, 32, 44, 0.5);
    border: 1px solid rgba(99, 179, 237, 0.2);
    border-radius: 12px;
    padding: 1rem 1.25rem;
    min-height: 80px;
}

.stButton button { border-radius: 10px; font-weight: 500; }
</style>
""",
    unsafe_allow_html=True,
)


def init_session_state() -> None:
    defaults = {
        "assistant": None,
        "homework_board": "",
        "voice_homework": "",
        "generated_homework": "",
        "grade_hint": "",
        "check_result": "",
        "submission_notes": "",
        "active_student_id": "",
        "child_name": "",
        "child_age": "",
        "child_grade": "",
        "parent_name": "",
        "child_notes": "",
        "parent_chat": [],
        "report_card": "",
        "parent_report_notes": "",
        "parent_search_query": "",
        "session_logged": False,
        "show_session_dialog": False,
        "dlg_name": "",
        "dlg_age": "",
        "dlg_grade": "",
        "dlg_parent": "",
        "dlg_student_id": "",
        "dlg_search_mode": "Student ID",
        "dlg_search_query": "",
        "parent_search_mode": "Student ID",
        "dlg_search_results": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state.assistant is None:
        st.session_state.assistant = LiveVoiceAssistant()


def active_student() -> dict | None:
    sid = st.session_state.active_student_id
    return get_student(sid) if sid else None


def load_homework_into_session(student_id: str) -> None:
    data = load_student_homework(student_id)
    st.session_state.homework_board = data.get("board", "")
    st.session_state.voice_homework = data.get("from_voice", "")
    st.session_state.generated_homework = data.get("generated", "")


def persist_homework_session() -> None:
    sid = st.session_state.active_student_id
    if not sid:
        return
    save_student_homework(
        sid,
        board=st.session_state.homework_board,
        generated=st.session_state.generated_homework,
        from_voice=st.session_state.voice_homework,
    )


def sync_homework_from_live_lesson() -> None:
    """Copy homework SHIKSHA gave in voice into session + disk for homework tab."""
    sid = st.session_state.active_student_id
    if not sid:
        return
    messages = assistant.snapshot().get("messages", [])
    if not messages:
        return
    voice_text = sync_voice_homework(sid, messages)
    if voice_text:
        st.session_state.voice_homework = voice_text


def sync_ui_from_student(student: dict, load_parent_history: bool = False) -> None:
    st.session_state.active_student_id = student["student_id"]
    st.session_state.child_name = student.get("child_name", "")
    st.session_state.child_age = student.get("age", "")
    st.session_state.child_grade = student.get("grade", "")
    st.session_state.parent_name = student.get("parent_name", "")
    st.session_state.child_notes = student.get("notes", "")
    if student.get("grade"):
        st.session_state.grade_hint = student.get("grade", "")
    load_homework_into_session(student["student_id"])
    if load_parent_history:
        st.session_state.parent_chat = load_parent_chat(student["student_id"])


def start_lesson_for_student(
    student: dict, restore_chat: bool = True, is_new: bool = False
) -> None:
    sync_ui_from_student(student)
    if restore_chat:
        assistant.restore_messages(load_live_chat(student["student_id"]))
    else:
        assistant.restore_messages([])
    st.session_state.show_session_dialog = False
    apply_lesson_context()
    if is_new:
        st.toast(f"Student ID: {student['student_id']} — save this for next time!")
    else:
        st.toast(f"Welcome back, {student['child_name']}!")
    assistant.start()
    st.rerun()


def student_context_for_voice() -> str:
    student = active_student()
    if not student:
        return ""
    return build_student_session_context(student)


def apply_lesson_context() -> None:
    assistant.set_lesson_context(
        homework_context_for_voice(),
        student_context_for_voice(),
    )


def maybe_log_ended_lesson() -> None:
    snap = assistant.snapshot()
    sid = st.session_state.active_student_id
    if (
        snap["status"] == "stopped"
        and not st.session_state.session_logged
        and sid
    ):
        msgs = [m for m in snap["messages"] if m["role"] in ("user", "assistant")]
        if msgs:
            try:
                log_live_session(sid, snap["messages"], snap["interruptions"])
                save_live_chat(sid, snap["messages"])
            except Exception:
                pass
        st.session_state.session_logged = True
    if snap["status"] in ("running", "starting"):
        st.session_state.session_logged = False


@st.dialog("Before we start")
def session_start_dialog() -> None:
    tab_new, tab_search = st.tabs(["New student", "Already registered"])

    with tab_new:
        st.caption("SHIKSHA will say hello first so you don't feel nervous.")
        name = st.text_input("Child's name *", key="dlg_name_input")
        c1, c2 = st.columns(2)
        with c1:
            age = st.text_input("Age (optional)", key="dlg_age_input")
        with c2:
            grade = st.text_input("Class (optional)", key="dlg_grade_input")
        parent = st.text_input("Parent name (optional)", key="dlg_parent_input")

        if st.button("Start my lesson", type="primary", use_container_width=True, key="dlg_start_new"):
            if not name.strip():
                st.error("Please enter the child's name.")
                return
            try:
                student = upsert_student(
                    child_name=name,
                    age=age,
                    grade=grade,
                    parent_name=parent,
                )
                start_lesson_for_student(student, restore_chat=False, is_new=True)
            except Exception as exc:
                st.error(str(exc))

    with tab_search:
        st.caption("Search your profile and continue your last conversation.")
        mode = st.selectbox(
            "Search by",
            SEARCH_BY_OPTIONS,
            key="dlg_search_mode_select",
        )
        query = st.text_input(
            "Enter Student ID or name",
            value=st.session_state.dlg_search_query,
            placeholder="SHK-XXXXXX or Arjun",
            key="dlg_search_query_input",
        )
        if st.button("Search", use_container_width=True, key="dlg_do_search"):
            st.session_state.dlg_search_query = query
            st.session_state.dlg_search_results = search_students_by_mode(query, mode)

        results = st.session_state.get("dlg_search_results", [])
        if results:
            if len(results) == 1:
                s = results[0]
                st.success(f"Found **{s['child_name']}** · `{s['student_id']}`")
                prior = load_live_chat(s["student_id"])
                if prior:
                    st.caption(f"Last chat: {len(prior)} messages — will continue where you left off.")
                if st.button(
                    "Continue lesson",
                    type="primary",
                    use_container_width=True,
                    key="dlg_continue_one",
                ):
                    start_lesson_for_student(s, restore_chat=True)
            else:
                st.markdown("**Pick your profile:**")
                for s in results:
                    if st.button(
                        f"{s['child_name']} · {s['student_id']}",
                        key=f"dlg_pick_{s['student_id']}",
                        use_container_width=True,
                    ):
                        start_lesson_for_student(s, restore_chat=True)

    if st.button("Cancel", use_container_width=True, key="dlg_cancel"):
        st.session_state.show_session_dialog = False
        st.rerun()


def render_student_search(
    key_prefix: str,
    *,
    load_parent_history: bool = False,
    compact: bool = False,
) -> bool:
    """Search by ID or name. Returns True if a student is active after search."""
    if compact:
        st.caption("Link work to a student (same ID as live class & parent reports).")

    c1, c2, c3 = st.columns([1.1, 2, 1])
    with c1:
        mode = st.selectbox(
            "Search by",
            SEARCH_BY_OPTIONS,
            key=f"{key_prefix}_search_mode",
        )
    with c2:
        query = st.text_input(
            "Search",
            placeholder="SHK-XXXXXX or child name",
            key=f"{key_prefix}_search_query",
            label_visibility="collapsed",
        )
    with c3:
        clicked = st.button("Search", key=f"{key_prefix}_search_btn", use_container_width=True)

    if clicked and query.strip():
        matches = search_students_by_mode(query.strip(), mode)
        if not matches:
            st.warning("No student found.")
        elif len(matches) == 1:
            sync_ui_from_student(matches[0], load_parent_history=load_parent_history)
            st.success(f"Linked: **{matches[0]['child_name']}** · `{matches[0]['student_id']}`")
        else:
            st.markdown("**Pick one:**")
            for m in matches:
                if st.button(
                    f"{m['child_name']} · {m['student_id']}",
                    key=f"{key_prefix}_pick_{m['student_id']}",
                    use_container_width=True,
                ):
                    sync_ui_from_student(m, load_parent_history=load_parent_history)
                    st.rerun()

    student = active_student()
    if student:
        st.info(
            f"Active student: **{student['child_name']}** · ID: `{student['student_id']}`"
        )
        return True
    return False


def homework_context_for_voice() -> str:
    parts = []
    if st.session_state.homework_board.strip():
        parts.append(st.session_state.homework_board.strip())
    if st.session_state.get("voice_homework", "").strip():
        parts.append("Homework already assigned in class:\n")
        parts.append(st.session_state.voice_homework.strip())
    if st.session_state.generated_homework.strip():
        parts.append("Latest generated homework sheet:\n")
        parts.append(st.session_state.generated_homework.strip())
    return "\n\n".join(parts)


init_session_state()
assistant: LiveVoiceAssistant = st.session_state.assistant
apply_lesson_context()
state_snapshot = assistant.snapshot()
status = state_snapshot["status"]
sync_homework_from_live_lesson()
maybe_log_ended_lesson()

if st.session_state.show_session_dialog:
    session_start_dialog()

# --- Header ---
st.markdown('<h1 class="main-title">SHIKSHA</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="sub-title">Your AI teaching assistant — live lessons, homework, and feedback</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p style="text-align:center;margin-top:-1rem;margin-bottom:1rem;">'
    '<span class="badge-teach">Live voice class</span>'
    '<span class="badge-teach">Homework writer</span>'
    '<span class="badge-teach">PDF & Word export</span>'
    '<span class="badge-teach">Submit & check work</span>'
    '<span class="badge-teach">Parent report card</span>'
    "</p>",
    unsafe_allow_html=True,
)

tab_live, tab_homework, tab_parent = st.tabs(
    ["🎙️ Live class", "📝 Homework & tasks", "👨‍👩‍👧 Parent corner"]
)

# ===================== LIVE CLASS =====================
with tab_live:
    col1, col2, col3 = st.columns([1, 1, 1.2])

    student = active_student()
    if student:
        st.success(
            f"**{student['child_name']}** · Student ID: `{student['student_id']}` "
            "(share this ID with parents for reports)"
        )
    else:
        st.info("Tap **Start lesson** — a short form will open first (name, age, class).")

    with col1:
        if st.button(
            "▶️ Start lesson",
            use_container_width=True,
            disabled=status in ["running", "starting"],
        ):
            st.session_state.show_session_dialog = True
            st.rerun()

    with col2:
        if st.button(
            "⏹️ Stop lesson",
            use_container_width=True,
            disabled=status not in ["running", "starting"],
        ):
            assistant.stop()
            snap = assistant.snapshot()
            sid = st.session_state.active_student_id
            if sid:
                try:
                    sync_voice_homework(sid, snap["messages"])
                    log_live_session(sid, snap["messages"], snap["interruptions"])
                    save_live_chat(sid, snap["messages"])
                    load_homework_into_session(sid)
                except Exception as exc:
                    st.warning(f"Could not save session log: {exc}")
            st.session_state.session_logged = True
            st.rerun()

    with col3:
        st.markdown(
            f"""
        <div class="status-box">
            <span class="status-dot status-{status}"></span>
            <span style="font-weight:600;text-transform:uppercase;letter-spacing:1px;font-size:0.9rem;color:#e2e8f0;">
                {status}
            </span>
        </div>
        """,
            unsafe_allow_html=True,
        )

    if state_snapshot["error"]:
        st.error(f"Error: {state_snapshot['error']}")

    if st.session_state.homework_board.strip() or st.session_state.generated_homework.strip():
        with st.expander("📋 Tasks loaded for this lesson", expanded=False):
            st.markdown(
                f'<div class="homework-board">{homework_context_for_voice().replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True,
            )

    st.divider()
    st.markdown("### 💬 Live conversation")
    chat_container = st.container(height=420, border=False)

    with chat_container:
        messages = state_snapshot["messages"]
        if not messages:
            st.markdown(
                "<p style='text-align:center;color:#718096;margin-top:32px;'>"
                "Start a lesson and speak naturally. SHIKSHA will teach, assign tasks, "
                "and discuss homework from the <strong>Homework & tasks</strong> tab.</p>",
                unsafe_allow_html=True,
            )
        else:
            for msg in messages:
                role = msg["role"]
                text = msg["text"]
                if role == "system":
                    st.info(text, icon="ℹ️")
                else:
                    with st.chat_message("user" if role == "user" else "assistant"):
                        st.write(text)

    if status in ["running", "starting"] or state_snapshot["interruptions"] > 0:
        st.caption(
            f"Interruptions: {state_snapshot['interruptions']} · Model: {state_snapshot['model']}"
        )

    if status in ["starting", "running"]:
        time.sleep(1.0)
        st.rerun()

# ===================== HOMEWORK & TASKS =====================
with tab_homework:
    st.markdown("### 📌 Task & homework board")
    render_student_search("hw", compact=True)
    if not active_student():
        st.warning("Search for the student above so homework saves to their progress report.")

    st.caption(
        f"{ASSISTANT_NAME} uses this board for voice class and printable sheets."
    )

    board_col, action_col = st.columns([2, 1])

    with board_col:
        st.session_state.homework_board = st.text_area(
            "Add tasks, subjects, and homework details",
            value=st.session_state.homework_board,
            height=160,
            placeholder=(
                "Example:\n"
                "- Math: 10 addition sums (two digits)\n"
                "- English: Write 5 sentences using 'because'\n"
                "- Hindi: Learn poem 'Machli Jal Ki Rani Hai' first two lines\n"
                "- Due: tomorrow evening"
            ),
            label_visibility="collapsed",
        )

    with action_col:
        st.session_state.grade_hint = st.text_input(
            "Grade / age (optional)", value=st.session_state.grade_hint, placeholder="e.g. Class 2, age 7"
        )
        if st.button("💾 Save board", use_container_width=True):
            persist_homework_session()
            apply_lesson_context()
            st.success("Saved. Live lessons will use this board.")

    if st.session_state.get("voice_homework", "").strip():
        st.markdown("### 🎙️ From live class (SHIKSHA assigned)")
        st.markdown(st.session_state.voice_homework)
        if st.button("Copy to task board", key="copy_voice_to_board"):
            combined = st.session_state.homework_board.strip()
            if combined:
                combined += "\n\n"
            st.session_state.homework_board = combined + st.session_state.voice_homework
            persist_homework_session()
            st.success("Added to task board below.")
            st.rerun()
    elif active_student():
        st.caption(
            "Homework SHIKSHA gives in voice class will appear here automatically."
        )

    if st.session_state.homework_board.strip():
        st.markdown("**Your task board**")
        st.markdown(
            f'<div class="homework-board">{st.session_state.homework_board.replace(chr(10), "<br>")}</div>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("### ✍️ Create homework sheet")
    gen_col1, gen_col2 = st.columns(2)

    with gen_col1:
        if st.button("🤖 Ask SHIKSHA to write homework", use_container_width=True):
            if not st.session_state.homework_board.strip():
                st.warning("Add details on the board first.")
            else:
                with st.spinner("Writing homework…"):
                    try:
                        st.session_state.generated_homework = generate_homework_sheet(
                            st.session_state.homework_board,
                            st.session_state.grade_hint,
                        )
                        persist_homework_session()
                        if st.session_state.active_student_id:
                            log_homework_assigned(
                                st.session_state.active_student_id,
                                st.session_state.homework_board,
                                st.session_state.generated_homework,
                            )
                        apply_lesson_context()
                        st.success("Homework sheet ready.")
                    except Exception as exc:
                        st.error(f"Could not generate: {exc}")

    with gen_col2:
        st.caption("Export the generated sheet below as PDF or Word.")

    if st.session_state.generated_homework:
        st.session_state.generated_homework = st.text_area(
            "Generated homework (edit if needed)",
            value=st.session_state.generated_homework,
            height=220,
        )

        title = f"SHIKSHA Homework — {date.today().isoformat()}"
        body = st.session_state.generated_homework
        dl1, dl2 = st.columns(2)
        try:
            pdf_bytes = create_pdf_bytes(title, body)
            docx_bytes = create_docx_bytes(title, body)
            with dl1:
                st.download_button(
                    "📄 Download PDF",
                    data=pdf_bytes,
                    file_name="shiksha_homework.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            with dl2:
                st.download_button(
                    "📘 Download Word",
                    data=docx_bytes,
                    file_name="shiksha_homework.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
        except Exception as exc:
            st.error(f"Export failed: {exc}")

    st.divider()
    st.markdown("### ✅ Submit homework for checking")
    st.caption("Upload a photo, PDF, Word file, or paste answers. SHIKSHA will review kindly.")

    check_col1, check_col2 = st.columns(2)

    with check_col1:
        uploaded = st.file_uploader(
            "Upload homework",
            type=["png", "jpg", "jpeg", "webp", "pdf", "docx", "txt"],
            label_visibility="collapsed",
        )

    with check_col2:
        st.session_state.submission_notes = st.text_area(
            "Or paste answers here",
            value=st.session_state.submission_notes,
            height=120,
            label_visibility="visible",
        )

    if st.button("🔍 Check my homework", use_container_width=True):
        assignment = st.session_state.generated_homework or st.session_state.homework_board
        if not assignment.strip() and not uploaded and not st.session_state.submission_notes.strip():
            st.warning("Add expected homework on the board (or generate a sheet) and submit work to check.")
        else:
            with st.spinner("SHIKSHA is checking…"):
                try:
                    submission_text = st.session_state.submission_notes
                    image_parts = []
                    if uploaded is not None:
                        extracted, image_parts = extract_upload_text(uploaded)
                        submission_text = f"{submission_text}\n\n{extracted}".strip()
                    st.session_state.check_result = check_homework(
                        assignment_context=assignment,
                        submission_text=submission_text,
                        image_parts=image_parts or None,
                    )
                    sid = st.session_state.active_student_id
                    if sid:
                        log_homework_check(
                            sid, assignment[:300], st.session_state.check_result
                        )
                        st.success("Saved to this student's progress (visible in Parent corner).")
                    else:
                        st.warning("Search for the student at the top so this is saved to their report.")
                except Exception as exc:
                    st.error(f"Check failed: {exc}")

    if st.session_state.check_result:
        st.markdown("#### Feedback")
        st.markdown(st.session_state.check_result)

# ===================== PARENT CORNER =====================
with tab_parent:
    st.markdown("### 👨‍👩‍👧 Parent corner — progress & report card")
    render_student_search("parent", load_parent_history=True)

    student = active_student()
    if student:
        st.success(
            f"**{student['child_name']}** · ID: `{student['student_id']}` · "
            f"Class: {student.get('grade') or '—'} · Age: {student.get('age') or '—'} · "
            f"Parent: {student.get('parent_name') or '—'}"
        )
        with st.expander("Progress & activity", expanded=True):
            st.markdown(student_summary_for_display(student["student_id"]))
    else:
        st.info("Use the search above to load your child's progress.")

    st.divider()

    chat_col, report_col = st.columns([1.2, 1])

    with chat_col:
        st.markdown("#### 💬 Talk to SHIKSHA (parent)")
        parent_attachment = st.file_uploader(
            "Attach photo or document (optional)",
            type=["png", "jpg", "jpeg", "webp", "pdf", "docx", "txt"],
            key="parent_chat_attachment",
        )

        for msg in st.session_state.parent_chat:
            with st.chat_message("user" if msg["role"] == "parent" else "assistant"):
                st.markdown(msg["text"])

        parent_input = st.chat_input(
            "Ask about progress, homework, or attach a file above…",
            disabled=not st.session_state.active_student_id,
        )

        if parent_input and st.session_state.active_student_id:
            sid = st.session_state.active_student_id
            full_message = parent_input.strip()
            image_parts = []
            if parent_attachment is not None:
                extracted, image_parts = extract_upload_text(parent_attachment)
                if extracted:
                    full_message = f"{full_message}\n\n[Attachment]\n{extracted}"

            st.session_state.parent_chat.append({"role": "parent", "text": full_message})
            with st.spinner("SHIKSHA is preparing your answer…"):
                try:
                    reply = answer_parent_message(
                        sid,
                        full_message,
                        st.session_state.parent_chat[:-1],
                        image_parts=image_parts or None,
                    )
                    st.session_state.parent_chat.append(
                        {"role": "assistant", "text": reply}
                    )
                    save_parent_chat(sid, st.session_state.parent_chat)
                except Exception as exc:
                    err = f"Sorry, I could not respond: {exc}"
                    st.session_state.parent_chat.append(
                        {"role": "assistant", "text": err}
                    )
                    save_parent_chat(sid, st.session_state.parent_chat)
                    st.error(str(exc))
            st.rerun()

        if st.button("Clear parent chat", use_container_width=True):
            st.session_state.parent_chat = []
            if st.session_state.active_student_id:
                save_parent_chat(st.session_state.active_student_id, [])
            st.rerun()

    with report_col:
        st.markdown("#### 📋 Full report card")
        st.session_state.parent_report_notes = st.text_area(
            "Anything extra for this report?",
            value=st.session_state.parent_report_notes,
            height=80,
            label_visibility="collapsed",
            placeholder="e.g. Focus on English speaking this month…",
        )

        if st.button("📋 Generate report card", use_container_width=True):
            if not st.session_state.active_student_id:
                st.warning("Search for your child by name or Student ID first.")
            else:
                with st.spinner("Writing report card…"):
                    try:
                        st.session_state.report_card = generate_report_card(
                            st.session_state.active_student_id,
                            st.session_state.parent_report_notes,
                        )
                    except Exception as exc:
                        st.error(f"Report failed: {exc}")

        if st.session_state.report_card:
            st.markdown(st.session_state.report_card)
            child = st.session_state.child_name.strip() or "student"
            title = f"SHIKSHA Report — {child} — {date.today().isoformat()}"
            try:
                st.download_button(
                    "📄 Download report (PDF)",
                    data=create_pdf_bytes(title, st.session_state.report_card),
                    file_name=f"shiksha_report_{child.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
            except Exception as exc:
                st.caption(f"PDF export: {exc}")

