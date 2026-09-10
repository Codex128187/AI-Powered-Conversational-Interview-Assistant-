# AI Interview Assistant

A voice-to-voice mock-interview platform. Pick a subject, get interviewed by **Natalie** — a LangGraph agent (Gemini 2.5 Flash) whose speech is streamed to your browser in real time via Murf.ai Falcon TTS. Answer through your mic (WebM/Opus), get transcribed by AssemblyAI with speaker diarization, and receive a structured 1–5 feedback report after 5 adaptive rounds.

<p align="center">
  <img src="https://img.shields.io/badge/backend-Flask-000?logo=flask" alt="Flask"/>
  <img src="https://img.shields.io/badge/LLM-Gemini%202.5%20Flash-4285F4?logo=google" alt="Gemini"/>
  <img src="https://img.shields.io/badge/agent-LangGraph-1C3C3C" alt="LangGraph"/>
  <img src="https://img.shields.io/badge/TTS-Murf.ai%20Falcon-8b5cf6" alt="Murf.ai"/>
  <img src="https://img.shields.io/badge/STT-AssemblyAI-blue" alt="AssemblyAI"/>
  <img src="https://img.shields.io/badge/frontend-Vanilla%20JS%20+%20Tailwind-06B6D4?logo=tailwindcss" alt="Tailwind"/>
</p>

---

## How it works

1. **Pick a subject** — Self Introduction, Generative AI, Python, English, HTML, or CSS.
2. **Natalie opens.** The LangGraph agent generates a greeting + first question conditioned on the chosen subject. Murf.ai Falcon synthesises the voice and streams base64-encoded MP3 chunks over HTTP; the browser plays them via `MediaSource` as they arrive (no wait for the full clip).
3. **You answer.** The browser records audio as `audio/webm;codecs=opus` via `MediaRecorder`.
4. **Transcription.** The WebM blob is sent to `/submit-answer`, saved to a temp file, and transcribed by AssemblyAI with speaker labels.
5. **Adaptive follow-up.** The transcript is fed into the same LangGraph agent. Because `InMemorySaver` checkpoints every turn under a fixed `thread_id`, the agent sees the full conversation history — it acknowledges your real answer, adapts difficulty, and asks the next question.
6. **Repeat for 5 rounds.** After question 5 the agent sends a closing remark and sets `X-Interview-Complete: true`.
7. **Feedback.** `/get-feedback` pulls the full message history from the LangGraph checkpointer, prompts Gemini for a structured JSON evaluation, and returns `{ candidate_score: 1–5, feedback, areas_of_improvement }`. The frontend renders a circular score dial and the two text sections.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser  (Vanilla JS + Tailwind)                   │
│                                                     │
│  MediaRecorder ──► WebM/Opus blob ──► POST /submit  │
│  MediaSource  ◄── base64 MP3 chunks ◄── streaming   │
│  Score dial + feedback text ◄── JSON ◄── /feedback  │
└──────────────────────┬──────────────────────────────┘
                       │  HTTP
                       ▼
┌─────────────────────────────────────────────────────┐
│  Flask  (app.py, port 5000)                         │
│                                                     │
│  /start-interview ─┐                                │
│  /submit-answer  ──┤                                │
│                    ▼                                │
│            LangGraph agent ◄──► InMemorySaver       │
│            (Gemini 2.5 Flash)    (per-thread state) │
│                    │                                │
│        ┌───────────┴───────────┐                    │
│        ▼                       ▼                    │
│  Murf.ai Falcon TTS    AssemblyAI STT              │
│  (stream MP3 chunks)   (speaker-diarised)           │
│                                                     │
│  /get-feedback ──► read history ──► Gemini ──► JSON │
└─────────────────────────────────────────────────────┘
```

---

## Tech stack

| Layer | Choice | Role |
|---|---|---|
| LLM | Gemini 2.5 Flash (`langchain.chat_models.init_chat_model`) | Generates questions, adapts to answers, scores feedback |
| Agent framework | LangGraph `create_agent` + `InMemorySaver` | Multi-turn memory keyed by `thread_id`; zero manual context stitching |
| TTS | Murf.ai Falcon (`en-US-natalie`, 24 kHz MP3) | Low-latency streaming speech via `/v1/speech/stream` |
| STT | AssemblyAI (`speaker_labels=True`) | Speaker-diarised transcription of WebM/Opus recordings |
| Web server | Flask + flask-cors | Streaming responses via Python generators |
| Frontend | Vanilla JS, Tailwind CSS (CDN), Font Awesome | No build step — one HTML file, one JS file |
| Audio capture | `MediaRecorder` (`audio/webm;codecs=opus`) | Best cross-browser codec for shipping to a Python backend |
| Audio playback | `MediaSource` + `SourceBuffer("audio/mpeg")` | True streaming playback of chunked MP3 — plays while still downloading |

---

## Quick start

### Prerequisites

- Python 3.10+
- API keys for:
  - [Google AI Studio](https://aistudio.google.com/apikey) (Gemini)
  - [Murf.ai](https://murf.ai/api)
  - [AssemblyAI](https://www.assemblyai.com/)

### 1. Backend

```bash
cd backend

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Set your keys
cp .env.example .env
# Edit .env and paste real keys

