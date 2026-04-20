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

# To Stop Redis
brew services stop redis
```

---

### Step 5 — Environment variables

Create a `.env` file in the project root (see `.env.example` for a full template):
```
# Supabase
SUPABASE_URL=...
SUPABASE_KEY=<service-role-key>     # backend / Celery — bypasses RLS
SUPABASE_ANON_KEY=<anon-key>        # used for RLS-scoped client (future)

# Clerk auth
CLERK_JWKS_URL=https://<your-clerk-domain>/.well-known/jwks.json
CLERK_ISSUER=https://<your-clerk-domain>
CLERK_WEBHOOK_SECRET=whsec_...      # from Clerk dashboard → Webhooks

# APIs
MUSICGPT_API_KEY=...
OPENROUTER_API_KEY=...

# Storage
BUCKET_NAME=music-generated
SFX_BUCKET_NAME=sound-generated

# Redis / Celery
REDIS_URL=redis://localhost:6379/0

# Max parallel MusicGPT requests. Free plan = 1. Bump to 2–3 on a paid plan,
# then restart the Celery worker with matching --concurrency value (see Step 7).
MUSICGPT_MAX_PARALLEL=1

# Dev auth bypass — skips Clerk JWT verification on every request.
# get_current_user returns a hardcoded dev stub (id=00000000-…-0001, email=dev@localhost).
# Also skips token balance checks in audio_edit, auto_edit, reference_match, and podcast routers.
# Never set to true in production — anyone can call any endpoint without a token.
DEV_BYPASS_AUTH=false

# Mock mode — skips MusicGPT API, Redis/Celery, and Supabase DB entirely.
# /generateMusic returns hardcoded QUEUED tracks instantly.
# /download returns IN_PROGRESS for ~40s then COMPLETED with sample audio URLs.
# Set to false (or remove) to use the real pipeline.
IS_MOCK=false
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

## Features

### AIME — Automated AI Music Editor

Beat-accurate, AI-driven audio trimming to a target duration. Upload any MP3/WAV and AIME analyses its BPM, detects structural segments (intro/verse/build/chorus/peak/drop/bridge/outro), scores candidate trim windows, and uses a DeepSeek LLM agent to select the best musical window.

**Key capabilities:**
- **Natural language intent** — describe what you want ("punchy 30s drop for a DJ mix") and the AI auto-fills all parameters and finds the best matching section in one click
- **9 energy preferences** — `high_energy`, `climax`, `drop`, `chorus`, `verse`, `build`, `chill`, `outro`, `intro_heavy`
- **Strictness slider** — Musical (best-sounding window) ↔ Balanced ↔ Precise (exact duration hit)
- **Beat-synced crossfades** — crossfade length snapped to beat grid (½ beat / 1 beat / 2 beats / 1 bar)
- **Intelligent loop restructuring** — when target > source, LLM plans a musical segment arrangement (intro→verse→chorus→outro) instead of robotic tiling
- **Candidate comparison** — all 3 scored candidates shown with scores; manually override the AI pick with one click
- **A/B comparison** — toggle between original and trimmed audio with position sync and kept/removed region overlays
- **Preview before committing** — "Find Best Section" shows the AI suggestion on the waveform before any audio is encoded (~1–3s vs 5–15s for full trim)

**Endpoints:** `POST /auto-edit/analyze` · `POST /auto-edit/suggest` · `POST /auto-edit/preview` · `POST /auto-edit/trim` · `POST /auto-edit/save`

Test UI: `GET /test-edit/ui` → ✦ Auto Trim tab

---

### AI Analog Warmth

Adaptive DSP warmth processing — 7-stage pipeline (subsonic cleanup → de-harshness → body EQ → analog saturation → Moog LPF → compression → loudness match) with all parameters derived from spectral analysis of the source audio. Vocal mode available.

**Endpoints:** `POST /test-edit/warmth` · `POST /test-edit/warmth/analyze`

---

### AI Style Enhancer

6 genre presets (lofi / edm / cinematic / pop / chill / vintage) with dry/wet blend, stereo widening, and crest-factor-aware loudness matching.

