# AI-Music-Gen

FastAPI backend for an AI music generation app using Supabase (database + file storage) and MusicGPT API for generation.

---

## Installation & Setup

### Step 1 — Prerequisites

Install system dependencies before anything else.

**Python 3.12**
```bash
# macOS (Homebrew)
brew install python@3.12

# Ubuntu/Debian
sudo apt-get install python3.12 python3.12-venv
```

**ffmpeg** (required for stem separation audio conversion)
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Verify
ffmpeg -version
```

---

### Step 2 — Clone the repository

```bash
git clone <repo-url>
cd AI-Music-Gen
```

---

### Step 3 — Install Python dependencies

**Option A — uv (recommended)**
```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies into .venv
uv sync

# Activate the virtual environment
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\activate         # Windows
```

**Option B — pip fallback**
```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

---

### Step 4 — Install and start Redis

Celery uses Redis as its message broker.

```bash
# macOS (Homebrew)
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# Verify Redis is running
redis-cli ping   # should print PONG

# To Step Redis
brew services stop redis
```

---

### Step 5 — Environment variables

Create a `.env` file in the project root:
```
SUPABASE_URL=...
SUPABASE_KEY=...
MUSICGPT_API_KEY=...
BUCKET_NAME=music-generated
OPENROUTER_API_KEY=...
REDIS_URL=redis://localhost:6379/0

# Max parallel MusicGPT requests (applies to ALL generation: generateMusic, remix,
# inpaint, extend, image-to-song, and album tracks). Free plan = 1. Bump to 2 or 3 on a paid plan,
# then restart the Celery worker with the matching --concurrency value (see Step 7).
MUSICGPT_MAX_PARALLEL=1

# Optional: watchdog timeout in seconds to auto-fail jobs stuck in QUEUED
# (default 600 = 10 minutes)
MUSIC_QUEUE_STALE_SECONDS=600
```

---

### Step 6 — Run the FastAPI server

```bash
# With uv (no manual activation needed)
uv run uvicorn main:app --reload

# With activated venv
uvicorn main:app --reload
```

Server starts at `http://localhost:8000`
Interactive API docs at `http://localhost:8000/docs`

---

### Step 7 — Run the Celery worker

**All** MusicGPT submissions — `generateMusic`, `remix`, `inpaint`, `extend`, `image-to-song`, and album tracks — go through the Celery queue. This is what prevents `429 Too Many Parallel Requests` errors when multiple users are active at the same time.

Open a **second terminal tab** and run:

```bash
# Free plan — concurrency 1 (one MusicGPT request at a time)

# With uv
uv run celery -A celery_app worker -Q musicgpt_album --concurrency=1 --loglevel=info

# With activated venv
celery -A celery_app worker -Q musicgpt_album --concurrency=1 --loglevel=info
```

`--concurrency` = how many MusicGPT jobs run in parallel. Match it to `MUSICGPT_MAX_PARALLEL` in `.env`.

> **Upgrading your MusicGPT plan?**  
> Set `MUSICGPT_MAX_PARALLEL=2` (or higher) in `.env`, then restart the worker with `--concurrency=2`.

---

### How queuing works with multiple users

The API server is **always fast** — it never waits for MusicGPT. Here is the full lifecycle:

```
User A  ──POST /generateMusic──►  pre-insert rows (QUEUED)  ──► return task_id immediately
User B  ──POST /generateMusic──►  pre-insert rows (QUEUED)  ──► return task_id immediately
User C  ──POST /remix──────────►  pre-insert rows (QUEUED)  ──► return task_id immediately

Redis queue:  [ User A job ] [ User B job ] [ User C job ]
                    ↓
Celery worker (concurrency=1):
  picks User A → calls MusicGPT → rows = IN_QUEUE → polls → rows = COMPLETED
  picks User B → calls MusicGPT → rows = IN_QUEUE → polls → rows = COMPLETED
  picks User C → calls MusicGPT → rows = IN_QUEUE → polls → rows = COMPLETED
```

- Each user gets a **stable `task_id`** at request time and polls `GET /download/?user_id=...&task_id=...` independently
- Jobs from different users never interfere — each has its own DB rows and storage path (`{user_id}/{task_id}/...`)
- If `concurrency=1`: jobs run strictly one at a time (safe for free MusicGPT plan)
- If `concurrency=2`: two jobs run in parallel (requires paid plan that allows 2 parallel API calls)
- If the worker is down: jobs stay in Redis with `status=QUEUED` until the worker restarts — no data is lost

**Status lifecycle:**
```
QUEUED → (worker picks up) → IN_QUEUE → (MusicGPT completes) → COMPLETED
                                                              → FAILED (error or timeout)
```

---

### All processes that must be running

