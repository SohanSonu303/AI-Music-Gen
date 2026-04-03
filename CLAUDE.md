# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

For installation, setup, and folder structure see [README.md](README.md).

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

**Inpaint flow:**
1. `POST /inpaint/inpaint` receives `id` (source `music_metadata` UUID) + inpaint params (including `audio_url`)
2. Fetches the source row to copy `project_id`, `user_name`, `user_email`, `type`
3. Calls MusicGPT `POST /inpaint` as `multipart/form-data` with `audio_url` passed as a string field (no file download); deletes no temp file
4. Inserts 2 new rows with `is_cloned = <source_id>`, returns immediately
5. Two `BackgroundTask`s poll MusicGPT `GET /byId` (`conversionType=INPAINT`) every 5s (same timeout as music generation)
6. On `COMPLETED`: same download + Supabase Storage upload as music generation, stored at `{BUCKET_NAME}/{user_id}/{task_id}/{conversion_id}.mp3`

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

**Quick idea generation flow:**
1. `POST /prompt/quick-idea` receives `user_id`, `user_name`, `prompt` (max 280 chars)
2. Calls OpenRouter API (`deepseek/deepseek-v3.2`) with a built-in system prompt instructing it to generate a concise music concept (mood, genre, tempo, hook) in ≤280 characters
3. Inserts one row into `user_prompts` with `is_lyrics=False`, `feature_type="quick_idea"`, and AI output stored in `prompt`

**Prompt enhancer flow:**
1. `POST /prompt/enhance` receives `user_id`, `user_name`, `prompt` (max 280 chars), and optional `master_prompt`
2. System prompt = user-provided `master_prompt` if given, otherwise loaded from `prompts/musicenhancerprompt.md`; the 280-char output constraint is always appended in code
3. Calls OpenRouter API (`deepseek/deepseek-v3.2`) to produce a rich, production-ready enhanced prompt
4. Inserts one row into `user_prompts` with `is_lyrics=False`, `feature_type="prompt_enhanced"`, and AI output stored in `prompt`

**Extend flow:**
1. `POST /extend/extend` receives `id` (source `music_metadata` UUID)
2. Fetches the source row — copies metadata, uses `prompt + music_style` as the combined prompt (truncated to 280 chars), `duration` as `extend_after`
3. Calls MusicGPT `POST /extend` as `multipart/form-data` with `audio_url` passed as a string field (no file download)
4. Inserts up to 2 new rows with `is_cloned = <source_id>`, returns immediately
5. Background poll tasks use `conversionType=EXTEND`; on `COMPLETED`: same download + Supabase Storage upload pattern

**Remix flow:**
1. `POST /music/remix` receives `id` (source `music_metadata` UUID), optional `prompt` (remix style description), optional `lyrics`, optional `gender`
2. Fetches the source row — if no `prompt` provided, falls back to `source["prompt"]`; validates `source["audio_url"]` is not null
3. Downloads audio from `source["audio_url"]` to a temp file, calls MusicGPT `POST /Remix` with `audio_file` upload (multipart/form-data), deletes temp file after call
4. Inserts 2 new rows with `is_cloned = <source_id>`, returns immediately
5. Two `BackgroundTask`s poll MusicGPT `GET /byId` (`conversionType=REMIX`) every 5s
6. On `COMPLETED`: same download + Supabase Storage upload as music generation

**Prompt validation (all generation endpoints):**
- `POST /music/generateMusic`, `POST /inpaint/inpaint`, `POST /prompt/quick-idea`, `POST /prompt/enhance` all return `422` if the input `prompt` exceeds 280 characters (MusicGPT limit)
- `music_service.py` also flattens multi-line prompts (joins `\n` with spaces) before sending to MusicGPT

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

**`user_prompts` table** (referenced in code as `lyrics_metadata`)
`id` (bigint), `user_id` (uuid), `user_name`, `prompt` (stores generated output — lyrics, idea, or enhanced prompt),
`is_lyrics` (bool — `true` for lyrics, `false` for quick idea / prompt enhanced),
`feature_type` (text, nullable — `null` for lyrics rows, `"quick_idea"` or `"prompt_enhanced"` for prompt feature rows),
`style`, `mood`, `theme`, `tone`, `created_at`

**`audio_separations` table**
`id` (UUID), `user_id` (UUID), `project_id` (text), `original_filename` (text),
`status` (PENDING/IN_PROGRESS/COMPLETED/FAILED), `vocals_url`, `drums_url`, `bass_url`, `other_url`,
`error_message` (nullable), `created_at`