**Endpoint:** `POST /test-edit/enhance` · `GET /test-edit/enhance/presets`

---

### Image-to-Song Generation

The `image-to-song` feature allows users to generate music based on an image. Users can upload an image file or provide an image URL, along with optional parameters like prompts, lyrics, and music style preferences. The generated music can be instrumental, vocal, or both.

---

## API Endpoints

### Image-to-Song Endpoint

**POST** `/image-to-song/generate`

#### Request Parameters (multipart/form-data):
Requires `Authorization: Bearer <clerk_jwt>` header. `user_id`/`user_name`/`user_email` come from the JWT — do not send them in the form.

- `project_id` (str, required)
- `image_url` (str, optional) — provide either this or `image_file`, not both
- `image_file` (file, optional)
- `prompt` (str, optional, max 300 chars)
- `lyrics` (str, optional, max 3000 chars)
- `make_instrumental` (bool, optional)
- `vocal_only` (bool, optional)
- `key` (str, optional)
- `bpm` (int, optional)
- `voice_id` (str, optional)
- `webhook_url` (str, optional)

#### Response:
- A list of `MusicResponse` objects containing metadata about the generated music.

#### Example:
```bash
curl -X POST http://localhost:8000/image-to-song/generate \
  -H "Authorization: Bearer <clerk_jwt>" \
  -F "project_id=12345" \
  -F "image_url=https://example.com/image.jpg" \
  -F "prompt=Generate a calm instrumental track" \
  -F "make_instrumental=true"
```

---

## Folder Structure