| Process | Command |
|---------|---------|
| FastAPI server | `uvicorn main:app --reload` |
| Celery worker | `celery -A celery_app worker -Q musicgpt_album --concurrency=1` |

Queue diagnostics:
`GET /queue/health` returns Redis connectivity + active Celery worker information.

> The Celery worker is **required** for all music generation features.  
> Without it, requests will be queued (`status=QUEUED`) but never processed.

---

## Folder Structure

```
AI-Music-Gen/
├── main.py                   # FastAPI app entry point, registers all routers
├── celery_app.py             # Celery instance + queue config (musicgpt_album queue)
├── supabase_client.py        # Supabase singleton client
├── pyproject.toml            # Project metadata and dependencies (uv)
├── requirements.txt          # pip-compatible dependency list
├── .env                      # Environment variables (gitignored)
├── .mcp.json                 # Supabase MCP server config (gitignored, contains PAT)
├── .python-version           # Pins Python 3.12
├── thirdpartyapi.md          # MusicGPT API reference
├── sample_requests.md        # Example request bodies for all features
├── agents/
│   └── album_agent.py        # LangGraph 4-node planning agent (analyze→plan→prompts→lyrics)
├── migrations/
│   ├── 001_create_albums.sql          # Creates albums + album_tracks tables
│   ├── 002_add_script_excerpt.sql     # Adds script_excerpt to album_tracks
│   ├── 003_add_music_metadata_id_2.sql # Adds music_metadata_id_2 to album_tracks
│   └── 004_add_musicgpt_task_id.sql   # Adds musicgpt_task_id to music_metadata
│   └── 005_add_music_metadata_error_message.sql # Adds error_message to music_metadata
├── prompts/
│   ├── musicenhancerprompt.md       # Default master prompt for prompt enhancer
│   ├── album_script_analysis.md     # System prompt: segment script into track sections
│   ├── album_prompt_generation.md   # System prompt: generate MusicGPT prompts per track
│   └── album_lyrics_generation.md   # System prompt: generate lyrics for vocal tracks
├── tasks/
│   ├── __init__.py
│   └── music_tasks.py        # Celery tasks: submit_and_poll_task (single-track) + process_album_track_task (album)
├── models/
│   ├── project_model.py      # ProjectCreate, ProjectResponse
│   ├── music_model.py        # MusicCreate, InpaintCreate, MusicResponse, MusicType enum
│   ├── lyrics_model.py       # LyricsCreate, LyricsResponse
│   ├── separation_model.py   # SeparationResponse
│   ├── download_model.py     # DownloadTrack, DownloadResponse
│   ├── prompt_model.py       # QuickIdeaCreate, PromptEnhanceCreate, PromptResponse
│   ├── extend_model.py       # ExtendCreate
│   ├── remix_model.py        # RemixCreate
│   ├── image_to_song_model.py # ImageToSongCreate
│   └── album_model.py        # AlbumCreate, AlbumApprove, AlbumResponse, AlbumTrackResponse, TrackUpdate, TrackReplanRequest
│   └── sound_model.py        # SoundCreate, SoundResponse
├── routers/
│   ├── project_router.py     # POST /projects/, GET /projects/
│   ├── music_router.py       # POST /music/generateMusic, POST /music/remix
│   ├── inpaint_router.py     # POST /inpaint/inpaint
│   ├── lyrics_router.py      # POST /lyrics/generate
│   ├── separation_router.py  # POST /separate/
│   ├── download_router.py    # GET /download/
│   ├── queue_router.py       # GET /queue/health
│   ├── prompt_router.py      # POST /prompt/quick-idea, POST /prompt/enhance
│   └── sound_router.py       # POST /sound_generator/, GET /sound_generator/, GET /sound_generator/status
│   ├── image_to_song_router.py # POST /image-to-song/generate
│   ├── extend_router.py      # POST /extend/extend
│   └── album_router.py       # POST /album/create, GET /album/{id}, PUT /album/{id}/approve, GET /album/{id}/progress, PUT /album/{id}/tracks/{tid}/replan, PUT /album/{id}/tracks/{tid}/regenerate
└── services/
    ├── project_service.py    # Supabase CRUD for projects table
    ├── music_service.py      # Pre-inserts QUEUED music_metadata rows; returns records + Celery params
    ├── lyrics_service.py     # MusicGPT lyrics generation, Supabase insert
    ├── separation_service.py # Demucs stem separation, local cleanup, Supabase Storage upload
    ├── download_service.py   # Fetch both music tracks by user_id + task_id from music_metadata
    ├── prompt_service.py     # OpenRouter (DeepSeek) calls for quick idea + prompt enhancer
    └── sound_service.py      # Sound generation, polling, and Supabase Storage upload
    └── album_service.py      # Album CRUD, LangGraph agent runner, Celery task dispatch, completion monitor
```
