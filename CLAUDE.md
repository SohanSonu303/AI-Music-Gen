# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

### Step 4 — Environment variables

Create a `.env` file in the project root:
```
SUPABASE_URL=...
SUPABASE_KEY=...
MUSICGPT_API_KEY=...
BUCKET_NAME=music-generated
SFX_BUCKET_NAME=sfx
```

---

### Step 5 — Run the server

```bash
# With uv (no manual activation needed)
uv run uvicorn main:app --reload

# With activated venv
uvicorn main:app --reload
```

Server starts at `http://localhost:8000`
Interactive API docs at `http://localhost:8000/docs`

---

## Folder Structure

```
AI-Music-Gen/
├── main.py                   # FastAPI app entry point, registers all routers
├── supabase_client.py        # Supabase singleton client
├── pyproject.toml            # Project metadata and dependencies (uv)
├── requirements.txt          # pip-compatible dependency list
├── .env                      # Environment variables (gitignored)
├── .python-version           # Pins Python 3.12
├── thirdpartyapi.md          # MusicGPT API reference
├── sample_requests.md        # Example request bodies for different music styles
├── models/
│   ├── project_model.py      # projectCreate, projectResponse
│   ├── music_model.py        # MusicCreate, InpaintCreate, MusicResponse, MusicType enum
│   ├── lyrics_model.py       # LyricsCreate, LyricsResponse
│   ├── separation_model.py   # SeparationResponse
│   └── download_model.py     # DownloadTrack, DownloadResponse
├── routers/
│   ├── project_router.py     # POST /projects/, GET /projects/
│   ├── music_router.py       # POST /music/generateMusic
│   ├── inpaint_router.py     # POST /inpaint/inpaint
│   ├── lyrics_router.py      # POST /lyrics/generate
│   ├── separation_router.py  # POST /separate/
│   ├── download_router.py    # GET /download/
│   └── sound_router.py       # POST /sound_generator/, GET /sound_generator/, GET /sound_generator/status
└── services/
    ├── project_service.py    # Supabase CRUD for projects table
    ├── music_service.py      # MusicGPT API calls, polling, Supabase Storage upload
    ├── lyrics_service.py     # MusicGPT lyrics generation, Supabase insert
    ├── separation_service.py # Demucs stem separation, local cleanup, Supabase Storage upload
    ├── download_service.py   # Fetch generated audio assets by user_id + task_id from music_metadata
    └── sound_service.py      # MusicGPT SFX calls, polling, Supabase Storage upload
```

---

## Architecture

FastAPI backend for an AI music generation app using Supabase (database + file storage) and MusicGPT API for generation.

**Request flow:** `main.py` → `routers/` → `services/` → `supabase_client.py`

- `routers/` — HTTP routing only, delegates all logic to services
- `services/` — business logic as static methods; `music_service.py` runs async background polling tasks; `separation_service.py` runs sync background processing via `BackgroundTasks`
- `models/` — Pydantic models for request validation and API responses
- `supabase_client.py` — singleton client shared across all services

**Music generation flow:**
1. `POST /music/generateMusic` calls MusicGPT `POST /MusicAI`, inserts 2 rows into `music_metadata` (one per `conversion_id`), returns immediately
2. Two `BackgroundTask`s poll MusicGPT `GET /byId` (`conversionType=MUSIC_AI`) every 5s independently (max 120s before marking `FAILED`)
3. On `COMPLETED`: downloads MP3, uploads to Supabase Storage at `{BUCKET_NAME}/{user_id}/{task_id}/{conversion_id}.mp3`, updates metadata row with storage URL, title, duration, and generated lyrics

**Sound generation flow:**
1. `POST /sound_generator/` validates `user_id`, calls MusicGPT `POST /sound_generator`, inserts 1 row into `sound_generations` with `type='sfx'`, returns immediately
2. One `BackgroundTask` polls MusicGPT `GET /byId` (`conversionType=SOUND_GENERATOR`) every 5s independently
3. On `COMPLETED`: downloads the generated audio, uploads it to Supabase Storage at `{SFX_BUCKET_NAME}/{user_id}/{task_id}/{conversion_id}.mp3` or `.wav`, and updates the `sound_generations` row with the public storage URL
4. `GET /sound_generator/?user_id=<id>&task_id=<id>` fetches the persisted SFX row from `sound_generations`
5. `GET /sound_generator/status?user_id=<id>&task_id=<id>` returns a debug payload (`is_completed`, `has_audio`, `ready_for_download`, and `error_message`) for quick troubleshooting

