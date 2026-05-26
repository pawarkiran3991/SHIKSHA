"""Class syllabus packs, topic progress, and teaching image manifests for SHIKSHA."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
SYLLABUS_DIR = DATA_DIR / "syllabus"

# Standard dropdown options (plan)
GRADE_OPTIONS: list[str] = [
    "Jr KG",
    "Sr KG",
    "Class 1",
    "Class 2",
    "Class 3",
    "Class 4",
    "Class 5",
    "Class 6",
]

_GRADE_FILE_MAP = {
    "Jr KG": "jr_kg.json",
    "Sr KG": "sr_kg.json",
    "Class 1": "class_1.json",
    "Class 2": "class_2.json",
    "Class 3": "class_3.json",
    "Class 4": "class_4.json",
    "Class 5": "class_5.json",
    "Class 6": "class_6.json",
}


def grade_to_slug(grade: str) -> str:
    g = (grade or "").strip()
    return _GRADE_FILE_MAP.get(g, "")


def load_syllabus(grade: str) -> dict[str, Any]:
    """Load syllabus JSON for a class. Returns empty scaffold if missing."""
    slug = grade_to_slug(grade)
    if not slug:
        return {"grade": grade, "topics": []}
    path = SYLLABUS_DIR / slug
    if not path.exists():
        return {"grade": grade, "topics": [], "_note": "Syllabus file not found — add data/syllabus/" + slug}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"grade": grade, "topics": []}


def get_topic_by_id(grade: str, topic_id: str) -> dict[str, Any] | None:
    for topic in load_syllabus(grade).get("topics", []):
        if topic.get("id") == topic_id:
            return topic
    return None


def build_syllabus_context_for_prompt(
    grade: str,
    progress_map: dict[str, str] | None = None,
    current_topic_id: str | None = None,
) -> str:
    """Text block for live lesson / parent prompts (simple RAG — no vector DB)."""
    syllabus = load_syllabus(grade)
    topics = syllabus.get("topics", [])
    if not topics:
        return f"## CLASS SYLLABUS\nGrade: {grade or 'not set'}\n(No syllabus loaded yet.)"

    progress_map = progress_map or {}
    lines = [
        f"## CLASS SYLLABUS — {syllabus.get('grade', grade)}",
        f"Total topics in plan: {len(topics)}",
        "",
    ]

    done: list[str] = []
    pending: list[str] = []
    in_progress: list[str] = []

    for t in topics:
        tid = t.get("id", "")
        title = t.get("title", tid)
        status = progress_map.get(tid, "pending")
        if status == "done":
            done.append(title)
        elif status == "in_progress":
            in_progress.append(title)
        else:
            pending.append(title)

    if done:
        lines.append("### Completed topics")
        lines.extend(f"- {x}" for x in done[:12])
    if in_progress:
        lines.append("### Currently teaching")
        lines.extend(f"- {x}" for x in in_progress)
    if pending:
        lines.append("### Up next (pending)")
        lines.extend(f"- {x}" for x in pending[:8])

    if current_topic_id:
        topic = get_topic_by_id(grade, current_topic_id)
        if topic:
            lines += [
                "",
                "### TODAY'S FOCUS TOPIC",
                f"ID: {topic.get('id')}",
                f"Title: {topic.get('title')}",
                f"Teaching hint: {topic.get('teaching_hint', '')}",
            ]
            pages = topic.get("pages", [])
            if pages:
                lines.append("Visual pages for child screen:")
                for p in pages[:5]:
                    lines.append(f"  - {p.get('caption', '')} (image: {p.get('file', '')})")

    return "\n".join(lines)


def first_pending_topic_id(grade: str, progress_map: dict[str, str]) -> str | None:
    for t in load_syllabus(grade).get("topics", []):
        tid = t.get("id", "")
        if progress_map.get(tid, "pending") != "done":
            return tid
    return None
