# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Run the server:**
```bash
uvicorn main:app --reload
```

UV run uvicorn main:app

**Setup with uv (recommended):**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv if not already installed
uv sync                                             # install deps from pyproject.toml into .venv
source .venv/bin/activate                           # activate (Mac/Linux)
# .venv\Scripts\activate                           # activate (Windows)
```

**Install dependencies (pip fallback):**
```bash
pip install -r requirements.txt
```

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
│   └── music_model.py        # MusicCreate, MusicResponse, MusicType enum
├── routers/
│   ├── project_router.py     # POST /projects/, GET /projects/
│   └── music_router.py       # POST /music/
└── services/
    ├── project_service.py    # Supabase CRUD for projects table
    └── music_service.py      # MusicGPT API calls, polling, Supabase Storage upload
```

## Architecture

FastAPI backend for an AI music generation app using Supabase (database + file storage) and MusicGPT API for generation.

**Request flow:** `main.py` → `routers/` → `services/` → `supabase_client.py`

- `routers/` — HTTP routing only, delegates all logic to services
- `services/` — business logic as static methods; `music_service.py` also runs async background polling tasks
- `models/` — Pydantic models for request validation and API responses
- `supabase_client.py` — singleton client shared across all services

**Music generation flow:**
1. `POST /music/` calls MusicGPT `POST /MusicAI`, inserts 2 rows into `music_metadata` (one per `conversion_id`), returns immediately
2. Two `BackgroundTask`s poll MusicGPT `GET /byId` every 5s independently (max 120s before marking `FAILED`)
3. On `COMPLETED`: downloads MP3, uploads to Supabase Storage at `{BUCKET_NAME}/{project_id}/{task_id}/{conversion_id}.mp3`, updates metadata row with storage URL, title, duration, and generated lyrics

## Database

**`projects` table**
`id` (int), `project_name`, `created_by`, `created_at`, `updated_at`

**`music_metadata` table**
`id` (UUID), `project_id` (text), `user_name`, `user_email`, `type` (music/vocal/sfx/stem),
`task_id`, `conversion_id`, `status` (IN_QUEUE/COMPLETED/ERROR/FAILED),
`prompt`, `music_style`, `title`, `duration` (float), `audio_url`, `album_cover_path`,
`generated_lyrics`, `created_at`, `updated_at`

## Environment

Requires a `.env` file with:
```
SUPABASE_URL=...
SUPABASE_KEY=...
MUSICGPT_API_KEY=...
BUCKET_NAME=music-generated
```
