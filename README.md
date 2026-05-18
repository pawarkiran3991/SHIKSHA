# SHIKSHA — AI Teaching Assistant for Kids

SHIKSHA (Shiksha Di) is a voice-first AI tutor for children aged 4–12. It runs live lessons with Google Gemini, manages homework, tracks each student with a unique ID, and gives parents progress reports.

**Repository:** [github.com/pawarkiran3991/SHIKSHA](https://github.com/pawarkiran3991/SHIKSHA)

## Features

- **Live voice class** — Real-time teaching via microphone and speaker (Gemini Live API)
- **Warm tutor persona** — Hinglish-friendly, encouraging, stories, poems, English speaking, good habits
- **Homework board** — Assign tasks, generate sheets, export **PDF** or **Word**
- **Homework checking** — Upload photos/PDF/DOCX or paste answers for AI feedback
- **Voice homework sync** — Homework given in class appears on the Homework tab
- **Student IDs** — Each child gets an ID like `SHK-XXXXXX` for returning sessions
- **Parent corner** — Search by name or ID, chat with SHIKSHA, download report cards

## Project structure

| File | Description |
|------|-------------|
| `app.py` | Streamlit web UI (tabs: Live class, Homework, Parent corner) |
| `main.py` | Live voice session, audio I/O, system prompt |
| `homework.py` | Homework generation, checking, PDF/DOCX export |
| `progress.py` | Student registry, activity logs, parent reports, chat history |
| `requirements.txt` | Python dependencies |

Local data (not in git): `data/` — students, activities, homework, chats.

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
streamlit run app.py
```

Open the URL shown in the terminal (usually `http://localhost:8501`).

## How to use

### Child / student

1. Click **Start lesson** → enter name (and optional age, class) or search an existing **Student ID**.
2. Speak with SHIKSHA; she greets first to help kids feel comfortable.
3. Use **Homework & tasks** for boards, downloads, and submitting work (search the same student ID).

### Parent

1. Open **Parent corner**.
2. **Search by** Student ID or name → **Search**.
3. View progress, chat with SHIKSHA, or **Generate report card** (PDF download).

## Environment variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Required for all AI features |
| `GEMINI_MODEL` | Live voice model (must support Live API) |
| `GEMINI_TEXT_MODEL` | Text tasks: homework, reports, parent chat |

## License

Private / educational use — add a license file if you open-source this project.

## Author

[pawarkiran3991](https://github.com/pawarkiran3991)
