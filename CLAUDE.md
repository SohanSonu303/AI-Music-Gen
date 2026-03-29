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
│   ├── music_model.py        # MusicCreate, MusicResponse, MusicType enum
│   └── lyrics_model.py       # LyricsCreate, LyricsResponse
├── routers/
│   ├── project_router.py     # POST /projects/, GET /projects/
│   ├── music_router.py       # POST /music/generateMusic
│   ├── inpaint_router.py     # POST /inpaint/inpaint
│   └── lyrics_router.py      # POST /lyrics/generate
└── services/
    ├── project_service.py    # Supabase CRUD for projects table
    ├── music_service.py      # MusicGPT API calls, polling, Supabase Storage upload
    └── lyrics_service.py     # MusicGPT lyrics generation, Supabase insert
```

## Architecture

FastAPI backend for an AI music generation app using Supabase (database + file storage) and MusicGPT API for generation.

**Request flow:** `main.py` → `routers/` → `services/` → `supabase_client.py`

- `routers/` — HTTP routing only, delegates all logic to services
- `services/` — business logic as static methods; `music_service.py` also runs async background polling tasks
- `models/` — Pydantic models for request validation and API responses
- `supabase_client.py` — singleton client shared across all services

**Music generation flow:**
1. `POST /music/generateMusic` calls MusicGPT `POST /MusicAI`, inserts 2 rows into `music_metadata` (one per `conversion_id`), returns immediately
2. Two `BackgroundTask`s poll MusicGPT `GET /byId` (`conversionType=MUSIC_AI`) every 5s independently (max 120s before marking `FAILED`)
3. On `COMPLETED`: downloads MP3, uploads to Supabase Storage at `{BUCKET_NAME}/{user_id}/{task_id}/{conversion_id}.mp3`, updates metadata row with storage URL, title, duration, and generated lyrics

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

## Environment

Requires a `.env` file with:
```
SUPABASE_URL=...
SUPABASE_KEY=...
MUSICGPT_API_KEY=...
BUCKET_NAME=music-generated
```
