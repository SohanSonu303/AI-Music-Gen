# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

For installation, setup, and folder structure see [README.md](README.md).

---

## Architecture

FastAPI backend for an AI music generation app using Supabase (database + file storage) and MusicGPT API for generation.

**Request flow:** `main.py` → `routers/` → `services/` → `supabase_client.py`

- `routers/` — HTTP routing only, delegates logic to services and enqueues Celery tasks
- `services/` — business logic as static methods; `music_service.py` pre-inserts QUEUED records and returns `(records, celery_params)` tuples; `separation_service.py` runs sync background processing via `BackgroundTasks`; `album_service.py` dispatches Celery tasks for album generation
- `models/` — Pydantic models for request validation and API responses
- `agents/` — LangGraph agents; `album_agent.py` is a 4-node planning graph (analyze → plan → prompts → lyrics)
- `tasks/` — Celery tasks; `music_tasks.py` contains `submit_and_poll_task` (all single-track operations) and `process_album_track_task` (album tracks)
- `celery_app.py` — Celery instance with one queue: `musicgpt_album` (concurrency = `MUSICGPT_MAX_PARALLEL`)
- `supabase_client.py` — singleton client shared across all services

For full user flow diagrams, sequence flows, and file responsibility breakdown see [userflow.md](userflow.md).

---

**Music generation flow:**
1. `POST /music/generateMusic` pre-inserts 2 `music_metadata` rows with `status=QUEUED` and a stable UUID as `task_id`, returns them immediately to the client
2. Enqueues `submit_and_poll_task(operation="music", ...)` in Celery queue `musicgpt_album`
3. Celery task calls MusicGPT `POST /MusicAI`, updates rows with real `conversion_id` + `musicgpt_task_id`, sets `status=IN_QUEUE`
4. Polls MusicGPT `GET /byId` (`conversionType=MUSIC_AI`) every 5s (max 300s before marking `FAILED`)
5. On `COMPLETED`: downloads MP3, uploads to Supabase Storage at `{BUCKET_NAME}/{user_id}/{stable_task_id}/{conversion_id}.mp3`, updates row with storage URL, title, duration, and generated lyrics
6. Client polls `GET /download/?user_id=...&task_id=<stable_task_id>` to track progress

**Inpaint flow:**
1. `POST /inpaint/inpaint` receives `id` (source `music_metadata` UUID) + inpaint params (including `audio_url`)
2. Fetches the source row to copy `project_id`, `user_name`, `user_email`, `type`
3. Pre-inserts 1 or 2 `music_metadata` rows with `status=QUEUED`, returns them immediately
4. Enqueues `submit_and_poll_task(operation="inpaint", ...)` in Celery
5. Celery task calls MusicGPT `POST /inpaint` as `multipart/form-data` with `audio_url` as a string field; updates rows with real IDs + `status=IN_QUEUE`
6. Polls `GET /byId` (`conversionType=INPAINT`); on `COMPLETED`: same download + Storage upload pattern

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
2. Fetches the source row — validates `audio_url` and `duration`, builds combined prompt (`prompt + music_style`, ≤280 chars)
3. Pre-inserts 2 `music_metadata` rows with `status=QUEUED`, returns them immediately
4. Enqueues `submit_and_poll_task(operation="extend", ...)` with `source_audio_url`, `combined_prompt`, `extend_after`
5. Celery task calls MusicGPT `POST /extend` as `multipart/form-data`; updates rows + polls; `conversionType=EXTEND`

**Remix flow:**
1. `POST /music/remix` receives `id` (source `music_metadata` UUID), optional `prompt`, optional `lyrics`, optional `gender`
2. Fetches the source row — if no `prompt` provided, falls back to `source["prompt"]`; validates `source["audio_url"]` is not null
3. Pre-inserts 2 `music_metadata` rows with `status=QUEUED`, returns them immediately
4. Enqueues `submit_and_poll_task(operation="remix", ...)` with `source_audio_url`
5. Celery task downloads audio to temp file, calls MusicGPT `POST /Remix` (multipart/form-data), deletes temp file; updates rows + polls; `conversionType=REMIX`