**Inpaint flow:**
1. `POST /inpaint/inpaint` receives `id` (source `music_metadata` UUID) + inpaint params
2. Fetches the source row to copy `project_id`, `user_name`, `user_email`, `type`
3. Calls MusicGPT `POST /inpaint` (multipart/form-data), inserts 2 new rows with `is_cloned = <source_id>`, returns immediately
4. Two `BackgroundTask`s poll MusicGPT `GET /byId` (`conversionType=INPAINT`) every 5s (same timeout as music generation)
5. On `COMPLETED`: same download + Supabase Storage upload as music generation, stored at `{BUCKET_NAME}/{user_id}/{task_id}/{conversion_id}.mp3`

**Lyrics generation flow:**
1. `POST /lyrics/generate` receives `user_id`, `user_name`, `prompt`, and optional `style`, `mood`, `theme`, `tone`
2. Builds a combined prompt by concatenating all non-null context fields (`prompt + mood + style + theme + tone`)
3. Calls MusicGPT `GET /prompt_to_lyrics?prompt=<combined_prompt>` — synchronous, returns lyrics immediately (no polling)
4. Inserts one row into `lyrics_metadata` with `is_lyrics=True` and generated lyrics stored in the `prompt` column

**Download flow:**
1. `GET /download/?user_id=<id>&task_id=<id>` queries `music_metadata` for all rows matching both `user_id` and `task_id`
2. Returns both tracks (one per `conversion_id`) with their `status`, `audio_url`, `title`, `duration`, `album_cover_path`, and `generated_lyrics`
3. `audio_url` is the Supabase Storage public URL — only populated once polling completes with `COMPLETED` status; `null` while still `IN_QUEUE`
4. Returns 404 if no rows match; 500 on unexpected DB errors

**Stem separation flow:**
1. `POST /separate/` receives `user_id`, `project_id`, and an uploaded audio file (multipart/form-data)
2. Saves the upload to `inputs/`, inserts a `PENDING` row into `audio_separations`, returns immediately
3. A `BackgroundTask` converts the file to WAV (via ffmpeg if needed), runs `demucs` (`htdemucs` model) — status set to `IN_PROGRESS`
4. On success: uploads `vocals.wav`, `drums.wav`, `bass.wav`, `other.wav` to Supabase Storage at `{user_id}/{project_id}/{job_id}/{stem}.wav`, updates row with public URLs and `COMPLETED`
5. On failure: sets status to `FAILED` with `error_message`
6. Cleanup: always deletes only this job's input file, converted WAV, and demucs output subfolder — `inputs/` and `outputs/` root folders are never removed (safe for concurrent jobs)

---

## Database

**`projects` table**
`id` (int), `project_name`, `created_by`, `created_at`, `updated_at`

**`music_metadata` table**
`id` (UUID), `project_id` (text), `user_id` (text), `user_name`, `user_email`, `type` (music/vocal/sfx/stem),
`task_id`, `conversion_id`, `status` (IN_QUEUE/COMPLETED/ERROR/FAILED),
`prompt`, `music_style`, `title`, `duration` (float), `audio_url`, `album_cover_path`,
`generated_lyrics`, `is_cloned` (UUID, nullable — source row id when created via inpaint),
`created_at`, `updated_at`

**`lyrics_metadata` table**
`id` (bigint), `user_id` (uuid), `user_name`, `prompt` (stores generated lyrics output),
`is_lyrics` (bool, always `true` for this flow), `style`, `mood`, `theme`, `tone`,
`created_at`

**`audio_separations` table**
`id` (UUID), `user_id` (UUID), `project_id` (text), `original_filename` (text),
`status` (PENDING/IN_PROGRESS/COMPLETED/FAILED), `vocals_url`, `drums_url`, `bass_url`, `other_url`,
`error_message` (nullable), `created_at`


**`sound_generations` table**
`user_id`, `created_at`, `user_name`, `task_id`, `project_id`, `audio_url`, `type`,
`status`, `updated_at`, `error_message`, `conversion_id`