python app.py
# → http://127.0.0.1:5000
```

### 2. Frontend

No build step — serve the static files any way you like:

```bash
cd frontend
python -m http.server 5500
# → open http://127.0.0.1:5500
```

Or just double-click `index.html`. CORS is enabled on the backend.

### 3. Use it

1. Pick a subject from the sidebar.
2. Click **Start Interview** — Natalie speaks the first question.
3. Click the mic button, answer, click again to stop recording, then click **Submit**.
4. Repeat for 5 rounds.
5. Click **Get Feedback** — see your score (1–5), feedback summary, and areas of improvement.

---

## API endpoints

| Method | Route | Request | Response |
|---|---|---|---|
| `POST` | `/start-interview` | `{ "subject": "Python" }` | Streaming `text/plain` — base64 MP3 chunks (one per line) |
| `POST` | `/submit-answer` | `multipart/form-data` with `audio` file (WebM) | Streaming `text/plain` — base64 MP3 chunks. Headers: `X-Question-Number`, `X-Interview-Complete` |
| `POST` | `/get-feedback` | `{}` | `{ "success": true, "feedback": { "candidate_score": 1-5, "subject": "...", "feedback": "...", "areas_of_improvement": "..." } }` |

---

## Project structure

```
ai-interview-assistant/
├── backend/
│   ├── app.py               # Flask server — 3 endpoints + LangGraph agent + TTS/STT
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example          # Template for API keys
│   └── .env                  # Your actual keys (git-ignored)
├── frontend/
│   ├── index.html            # UI shell — Tailwind + Font Awesome via CDN
│   └── index.js              # MediaRecorder + MediaSource + fetch orchestration
├── .gitignore
└── README.md
```

---

## How each endpoint works

### `/start-interview`

1. Resets `InMemorySaver` (fresh session) and `question_count = 1`.
2. Formats the system prompt with the chosen subject.
3. Invokes the LangGraph agent for the opening question.
4. Pipes the question text through `stream_audio()` → Murf.ai Falcon → base64 MP3 chunks → client.

### `/submit-answer`

1. Receives the WebM/Opus blob from `FormData`.
2. Saves to a temp file and transcribes via AssemblyAI (with `speaker_labels=True`).
3. Feeds the transcript into the same LangGraph agent (the `InMemorySaver` checkpointer auto-threads the full message history).
4. Increments `question_count`. If ≤ 5, generates the next question; if > 5, generates a closing remark.
5. Streams the response as Murf TTS, with `X-Question-Number` and `X-Interview-Complete` headers.

### `/get-feedback`

1. Calls `agent.get_state(config)` to pull the complete message history from the checkpointer.
2. Formats the history into a labelled transcript.
3. Sends a single-shot prompt to Gemini asking for JSON: `{ candidate_score, subject, feedback, areas_of_improvement }`.
4. Parses the JSON (with fallback if the model wraps it in markdown fences).
5. Returns `{ "success": true, "feedback": { ... } }`.

---

## Known limitations

- **Single-session only.** `thread_id = "interview_session"` is a constant — two concurrent users will overwrite each other's state. For multi-user support, generate a UUID per session and pass it from the frontend.
- **In-memory state.** `InMemorySaver` loses all data on server restart. Swap to `SqliteSaver` or `PostgresSaver` for persistence.
- **Flask dev server.** `app.run(debug=True)` is single-threaded. Use `gunicorn` with `--workers` for production.
- **No Murf error handling.** If the TTS API fails (key expired, rate limit), the frontend sees an empty stream and hangs.
- **AssemblyAI cold start.** Transcription takes 5–15 seconds depending on audio length — the user sees "Submitting..." during this wait.

---

## Environment variables

| Variable | Where to get it | Used by |
|---|---|---|
| `GOOGLE_API_KEY` | [aistudio.google.com](https://aistudio.google.com/apikey) | Gemini 2.5 Flash (question generation + feedback scoring) |
| `MURF_API_KEY` | [murf.ai/api](https://murf.ai/api) | Falcon TTS streaming |
| `ASSEMBLYAI_API_KEY` | [assemblyai.com](https://www.assemblyai.com/) | Speaker-diarised speech-to-text |

---

## License

MIT
