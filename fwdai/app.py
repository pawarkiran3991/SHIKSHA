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
    list_students,
    log_homework_assigned,
    log_homework_check,
    log_live_session,
    search_students,
    upsert_student,
)

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
@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@300..700&display=swap');

html, body, [class*="css"], .stMarkdown, .stButton, .stTextInput, .stTextArea {
    font-family: 'Fredoka', sans-serif !important;
}

.main-title {
    background: linear-gradient(135deg, #ff6b6b 0%, #feca57 50%, #1dd1a1 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 3.5rem;
    font-weight: 700;
    text-align: center;
    margin-bottom: 0.1rem;
    padding-top: 0.5rem;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.05);
}

.sub-title {
    text-align: center;
    color: var(--text-color);
    opacity: 0.9;
    font-size: 1.25rem;
    margin-bottom: 1.5rem;
    font-weight: 400;
}

.badge-teach {
    display: inline-block;
    background: linear-gradient(135deg, #ffeaa7 0%, #ffd2df 100%) !important;
    color: #2d3436 !important;
    border: 2px solid #feca57 !important;
    border-radius: 999px;
    padding: 6px 16px;
    font-size: 0.95rem;
    font-weight: 600;
    margin: 4px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    transition: transform 0.2s;
}

.badge-teach:hover {
    transform: scale(1.05);
}

.status-box {
    background: rgba(255, 255, 255, 0.95);
    border: 2px solid #feca57;
    border-radius: 16px;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    box-shadow: 0 4px 10px rgba(0,0,0,0.1);
}

.status-dot {
    height: 14px;
    width: 14px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 12px;
}

.status-idle { background-color: #8395a7; }
.status-starting { background-color: #feca57; animation: pulse-yellow 1.5s infinite; }
.status-running { background-color: #1dd1a1; animation: pulse-green 1.5s infinite; }
.status-stopped { background-color: #ff9f43; }
.status-error { background-color: #ff6b6b; }

@keyframes pulse-green {
    0% { box-shadow: 0 0 0 0 rgba(29, 209, 161, 0.7); }
    70% { box-shadow: 0 0 0 10px rgba(29, 209, 161, 0); }
    100% { box-shadow: 0 0 0 0 rgba(29, 209, 161, 0); }
}

@keyframes pulse-yellow {
    0% { box-shadow: 0 0 0 0 rgba(254, 202, 87, 0.7); }
    70% { box-shadow: 0 0 0 10px rgba(254, 202, 87, 0); }
    100% { box-shadow: 0 0 0 0 rgba(254, 202, 87, 0); }
}

.homework-board {
    background: #f8f9fa;
    color: #2d3436 !important;
    border: 3px dashed #ff9f43;
    border-radius: 16px;
    padding: 1.25rem;
    min-height: 80px;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.05);
}

.stButton button {
    border-radius: 16px !important;
    font-weight: 600 !important;
    font-size: 1.05rem !important;
    border: 2px solid #feca57 !important;
    background-color: var(--secondary-background-color) !important;
    color: var(--text-color) !important;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important;
    transition: all 0.2s ease-in-out !important;
}

.stButton button:hover {
    background-color: #feca57 !important;
    color: #2d3436 !important;
    transform: translateY(-2px) scale(1.02);
    box-shadow: 0 6px 12px rgba(0,0,0,0.15) !important;
}

.stButton button:disabled {
    background-color: rgba(255, 255, 255, 0.05) !important;
    color: rgba(255, 255, 255, 0.3) !important;
    border-color: rgba(255, 255, 255, 0.1) !important;
    transform: none !important;
    box-shadow: none !important;
}

.stButton button[kind="primary"], .stButton button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #1dd1a1 0%, #10ac84 100%) !important;
    color: white !important;
    border: 2px solid transparent !important;
}

.stButton button[kind="primary"]:hover, .stButton button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #10ac84 0%, #1dd1a1 100%) !important;
    color: white !important;
}

/* Tab labels styling */
.stTabs [data-baseweb="tab-list"] {
    gap: 12px;
}

.stTabs [data-baseweb="tab"] {
    background-color: var(--secondary-background-color) !important;
    color: var(--text-color) !important;
    border-radius: 12px 12px 0 0;
    padding: 10px 20px;
    font-weight: 600;
    opacity: 0.75;
    border: 1px solid rgba(255, 255, 255, 0.05);
}

.stTabs [data-baseweb="tab"]:hover {
    opacity: 1.0;
    color: var(--text-color) !important;
}

.stTabs [aria-selected="true"] {
    background-color: #ffeaa7 !important;
    color: #2d3436 !important;
    border: 2px solid #feca57;
    border-bottom: none;
    opacity: 1.0;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style="text-align: center; font-size: 2.2rem; margin-top: -10px; margin-bottom: 20px;">
        🍎 ✨ 🧸 🎈 🚀 🦄 📚 🎨
    </div>
    """,
    unsafe_allow_html=True,
)


def init_session_state() -> None:
    defaults = {
        "assistant": None,
        "homework_board": "",
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
        "pending_start": False,
        "dlg_name": "",
        "dlg_age": "",
        "dlg_grade": "",
        "dlg_parent": "",
        "dlg_student_id": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if st.session_state.assistant is None:
        st.session_state.assistant = LiveVoiceAssistant()


def active_student() -> dict | None:
    sid = st.session_state.active_student_id
    return get_student(sid) if sid else None


def sync_ui_from_student(student: dict) -> None:
    st.session_state.active_student_id = student["student_id"]
    st.session_state.child_name = student.get("child_name", "")
    st.session_state.child_age = student.get("age", "")
    st.session_state.child_grade = student.get("grade", "")
    st.session_state.parent_name = student.get("parent_name", "")
    st.session_state.child_notes = student.get("notes", "")
    
    # Load their latest homework onto the board and workspace
    hw = student.get("latest_homework", "")
    st.session_state.generated_homework = hw
    st.session_state.homework_board = hw


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
            log_live_session(sid, snap["messages"], snap["interruptions"])
        st.session_state.session_logged = True
    if snap["status"] in ("running", "starting"):
        st.session_state.session_logged = False


@st.dialog("Before we start — tell me about you!")
def session_start_dialog() -> None:
    render_session_start_form(show_cancel=True)


def render_session_start_form(show_cancel: bool = False) -> None:
    st.markdown(
        "SHIKSHA will **say hello first** so you don't feel nervous. "
        "Parents: save the **Student ID** shown after signup to view reports later."
    )
    returning_id = st.text_input(
        "Already have a Student ID? (optional)",
        value=st.session_state.dlg_student_id,
        placeholder="e.g. S1, S2 …",
    )
    # Look up by ID directly (case-insensitive)
    lookup_id = returning_id.strip().upper()
    existing = get_student(lookup_id) if lookup_id else None
    if existing:
        st.info(
            f"Welcome back, **{existing['child_name']}**! "
            f"ID: `{existing['student_id']}`"
        )

    name = st.text_input("Child's name *", value=st.session_state.dlg_name or (existing or {}).get("child_name", ""))
    c1, c2 = st.columns(2)
    with c1:
        age = st.text_input("Age (optional)", value=st.session_state.dlg_age or (existing or {}).get("age", ""))
    with c2:
        grade = st.text_input("Class (optional)", value=st.session_state.dlg_grade or (existing or {}).get("grade", ""))
    parent = st.text_input(
        "Parent name (optional)",
        value=st.session_state.dlg_parent or (existing or {}).get("parent_name", ""),
    )

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Start my lesson", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Please enter the child's name.")
                return
            try:
                sid = existing["student_id"] if existing else (lookup_id if lookup_id and get_student(lookup_id) else None)
                student = upsert_student(
                    child_name=name,
                    age=age,
                    grade=grade,
                    parent_name=parent,
                    student_id=sid,
                )
                sync_ui_from_student(student)
                # Hide the dialog first; the full app rerun starts audio cleanly.
                st.session_state.show_session_dialog = False
                st.session_state.pending_start = True
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with b2:
        if show_cancel and st.button("Cancel", use_container_width=True):
            st.session_state.show_session_dialog = False
            st.rerun()


def homework_context_for_voice() -> str:
    parts = []
    if st.session_state.homework_board.strip():
        parts.append(st.session_state.homework_board.strip())
    if st.session_state.generated_homework.strip():
        parts.append("Latest generated homework sheet:\n")
        parts.append(st.session_state.generated_homework.strip())
    return "\n\n".join(parts)


# --- Top-Level Render ---
init_session_state()
assistant: LiveVoiceAssistant = st.session_state.assistant
apply_lesson_context()

# Handle deferred session start (so dialog closes cleanly before audio begins)
if st.session_state.pending_start:
    st.session_state.pending_start = False
    if not assistant.is_running():
        apply_lesson_context()
        assistant.start()
        st.toast(
            f"Session started! Student ID: {st.session_state.active_student_id} — save this for parent reports!",
            icon="🎉",
        )

state_snapshot = assistant.snapshot()
status = state_snapshot["status"]
maybe_log_ended_lesson()

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
    control_col, status_col = st.columns([1, 1.2])

    student = active_student()
    if student:
        st.success(
            f"**{student['child_name']}** · Student ID: `{student['student_id']}` "
            "(share this ID with parents for reports)"
        )
    else:
        st.info("Enter the student details below, then start the lesson.")

    with control_col:
        if st.button(
            "⏹️ Stop lesson",
            use_container_width=True,
            disabled=status not in ["running", "starting"],
        ):
            assistant.stop()
            snap = assistant.snapshot()
            if st.session_state.active_student_id:
                log_live_session(
                    st.session_state.active_student_id,
                    snap["messages"],
                    snap["interruptions"],
                )
            st.session_state.session_logged = True
            st.rerun()

    with status_col:
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

    if status not in ["running", "starting"]:
        st.markdown("### Before we start - tell me about you!")
        render_session_start_form()
    else:
        st.info("Lesson is running. Use **Stop lesson** when you are finished.")

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

# ===================== HOMEWORK & TASKS =====================
with tab_homework:
    st.markdown("### 📌 Task & homework board")
    st.caption(
        f"{ASSISTANT_NAME} uses this board to assign work in voice class and to generate printable sheets."
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
        col_save, col_clear = st.columns(2)
        with col_save:
            if st.button("💾 Save", use_container_width=True):
                apply_lesson_context()
                st.success("Saved!")
        with col_clear:
            if st.button("🗑️ Clear", use_container_width=True):
                st.session_state.homework_board = ""
                st.session_state.generated_homework = ""
                st.rerun()

    # Quick-generate homework from topic without needing board text
    st.markdown("**Ask SHIKSHA to assign homework for a topic:**")
    quick_col1, quick_col2 = st.columns([3, 1])
    with quick_col1:
        quick_topic = st.text_input(
            "Topic for homework",
            placeholder="e.g. Multiplication tables, English sentences, Hindi poem…",
            label_visibility="collapsed",
            key="quick_topic",
        )
    with quick_col2:
        if st.button("➕ Add to board", use_container_width=True):
            if quick_topic.strip():
                grade_str = st.session_state.grade_hint or st.session_state.child_grade or ""
                new_line = f"- {quick_topic.strip()}{(' (Grade: ' + grade_str + ')') if grade_str else ''}"
                if st.session_state.homework_board.strip():
                    st.session_state.homework_board += "\n" + new_line
                else:
                    st.session_state.homework_board = new_line
                apply_lesson_context()
                st.rerun()
            else:
                st.warning("Please enter a topic first.")

    if st.session_state.homework_board.strip():
        st.markdown("**Current board**")
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
                        if st.session_state.active_student_id:
                            log_homework_assigned(
                                st.session_state.active_student_id,
                                st.session_state.homework_board,
                                st.session_state.generated_homework,
                            )
                            # Update latest homework in student profile
                            student = get_student(st.session_state.active_student_id)
                            if student:
                                upsert_student(
                                    child_name=student["child_name"],
                                    age=student.get("age", ""),
                                    grade=student.get("grade", ""),
                                    parent_name=student.get("parent_name", ""),
                                    notes=student.get("notes", ""),
                                    latest_homework=st.session_state.generated_homework,
                                    student_id=student["student_id"],
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
                    if st.session_state.active_student_id:
                        log_homework_check(
                            st.session_state.active_student_id,
                            assignment[:300],
                            st.session_state.check_result,
                        )
                    else:
                        st.warning("Start a lesson first so homework is linked to a Student ID.")
                except Exception as exc:
                    st.error(f"Check failed: {exc}")

    if st.session_state.check_result:
        st.markdown("#### Feedback")
        st.markdown(st.session_state.check_result)

# ===================== PARENT CORNER =====================
with tab_parent:
    st.markdown("### 👨‍👩‍👧 Parent corner — find child & report card")
    st.caption(
        'Search by **child name** or **Student ID** (e.g. S1). '
        'Once loaded, you can check progress, generate report cards, and talk to SHIKSHA.'
    )

    search_col, search_btn = st.columns([3, 1])
    with search_col:
        st.session_state.parent_search_query = st.text_input(
            "Search name or Student ID",
            value=st.session_state.parent_search_query,
            placeholder="e.g. Mitansh or S1",
            label_visibility="collapsed",
        )
    with search_btn:
        do_search = st.button("🔍 Find child", use_container_width=True)

    if do_search and st.session_state.parent_search_query.strip():
        matches = search_students(st.session_state.parent_search_query)
        if not matches:
            st.warning("No student found. Check the name or ID from the child's lesson.")
        elif len(matches) == 1:
            sync_ui_from_student(matches[0])
            st.success(
                f"Loaded **{matches[0]['child_name']}** · ID: `{matches[0]['student_id']}`"
            )
            st.rerun()
        else:
            st.markdown("**Several matches — pick one:**")
            for m in matches:
                if st.button(
                    f"{m['child_name']} · {m['student_id']} · Class {m.get('grade') or '—'}",
                    key=f"pick_{m['student_id']}",
                    use_container_width=True,
                ):
                    sync_ui_from_student(m)
                    st.rerun()

    student = active_student()
    
    with st.expander("All registered students"):
        for s in list_students()[:20]:
            st.caption(f"{s['child_name']} — `{s['student_id']}`")

    st.divider()

    if student:
        # Show child profile in a gorgeous, read-only premium HTML card
        age_str = student.get("age") or "—"
        grade_str = student.get("grade") or "—"
        parent_str = student.get("parent_name") or "—"
        notes_str = student.get("notes") or "None"
        
        st.markdown(
            f"""
            <div style="background: rgba(254, 202, 87, 0.1); padding: 1.5rem; border-radius: 16px; border: 2px solid #feca57; margin-bottom: 1.5rem; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                <h3 style="margin-top: 0; color: #ff9f43; font-weight: 700; font-size: 1.6rem;">🎒 {student['child_name']}'s Learning Profile</h3>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; font-size: 1.1rem;">
                    <div><strong>🆔 Student ID:</strong> <span style="background-color: #ffeaa7; padding: 2px 8px; border-radius: 8px; font-weight: 600; color: #2d3436;">{student['student_id']}</span></div>
                    <div><strong>🏫 Class / Grade:</strong> {grade_str}</div>
                    <div><strong>🎂 Age:</strong> {age_str} years</div>
                    <div><strong>👨‍👩‍👧 Parent Name:</strong> {parent_str}</div>
                </div>
                <div style="margin-top: 15px; padding-top: 15px; border-top: 1px dashed rgba(0,0,0,0.1); font-size: 1.1rem;">
                    <strong>📝 Teacher Notes:</strong> {notes_str}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        chat_col, report_col = st.columns([1.2, 1])

        with chat_col:
            st.markdown("#### 💬 Talk to SHIKSHA (parent)")
            chat_container = st.container(height=300)
            with chat_container:
                if not st.session_state.parent_chat:
                    st.caption("Ask SHIKSHA questions like: 'How did Arjun perform in math today?' or 'What are his strengths?'")
                for msg in st.session_state.parent_chat:
                    with st.chat_message("user" if msg["role"] == "parent" else "assistant"):
                        st.markdown(msg["text"])

            parent_input = st.chat_input(
                f"Ask Shiksha about {student['child_name']}..."
            )
            if parent_input:
                st.session_state.parent_chat.append({"role": "parent", "text": parent_input})
                with st.spinner("SHIKSHA is preparing your answer…"):
                    try:
                        reply = answer_parent_message(
                            st.session_state.active_student_id,
                            parent_input,
                            st.session_state.parent_chat[:-1],
                        )
                        st.session_state.parent_chat.append(
                            {"role": "assistant", "text": reply}
                        )
                    except Exception as exc:
                        st.session_state.parent_chat.append(
                            {
                                "role": "assistant",
                                "text": f"Sorry, I could not respond: {exc}",
                            }
                        )
                st.rerun()

            if st.button("Clear parent chat", use_container_width=True):
                st.session_state.parent_chat = []
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
                child = student.get("child_name") or "student"
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
    else:
        st.warning("🔍 Please search for your child above by name or Student ID (e.g. S1) to see their details, report cards, and speak with SHIKSHA.")

# --- Auto refresh during live session ---
if status in ["starting", "running"]:
    time.sleep(1.0)
    st.rerun()