**Prompt validation (all generation endpoints):**
- `POST /music/generateMusic`, `POST /inpaint/inpaint`, `POST /prompt/quick-idea`, `POST /prompt/enhance` all return `422` if the input `prompt` exceeds 280 characters (MusicGPT limit)
- `submit_and_poll_task` flattens multi-line prompts (joins whitespace with spaces) before sending to MusicGPT for the `music` operation

**Album generation flow:**
1. `POST /album/create` receives `project_id`, `user_id`, `user_name`, `user_email`, `script`, and track composition (`songs`, `background_scores`, `instrumentals`; total 1–20)
2. Inserts an `albums` row with `status=PLANNING`, returns immediately
3. A `BackgroundTask` runs the LangGraph agent (`agents/album_agent.py`) which executes 4 nodes in sequence via OpenRouter (DeepSeek v3.2); all LLM calls go through `_call_openrouter()` which has a 300s read timeout and auto-retries up to 3 times on `ReadTimeout`/`ConnectTimeout` (backoff: 5s, 10s, 15s):
   - `analyze_script` — segments the script into N sections, extracting `scene_summary`, `emotional_arc`, `key_themes`, `script_excerpt`
   - `plan_tracks` — assigns `track_type`, `suggested_style`, `suggested_mood`, `suggested_tempo`, `energy_level` per track; outputs `album_title` and `style_palette`
   - `generate_prompts` — generates MusicGPT-ready `prompt` (≤280 chars) and `music_style` per track; auto-retries prompts exceeding 280 chars
   - `generate_lyrics` — generates full lyrics for vocal (`song`) tracks only; non-fatal if it fails
4. On agent completion: inserts `album_tracks` rows and sets `albums.status=PLANNED`
5. Client polls `GET /album/{album_id}` until `status == PLANNED`
6. `PUT /album/{album_id}/approve` (optional `track_updates` edits) → sets `status=GENERATING`, enqueues one `process_album_track_task` Celery task per track (queue: `musicgpt_album`, concurrency=`MUSICGPT_MAX_PARALLEL`)
7. Each Celery task: calls MusicGPT `POST /MusicAI`, inserts 2 `music_metadata` rows (one per `conversion_id`), updates `album_tracks` with `task_id`, `music_metadata_id` (first conversion), and `music_metadata_id_2` (second conversion), then polls `GET /byId` until done, downloads and stores audio
8. A `BackgroundTask` completion monitor polls DB every 15s (max 600s), syncs `album_tracks.status` from `music_metadata.status`, sets `albums.status=COMPLETED` or `FAILED` when all tracks reach terminal state
9. Client polls `GET /album/{album_id}/progress` during generation; fetches final album via `GET /album/{album_id}`

**Album re-approve (retry failed tracks):**
- `PUT /album/{album_id}/approve` also works when `albums.status=FAILED`
- Only tracks NOT in `COMPLETED` status are re-submitted; already completed tracks are skipped

**Album per-track operations:**
- `PUT /album/{album_id}/tracks/{track_id}/replan` — re-runs AI prompt + lyrics for one track while album is `PLANNED`; optionally accepts `custom_script_excerpt` (≤500 chars) to re-derive scene context from a different script section
- `PUT /album/{album_id}/tracks/{track_id}/regenerate` — re-submits one track to MusicGPT after album is `GENERATING`/`COMPLETED`; sets track to `PENDING`, enqueues Celery task, re-arms completion monitor

**Celery queue and multi-user behaviour:**

All MusicGPT submissions — single-track (generateMusic, remix, inpaint, extend) and album tracks — go through a single Redis-backed Celery queue `musicgpt_album`. This is the mechanism that prevents `429 Too Many Parallel Requests` from MusicGPT.

How it handles multiple concurrent users:

1. **API response is always instant.** When any user hits a generation endpoint, the FastAPI server pre-inserts `music_metadata` rows with `status=QUEUED` and a stable UUID `task_id`, then returns those rows to the client in <100ms. The client immediately has a `task_id` to poll with. No user ever waits at the HTTP layer.

2. **All jobs line up in Redis.** `submit_and_poll_task` (or `process_album_track_task` for album tracks) is enqueued in Redis. If 10 users submit simultaneously, Redis holds 10 tasks in order.

3. **Celery worker processes N at a time.** The worker picks up tasks from the queue. `--concurrency=N` (= `MUSICGPT_MAX_PARALLEL`) controls how many MusicGPT API calls run simultaneously. On free plan: `N=1` (strictly serial). Paid plan: bump N accordingly.

4. **Each job is fully independent.** Each task carries its own `stable_task_id`, `record_ids`, and `user_id`. Jobs from different users do not interfere — they each update their own `music_metadata` rows and upload to their own storage paths (`{user_id}/{stable_task_id}/...`).

5. **Polling is always safe.** `GET /download/?user_id=...&task_id=...` is a simple DB read. Any user can poll at any time without affecting the queue. Status progresses: `QUEUED` → `IN_QUEUE` → `COMPLETED` / `FAILED`.

6. **Failure is isolated.** If one job fails (MusicGPT error, timeout), only that job's rows are marked `FAILED`. Other queued jobs continue normally.

Key identifiers:
- `music_metadata.task_id` = stable UUID pre-generated by us, returned to client immediately, used for `/download/` polling
- `music_metadata.musicgpt_task_id` = real task_id from MusicGPT response, used internally for `GET /byId` polling API calls
- For album tracks: `task_id == musicgpt_task_id` (inserted after MusicGPT responds, both hold the real ID)

`MUSICGPT_MAX_PARALLEL` env var (default `1`) = `--concurrency` passed to Celery worker; bump + restart worker when upgrading MusicGPT plan.
Worker command: `celery -A celery_app worker -Q musicgpt_album --concurrency=1 --loglevel=info`

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
`task_id` (stable UUID pre-generated before MusicGPT call — client uses this to poll via `/download/`),
`musicgpt_task_id` (text, nullable — real task_id from MusicGPT response, used for polling API; same as `task_id` for album tracks),
`conversion_id`, `status` (QUEUED/IN_QUEUE/COMPLETED/ERROR/FAILED),
`prompt`, `music_style`, `title`, `duration` (float), `audio_url`, `album_cover_path`,
`generated_lyrics`, `is_cloned` (UUID, nullable — source row id when created via inpaint/remix/extend),
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

**`albums` table**
`id` (UUID), `project_id` (text), `user_id` (text), `user_name`, `user_email`,
`title` (text, nullable — AI-suggested album title), `script` (text),
`num_songs` (int, 1–20 — total track count),
`track_composition` (text — JSON string: `{"songs":N,"background_scores":N,"instrumentals":N}`),
`status` (PLANNING/PLANNED/GENERATING/COMPLETED/FAILED),
`style_palette` (text, nullable — JSON string with `primary_genre`, `bpm_range`, `key_signature`, `instrumentation_family`, `mood_arc`),
`created_at`, `updated_at`

**`album_tracks` table**
`id` (UUID), `album_id` (UUID → albums.id CASCADE DELETE), `track_number` (int),
`track_type` (text: `song` / `background_score` / `instrumental`),
`scene_description` (text, nullable), `script_excerpt` (text, nullable — ≤500 chars of source script),
`suggested_style`, `suggested_mood`, `suggested_tempo`,
`prompt` (text — MusicGPT generation prompt ≤280 chars), `music_style`,
`lyrics` (text, nullable), `make_instrumental` (bool), `gender`, `output_length` (int),
`music_metadata_id` (UUID, nullable — first conversion's music_metadata row, set after generation starts),
`music_metadata_id_2` (UUID, nullable — second conversion's music_metadata row),
`task_id` (text, nullable), `status` (PENDING/IN_QUEUE/COMPLETED/FAILED/ERROR),
`energy_level` (int 1–10), `created_at`