```
AI-Music-Gen/
├── main.py                   # FastAPI app entry point, registers all routers
├── celery_app.py             # Celery instance + queue config (musicgpt_album queue)
├── supabase_client.py        # Supabase singleton (service-role) client
├── pyproject.toml            # Project metadata and dependencies (uv)
├── requirements.txt          # pip-compatible dependency list
├── .env                      # Environment variables (gitignored)
├── .env.example              # Env var template with descriptions
├── mock_data/
│   ├── mock_state.py                        # In-memory task registry; tracks creation time per task_id for time-based progress simulation
│   ├── generate_music_response.json         # Template for POST /music/generateMusic mock response (2 QUEUED tracks)
│   ├── download_inprogress_response.json    # Template for GET /download/ while elapsed < 40s
│   └── download_completed_response.json     # Template for GET /download/ after 40s (COMPLETED + sample audio URLs)
├── .python-version           # Pins Python 3.12
├── thirdpartyapi.md          # MusicGPT API reference
├── sample_requests.md        # Example requests for all features
├── auth/
│   └── clerk_auth.py         # Clerk JWT verification, get_current_user dependency, get_scoped_supabase
├── config/
│   └── token_costs.py        # Token cost constants per feature
├── agents/
│   ├── album_agent.py        # LangGraph 4-node planning agent (analyze→plan→prompts→lyrics)
│   └── auto_edit_agent.py    # AIME: LangGraph window selector + LLM loop arrangement planner
├── migrations/
│   ├── 001_create_albums.sql               # albums + album_tracks tables
│   ├── 002_add_script_excerpt.sql
│   ├── 003_add_music_metadata_id_2.sql
│   ├── 004_add_musicgpt_task_id.sql
│   ├── 005_add_music_metadata_error_message.sql
│   ├── 006_create_auth_tables.sql          # users, subscriptions, token_balances, token_transactions
│   ├── 007_migrate_user_id_to_uuid.sql     # migrate string user_ids to UUIDs
│   └── 008_enable_rls.sql                  # Row Level Security on all user-owned tables
├── prompts/
│   ├── musicenhancerprompt.md
│   ├── album_script_analysis.md
│   ├── album_prompt_generation.md
│   └── album_lyrics_generation.md
├── tasks/
│   └── music_tasks.py        # Celery tasks: submit_and_poll_task + process_album_track_task
├── models/
│   ├── auth_model.py         # UserContext (JWT claims)
│   ├── project_model.py      # projectCreate, projectResponse
│   ├── music_model.py        # MusicCreate, InpaintCreate, MusicResponse, MusicType
│   ├── lyrics_model.py       # LyricsCreate, LyricsResponse
│   ├── separation_model.py   # SeparationResponse
│   ├── download_model.py     # DownloadTrack, DownloadResponse
│   ├── prompt_model.py       # QuickIdeaCreate, PromptEnhanceCreate, PromptResponse
│   ├── extend_model.py       # ExtendCreate
│   ├── remix_model.py        # RemixCreate
│   ├── image_to_song_model.py
│   ├── album_model.py        # AlbumCreate, AlbumApprove, AlbumResponse, AlbumTrackResponse, TrackUpdate, TrackReplanRequest
│   ├── sound_model.py        # SoundCreate, SoundResponse
│   └── auto_edit_model.py    # AutoTrimRequest, AutoTrimResponse, CandidateWindow, AudioAnalysis, SegmentInfo
├── routers/
│   ├── auth_router.py        # GET /auth/me, POST /auth/webhook/clerk
│   ├── payment_router.py     # GET /payment/plans, POST /payment/checkout, GET /payment/subscription, POST /payment/webhook/dodo
│   ├── project_router.py     # POST /projects/, GET /projects/
│   ├── music_router.py       # POST /music/generateMusic, POST /music/remix
│   ├── inpaint_router.py     # POST /inpaint/inpaint
│   ├── lyrics_router.py      # POST /lyrics/generate
│   ├── separation_router.py  # POST /separate/
│   ├── download_router.py    # GET /download/
│   ├── queue_router.py       # GET /queue/health
│   ├── prompt_router.py      # POST /prompt/quick-idea, POST /prompt/enhance
│   ├── sound_router.py       # POST /sound_generator/, GET /sound_generator/, GET /sound_generator/status
│   ├── image_to_song_router.py # POST /image-to-song/generate
│   ├── extend_router.py      # POST /extend/extend
│   ├── album_router.py       # POST /album/create, GET /album/user, GET /album/{id}, PUT /album/{id}/approve, GET /album/{id}/progress, PUT /album/{id}/tracks/{tid}/replan, PUT /album/{id}/tracks/{tid}/regenerate
│   ├── auto_edit_router.py   # POST /auto-edit/analyze|suggest|preview|trim|save
│   ├── mastering_router.py   # GET /mastering/platforms, POST /mastering/process, POST /mastering/save
│   ├── reference_match_router.py # POST /reference-match/analyze|process|vibe-prompt|save
│   ├── podcast_router.py     # POST /podcast/produce|save
│   ├── audio_edit_test_router.py # GET /test-edit/ui, POST /test-edit/cut|fade|loop|mix|overlay|split|eq|warmth|enhance|save
│   └── user_library_router.py # GET /library/
└── services/
    ├── project_service.py    # CRUD for projects (filtered by user_id)
    ├── music_service.py      # Pre-inserts QUEUED rows; ownership checks on inpaint/extend/remix
    ├── lyrics_service.py     # MusicGPT lyrics generation
    ├── separation_service.py # Demucs stem separation, Storage upload
    ├── download_service.py   # Fetch tracks by user_id + task_id
    ├── prompt_service.py     # OpenRouter calls for quick idea + prompt enhancer
    ├── sound_service.py      # Sound generation, polling, Storage upload
    ├── album_service.py      # Album CRUD, agent runner, Celery dispatch, completion monitor (ownership enforced)
    ├── token_service.py      # Token balance checks and debits
    ├── user_library_service.py # Aggregate all user content across tables
    ├── warmth_service.py     # AI Analog Warmth: 7-stage DSP pipeline
    ├── enhancer_service.py   # AI Style Enhancer: 6 genre presets
    └── auto_edit_service.py  # AIME: analyze, candidate scoring, trim, intelligent loop
```

---

## Notes

- The `image-to-song` feature uses the `MusicService.create_image_to_song` method to pre-insert metadata rows and queue tasks for processing.
- Validation ensures that either `image_url` or `image_file` is provided, but not both.
- The Celery worker processes the queued tasks and generates the music using the MusicGPT API.
- Ensure Redis and Celery are running for this feature to work.
