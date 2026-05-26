# SHIKSHA — Product Plan, Architecture & Roadmap

**Document version:** 1.0  
**Project:** [SHIKSHA on GitHub](https://github.com/pawarkiran3991/SHIKSHA)  
**Languages:** English (Part A) · Hinglish (Part B) — same content, different audience  

---

## Table of contents

| Section | English | Hinglish |
|---------|---------|----------|
| Project summary | Part A §1 | Part B §1 |
| Current stack | Part A §2 | Part B §2 |
| Storage: SQLite vs JSON | Part A §3 | Part B §3 |
| Parent conversation memory | Part A §4 | Part B §4 |
| Class + syllabus + RAG | Part A §5 | Part B §5 |
| Images & mini teaching screen | Part A §6 | Part B §6 |
| Task board & charts | Part A §7 | Part B §7 |
| Similar projects (research) | Part A §8 | Part B §8 |
| Build phases | Part A §9 | Part B §9 |
| Author suggestions & opinion | Part A §10 | Part B §10 |

---

# Part A — English

## 1. Project summary

**SHIKSHA** (Shiksha Di) is an AI teaching assistant for children roughly **4–12 years old**. It combines:

- **Live voice lessons** (Gemini Live API — child speaks, SHIKSHA replies with voice)
- **Homework** (task board, AI-written sheets, PDF/Word export, upload & check)
- **Student profiles** (unique ID per child, e.g. `S1`, `S2`)
- **Parent corner** (search child, chat, progress, report card PDF)

**Goal:** Act like a real human tutor — warm, Hinglish-friendly, poems, stories, habits, daily check-ins — plus tools parents need (progress, homework, focus areas).

**Current UI:** FastAPI + `templates/index.html` (Streamlit removed).  
**Current data:** SQLite (`data/shiksha.db`) + optional JSON snapshot for export.

---

## 2. Current technical stack

| Layer | Technology |
|-------|------------|
| Voice engine | `main.py` — mic/speaker, Gemini Live |
| Web app | `fastapi_app.py` + `templates/index.html` |
| Homework | `homework.py` — generate, check, PDF/DOCX |
| Students & memory | `progress.py` — SQLite, sessions, reports |
| AI | Google Gemini (Live + text models via `.env`) |

**Run locally:**

```powershell
uvicorn fastapi_app:app --reload
# Open http://127.0.0.1:8000
```

**CLI voice only:** `python main.py`

---

## 3. Storage: SQLite vs JSON — speed & design

### Question

Should homework and student data be stored in **JSON files** instead of **SQLite** for faster loading?

### Answer (for SHIKSHA scale)

| Approach | Best for | Speed at your scale (tens–hundreds of students) |
|----------|----------|--------------------------------------------------|
| **SQLite** (current) | Students, sessions, homework logs, parent chat (to add), syllabus progress | **Very fast** (milliseconds). WAL mode + single connection already used. |
| **JSON files** | Static syllabus per class, image manifests, config | **Fast** when read once per lesson; **slow/risky** if one big file is rewritten on every update |
| **Hybrid (recommended)** | SQLite = changing data; JSON/folders = static curriculum + images | Best balance |

**Important:** Slowness users feel usually comes from **Gemini API calls**, not SQLite. A parent chat or live lesson waits on the network, not on reading 20 rows from a database.

### Recommendation

- **Keep SQLite** as source of truth for: students, live sessions, homework assigned/checked, parent messages, syllabus progress per student.
- **Use JSON** only for: `data/syllabus/jr_kg.json`, `class_1.json`, … and `data/syllabus/class_1/images/` + manifest.
- Keep `students_snapshot.json` as **export/backup**, not primary storage.

---

## 4. Parent conversation memory

### What you want

When a parent returns:

- SHIKSHA greets naturally: *"Hello, good to see you again…"*
- Remembers **last conversation** (topics, concerns, homework result).
- Knows **which subjects improved** and **where the child still struggles**.
- Suggests what **parents should focus on** at home.

### What the app does today (gap)

- Parent chat is stored in **server memory only** (`_SESSION["parent_chat"]` in `fastapi_app.py`).
- Loading a student in Parent corner **clears** chat.
- Only the **last ~8 messages** are sent to the AI during that browser session.
- **No durable parent chat table** in SQLite yet.

### What to build

1. **Table `parent_messages`** — `student_id`, `role`, `text`, `created_at`, optional attachment summary.
2. **Field `parent_summary` on student** — rolling short memory updated after chats:
   - Last topics discussed  
   - Parent concerns  
   - Strengths / weak subjects  
   - Last homework check outcome  
   - Recommended focus at home  
3. **Prompt at start of parent chat** — inject summary + last 3–5 messages so replies feel continuous, without sending full history every time (saves tokens).

Child **live session** memory already exists via `sessions` table in `progress.py`; parent side needs the same care.

---

## 5. Class dropdown, syllabus, and RAG

### Idea

- Dropdown: **Jr KG, Sr KG, Class 1 … Class 5/6** (and beyond later).
- SHIKSHA knows the **standard** → loads **syllabus** for that class.
- Tracks per student: **covered**, **pending**, **next topic**, **weak subjects**.
- **RAG** retrieves only relevant syllabus chunks for live lesson, homework, and parent chat.

### Architecture (simple → advanced)

**Phase 1 (no vector DB):**

- One JSON file per class: topics, order, teaching hints, image file names.
- Filter by `student.grade` → inject current + next 3 topics into system prompt.

**Phase 2:**

- Table `syllabus_progress`: `student_id`, `topic_id`, `status` (pending / in_progress / done).
- Optional embeddings + small local index when syllabus is large.

### Why this is good for MVP+

- SHIKSHA stops asking *"what did we study?"* every time — she **knows the curriculum path**.
- Homework aligns with **what the class should cover**, not random topics.
- Parents see **structured progress** (math 70%, English needs work, etc.).

---

## 6. Images & mini teaching screen

### Idea

- Syllabus includes images (e.g. ABCD, number charts, science diagrams).
- **Mini screen** in UI shows the current image while SHIKSHA teaches.
- Multiple images per topic (carousel / next page).
- SHIKSHA knows **which page** is on screen.

### Best approach (recommended)

| Do | Don't |
|----|--------|
| **Curated local images** under `data/syllabus/class_X/images/` | Fetch random images from internet during class |
| **manifest.json** per topic: `topic_id`, `pages[]`, `caption`, `file` | Send full image stream every second to Live API |
| UI shows image; **prompt** tells model the caption/topic | Depend on unstable URLs |

**Optional later:** Use Gemini multimodal for **homework photo check** (already partially there) — different from syllabus slideshow.

**Internet images:** Use only in **admin/build** step to download into your pack once, not at runtime for kids (safety, copyright, offline, speed).

### Live lesson flow

```
Child voice ←→ Gemini Live
     +
UI mini screen ← local image for current_topic_id
     +
Prompt includes: "Child sees: A for Apple (image page 1)"
```

---

## 7. Task board, chat board, and charts

| Feature | User | Purpose |
|---------|------|---------|
| Live class | Child | Teach, assign homework verbally |
| Homework board | Child / parent | Tasks, submit, AI check |
| Parent chat | Parent | Progress, concerns, natural dialogue |
| **Task board (new)** | Parent / teacher | Action items: "Practice Hindi 10 min daily", "Talk to school about math" |
| **Progress chart (new)** | Parent | Simple bars: subject progress from sessions + checks + syllabus |

Parent chat can **create tasks** from conversation → saved to task board.

---

## 8. Similar projects & references (internet research)

Use these to improve your MVP — none are identical to SHIKSHA, but pieces overlap.

### GitHub — closest feature overlap

| Project | Link | What to learn |
|---------|------|----------------|
| **MirrorBuddy** | https://github.com/FightTheStroke/MirrorBuddy | Voice tutors, homework help (photo), **parental dashboard**, progress — very close to your vision |
| **Magic Homework Buddy** | https://github.com/johnpole/magic-homework-buddy | **Gemini Live** + camera + voice for kids; real-time tutoring |
| **VisionAITutor** | https://github.com/WorldT0day/VisionAITutor | Gemini Live + camera homework + progress tracking |
| **Eduverse** | https://github.com/Kareem-007/Eduverse | Gemini Live + 3D avatar + live content panel |
| **AI Math Tutor** | https://github.com/maxpetrusenko/ai-math-tutor | FastAPI + voice stack, pluggable STT/LLM/TTS |
| **DeepTutor** | https://github.com/HKUDS/DeepTutor | Agent-native tutors, RAG, multi-user — scale ideas |
| **OpenTutor** | https://github.com/zijinz456/OpenTutor | Local-first, quizzes, flashcards, adaptive tutor |
| **VidyaAI** | https://github.com/yashkuceriya/vidyaai | **Indian languages**, NCERT, quiz, voice — strong India fit |
| **Sahayak Sikshak** | https://github.com/Muneerali199/sahayak-sikshak | Indian teachers, multilingual, grade content, charts |

### Products / articles (not always open source)

| Name | Link | Notes |
|------|------|-------|
| **Vidyaarthi.ai** | https://www.vidyaarthi.ai/ | Voice-native learning in mother tongue (Hindi, Tamil, etc.) |
| **KrishGuru AI** | https://aslearnix.ai/krishguru-ai/ | Offline-first, Hindi/English/regional, NCERT-aligned |
| **Udaan AI** (article) | https://dev.to/mr_spiky__/i-built-udaan-ai-a-multilingual-ai-mentor-for-indian-students-using-gemma-4-20h6 | Hinglish + career/education mentor pattern |
| **AULA** | https://dev.to/jpablortiz96/aula-the-ai-tutor-that-fits-in-a-browser-tab-built-for-the-students-the-internet-leaves-behind-253n | Browser-local tutor, voice, privacy — offline angle |
| **Gemini Live docs** | https://ai.google.dev/gemini-api/docs/live | Official reference for your voice stack |
| **Gemini 2.5 Flash Live** | https://cloud.google.com/gemini-enterprise-agent-platform/models/gemini/2-5-flash-live-api | Model capabilities (audio in/out, tools) |

### YouTube search terms (for tutorials & ideas)

Search on YouTube:

- `Gemini Live API tutorial Python`
- `AI tutor for kids homework`
- `build voice agent FastAPI Gemini`
- `NCERT AI tutor Hindi English`
- `Gemini Live Agent Challenge` (many demo projects like Magic Homework Buddy, Eduverse)

### How SHIKSHA can stand out

| Others often have | SHIKSHA differentiator |
|-------------------|-------------------------|
| Generic chat tutor | **Shiksha Di** persona: poems, stories, habits, guardian tone, Hinglish |
| English-only | Built for **Hinglish + Indian parent** flow |
| No parent report | **Report card + parent chat + student ID** |
| No class syllabus path | **Jr KG–Class 5 dropdown + RAG + local teaching images** (planned) |
| Cloud-only | Can stay **local FastAPI + SQLite** for privacy pilot |

---

## 9. Recommended build phases

| Phase | Work | Priority |
|-------|------|----------|
| **1** | Persist **parent chat** in SQLite + `parent_summary` | High |
| **2** | **Class dropdown** on register (Jr KG … Class 5/6) tied to `grade` | High |
| **3** | Static **syllabus JSON** per class + inject into live/parent prompts | High |
| **4** | **`syllabus_progress`** table per student | High |
| **5** | **Mini image panel** in UI + local image packs | Medium |
| **6** | Parent **task board** + simple **progress chart** | Medium |
| **7** | Per-browser **sessions** (fix single `_SESSION` for multi-user) | High before public deploy |
| **8** | RAG embeddings (only if syllabus JSON grows large) | Low later |
| **9** | Update README (FastAPI only, remove Streamlit refs) | Quick win |

---

## 10. Suggestions & opinions (author / AI assistant)

### Is the project good as-is?

**Yes for:** family demo, pilot with a few kids, portfolio, learning Gemini Live.  
**Not yet for:** many families on one public server without session isolation and basic privacy.

### Storage opinion

**Do not move runtime data to JSON for speed.** Use **SQLite + JSON syllabus packs**. That is the professional and still-fast pattern.

### Parent memory opinion

This is the **highest-value** feature after stable voice class. Parents will judge the product by *"does she remember my child?"*

### RAG + class dropdown opinion

**Strong yes.** It turns SHIKSHA from a generic chatbot into a **class-aware teacher**. Start with JSON syllabus, not a heavy vector DB.

### Images opinion

**Local curated packs only** for classroom teaching. Internet at lesson time = slow, unsafe, unreliable. Your mini-screen idea is **excellent** and matches how real teachers use charts.

### One LLM vs many agents opinion

Keep **Gemini Live for class** and **text model for homework/reports** for now. Add **MCP/agents** only when the codebase grows; not required for MVP.

### Competitive opinion

**MirrorBuddy** and **VidyaAI** are the best references to study. SHIKSHA wins on **persona + parent report + simple local deploy** if you finish parent memory and syllabus tracking.

### Cost opinion

Budget for **Live session minutes** separately from **text calls**. Voice will dominate cost if kids talk long.

---

# Part B — Hinglish (हिंदी + English — team / parents ke liye)

## 1. Project summary (संक्षेप)

**SHIKSHA** (Shiksha Di) bachchon ke liye **4–12 saal** ka AI teacher hai.

**Kya-kya karta hai:**

- **Live voice class** — bachcha mic se baat kare, SHIKSHA awaaz se jawab de (Gemini Live)
- **Homework** — task likho, sheet banao, PDF/Word download, upload karke check karwao
- **Har bachche ka ID** — jaise `S1`, `S2` — dubara aane par search karo
- **Parent corner** — naam ya ID se dhundho, progress dekho, report card, chat

**Target feel:** Jaise sachchi teacher — pyaar se, Hinglish, kavita, kahani, achhi aadatein, parent ko bhi update.

**Ab UI:** FastAPI + HTML page (`fastapi_app.py`, `templates/index.html`) — Streamlit hata diya gaya.  
**Data:** SQLite database (`data/shiksha.db`).

---

## 2. Abhi ka tech stack (short)

| Cheez | File |
|-------|------|
| Awaz / live class | `main.py` |
| Website | `fastapi_app.py` + `templates/index.html` |
| Homework | `homework.py` |
| Student + report | `progress.py` |

**Chalane ke liye:**

```powershell
uvicorn fastapi_app:app --reload
```

Browser: `http://127.0.0.1:8000`

---

## 3. SQLite vs JSON — speed ke liye kya sahi hai?

### Sawal

Kya homework aur student data **JSON file** mein rakhein taaki **jaldi load** ho?

### Seedha jawab

**Tumhare scale par (kam students) SQLite slow nahi karti.** Slow feel zyada tar **internet + Gemini API** ki wajah se hota hai.

| Storage | Kab use karo |
|---------|----------------|
| **SQLite** | Student, session, homework, parent chat, progress — **yahi main rakho** |
| **JSON** | Sirf **static syllabus** — Jr KG, Class 1 file, images ki list |
| **JSON snapshot** | Backup / dekhne ke liye — primary database mat banao |

**Meri salah:** Speed ke chakkar mein sab kuch JSON mat karo — **bug aur data loss** ka risk badhega. **SQLite + syllabus JSON** = best.

---

## 4. Parent ki baat yaad rakhna (bahut zaroori)

### Tum kya chahte ho

Parent dubara aaye to SHIKSHA bole:

- *"Namaste, phir mil kar achha laga…"*
- Pichli baat yaad ho — kis subject mein problem thi, homework kaisa tha
- Bataaye: kahan progress hai, kahan abhi bhi dikkat hai
- Ghar par **kya focus** karna chahiye

### Abhi app mein kya missing hai

- Parent chat **sirf memory mein** hai — page refresh / dubara load = **chat gayab**
- Database mein **parent messages save nahi** ho rahe (abhi)
- Isliye SHIKSHA har baar **nayi teacher** jaisi lag sakti hai parent ke liye

### Kya add karna chahiye

1. SQLite table: **parent_messages** (har message save)
2. Student par **parent_summary** — chhoti summary: last talk, weak subject, homework result
3. Nayi chat shuru karte waqt yeh summary + last 4-5 messages model ko do

**Bachche ki live class** ka history partly save ho raha hai — **parent ke liye bhi same chahiye.**

---

## 5. Class dropdown + syllabus + RAG

### Idea (bahut sahi hai)

- Dropdown: **Jr KG, Sr KG, Class 1 … Class 5/6**
- SHIKSHA ko pata ho **kis standard** ka bachcha hai
- **Syllabus** us class ka load ho
- Track: **kya padh liya**, **kya pending**, **agla topic kya**
- **RAG** = syllabus se sirf relevant hissa model ko bhejo (token bachta hai, focus better)

### Shuruat kaise karein (simple)

- Pehle: har class ki **ek JSON file** — topics ki list, order, chhoti teaching tip, image name
- Baad mein: bade syllabus ke liye embeddings / vector search

### Fayda

- Bachcha har baar "kal kya padha tha?" na bole — teacher **khud jaanti hai**
- Homework **class ke hisaab se** milega
- Parent ko clear dikhe: math theek, English weak, etc.

---

## 6. Teaching images + chhoti screen (mini screen)

### Idea

- Syllabus ke sath pictures — ABCD, numbers, diagrams
- Screen par **picture dikhe** jab SHIKSHA padhaye
- Kai images — next / previous
- SHIKSHA ko pata ho **kaunsi slide** ab dikh rahi hai

### Best approach

| ✅ Karo | ❌ Mat karo |
|--------|-----------|
| Images **project folder** mein rakho | Class ke time internet se random image |
| `data/syllabus/class_2/images/` | Har second poori image API ko bhejna |
| UI par chhoti screen | Bachchon ke liye unsafe / slow links |

**Internet se image:** sirf **ek baar download** karke pack banao — class ke time nahi.

**Example flow:** SHIKSHA bole *"Screen par dekho — A for Apple"* — aur UI par wahi picture ho.

---

## 7. Task board + chart

| Feature | Kaun use karega |
|---------|------------------|
| Live class | Bachcha |
| Homework board | Bachcha / parent |
| Parent chat | Parent |
| **Task board (naya)** | Parent — "roz 10 min Hindi", "teacher se math par baat" |
| **Chart (naya)** | Subject-wise progress — simple bar |

Parent chat se hi task ban sakta hai: *"SHIKSHA, is week Hindi par zor do"* → task board mein save.

---

## 8. Internet par similar projects — dekhne ke liye

### GitHub (open source — code dekh sakte ho)

| Project | Link | Kyon dekhein |
|---------|------|--------------|
| **MirrorBuddy** | https://github.com/FightTheStroke/MirrorBuddy | Voice tutor + homework photo + **parent dashboard** — SHIKSHA jaisa sabse kareeb |
| **Magic Homework Buddy** | https://github.com/johnpole/magic-homework-buddy | Gemini Live + camera + bachchon ke liye |
| **VisionAITutor** | https://github.com/WorldT0day/VisionAITutor | Live + homework + progress |
| **VidyaAI** | https://github.com/yashkuceriya/vidyaai | **Hindi/Indian**, NCERT, quiz, voice |
| **Sahayak Sikshak** | https://github.com/Muneerali199/sahayak-sikshak | Indian teacher tool, multilingual, grade content |
| **DeepTutor** | https://github.com/HKUDS/DeepTutor | Agents + RAG — bade scale ke ideas |
| **AI Math Tutor** | https://github.com/maxpetrusenko/ai-math-tutor | FastAPI voice architecture |

### Websites / articles

| Naam | Link |
|------|------|
| Vidyaarthi.ai | https://www.vidyaarthi.ai/ — mother tongue voice learning |
| KrishGuru AI | https://aslearnix.ai/krishguru-ai/ — offline, Hindi/English |
| Udaan AI (Hinglish mentor) | https://dev.to/mr_spiky__/i-built-udaan-ai-a-multilingual-ai-mentor-for-indian-students-using-gemma-4-20h6 |
| Gemini Live docs | https://ai.google.dev/gemini-api/docs/live |

### YouTube par search karo

- `Gemini Live API Python tutorial`
- `AI homework tutor kids`
- `Gemini Live Agent Challenge`
- `NCERT AI tutor Hindi`

### SHIKSHA alag kaise dikhe

- Sirf chat nahi — **Shiksha Di personality** (kahani, kavita, habits)
- **Parent report + ID + Hinglish parent chat**
- **Class-wise syllabus + local images** (plan) — zyada tar demos mein nahi milta

---

## 9. Build order (phase wise)

| Phase | Kaam | Priority |
|-------|------|----------|
| 1 | Parent chat **database** mein save + summary | ⭐⭐⭐ |
| 2 | Class dropdown (Jr KG … Class 5) | ⭐⭐⭐ |
| 3 | Syllabus JSON per class | ⭐⭐⭐ |
| 4 | Student ka syllabus progress | ⭐⭐⭐ |
| 5 | Mini screen + local images | ⭐⭐ |
| 6 | Task board + chart | ⭐⭐ |
| 7 | Har user ka alag session (public deploy se pehle) | ⭐⭐⭐ |
| 8 | README update (FastAPI instructions) | ⭐ |

---

## 10. Meri rai aur suggestions (opinion)

### Kya project abhi achha hai?

- **Haan** — ghar par demo, kuch bachchon ke sath pilot, GitHub portfolio ke liye
- **Abhi nahi** — bina login / session ke poori duniya ko ek server par mat kholo

### SQLite vs JSON

**JSON se speed nahi milegi** tumhare size par. **SQLite rakho** — professional aur safe.

### Sabse important agla step

**Parent ki conversation save karo** — parents yahi dekhenge: *"yeh meri beti ko jaanti hai ya nahi?"*

### Class + RAG + images

**Bahut sahi direction.** Pehle simple JSON syllabus, baad mein heavy RAG. Images **local pack** — mini screen idea **ekdum teacher jaisa**.

### Ek LLM vs agents

Abhi **Live + text model** kaafi hai. MCP/agents baad mein jab code bada ho.

### Dusre projects se kya seekhein

**MirrorBuddy** aur **VidyaAI** — in dono ko kholo, UI/flow note karo. SHIKSHA **persona + parent report + simple local app** se alag ho sakta hai.

### Paisa / API cost

**Live class** sabse zyada kharch karegi (awaaz + lamba session). Homework/report alag budget socho.

---

## Quick links

| Resource | URL |
|----------|-----|
| Your repo | https://github.com/pawarkiran3991/SHIKSHA |
| Gemini Live API | https://ai.google.dev/gemini-api/docs/live |

---

*Document created for SHIKSHA roadmap planning. Update as features ship.*
