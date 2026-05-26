# SHIKSHA — AI Teaching Assistant for Kids

SHIKSHA (Shiksha Di) is a voice-first AI tutor for children aged 4–12. It runs live lessons with Google Gemini, manages homework, tracks each student with a unique ID, and gives parents progress reports.

**Repository:** [github.com/pawarkiran3991/SHIKSHA](https://github.com/pawarkiran3991/SHIKSHA)

## Features

- **Live voice class** — Real-time teaching via microphone and speaker (Gemini Live API)
- **Class syllabus** — Per-grade topic plans (JSON) injected into lessons; mini on-screen visuals when images are added
- **Warm tutor persona** — Hinglish-friendly, encouraging, stories, poems, English speaking, good habits
- **Homework board** — Assign tasks, generate sheets, export **PDF** or **Word**
- **Homework checking** — Upload photos/PDF/DOCX or paste answers for AI feedback
- **Student IDs** — Each child gets an ID like `S1`, `S2` for returning sessions
- **Parent corner** — Search by name or ID, **persistent parent chat**, task board, progress stats, report cards (PDF)

## Project structure

| File | Description |
|------|-------------|
| `fastapi_app.py` | Web UI (FastAPI + Jinja templates) |
| `main.py` | Live voice session, audio I/O, system prompt |
| `homework.py` | Homework generation, checking, PDF/DOCX export |
| `progress.py` | SQLite students, sessions, parent chat, syllabus progress |
| `syllabus.py` | Class syllabus packs under `data/syllabus/` |
| `session_store.py` | Per-browser cookie sessions (multi-tab safe) |
| `templates/index.html` | Main UI |
| `docs/SHIKSHA_PRODUCT_PLAN.md` | Product roadmap |

Local data (not in git): `data/` — SQLite DB, syllabus JSON, teaching images.

## Requirements

- Python 3.10+
- Microphone and speakers
- [Google AI API key](https://aistudio.google.com/apikey) (Gemini)

## Setup

```powershell
cd fwdai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.0-flash-live-preview
GEMINI_TEXT_MODEL=gemini-2.0-flash
```

Optional: adjust live model name if your account supports a different Live preview model.

## Run

```powershell
uvicorn fastapi_app:app --reload
```

Open **http://127.0.0.1:8000**

## How to use

### Child / student

1. **Live class** → enter name (lookup fills details) or register with age, class, parent name.
2. Pick **class** from the dropdown (Jr KG … Class 6).
3. Speak with SHIKSHA; use the **class screen** for syllabus pictures when you add PNGs under `data/syllabus/`.
4. **Homework & tasks** — board, generate sheet, download PDF/Word, submit work for checking.

### Parent

1. **Parent corner** → search by Student ID or name.
2. View **progress stats**, mark **syllabus topics**, manage **parent task board**.
3. Chat with SHIKSHA (history is saved per student).
4. **Generate report card** → download PDF.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Required for all AI features |
| `GEMINI_MODEL` | Live voice model |
| `GEMINI_TEXT_MODEL` | Homework, checks, parent chat, reports |

## Syllabus packs

Add `data/syllabus/class_1.json` (see `jr_kg.json`, `class_1.json` samples). Place images at paths referenced in `pages[].file` (e.g. `data/syllabus/class_1/en_a_apple.png`).

## License

MIT — see `LICENSE`.
