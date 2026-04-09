For a production-grade FastAPI music editor on a 4 vCPU server, you need a stack that avoids memory exhaustion while maintaining low latency.

Here is the recommended tech stack and concurrency strategy.

## 1. The Core Tech Stack

| Component | Technology | Why? |
| :--- | :--- | :--- |
| **Framework** | **FastAPI** | High performance, native `async` support, and easy to containerize. |
| **Audio Engine** | **Pydub** or **ffmpeg-python** | Pydub is very "Pythonic" for fading/mixing. FFmpeg handles the heavy lifting. |
| **Task Queue** | **Celery** + **Redis** | **Crucial.** Audio processing is CPU-bound; you must move it out of the request thread. |
| **Package Manager**| **uv** | Since you used it for ACE-Step, it’s the fastest way to manage your heavy dependencies. |
| **Web Server** | **Gunicorn** + **Uvicorn** | Standard for production Python to handle multiple worker processes. |

---

## 2. Handling Concurrency for Multiple Users

On a 4 vCPU server, if you try to process multiple audio files inside the FastAPI endpoint itself, the server will "freeze" or time out because Python's **Global Interpreter Lock (GIL)** and CPU saturation will block the event loop.

### The Worker Pattern
Instead of processing immediately, follow this workflow:
1. **FastAPI** receives the request (e.g., "mix these two tracks").
2. **FastAPI** saves the files and pushes a "task" into **Redis**.
3. **FastAPI** immediately returns a `202 Accepted` with a `task_id`.
4. **Celery Workers** (the heavy lifters) pick up the task and run the FFmpeg commands.
5. **User** polls a status endpoint (e.g., `/status/{task_id}`) to see if the file is ready.

### Resource Tuning for 4 vCPUs
To prevent your 4 vCPU server from crashing under high load:
* **Worker Limit:** Set Celery to run only **3 or 4 concurrent tasks** (`--concurrency=3`). This ensures there is always 1 vCPU free for the API and OS tasks.
* **Prefork Pool:** Use the `prefork` pool in Celery to take advantage of multiple cores for CPU-bound audio mixing.

---

## 3. Libraries to Install

```bash
# Core API
uv add "fastapi" "uvicorn[standard]"

# Audio Processing (Requires ffmpeg installed on the OS)
uv add "pydub"

# Background Tasks
uv add "celery[redis]"
```

---

## 4. Implementation Logic (The "Smart" Mix)

Since you are used to Java's structured approach, you'll appreciate how `Pydub` handles the operations you asked for:

```python
from pydub import AudioSegment

def process_audio(file_path_1, file_path_2):
    # Load tracks (Note: This uses RAM)
    track1 = AudioSegment.from_file(file_path_1)
    track2 = AudioSegment.from_file(file_path_2)

    # Cut & Fade
    track1 = track1[:10000].fade_in(2000).fade_out(3000) # First 10 seconds
    
    # Mix (Overlay)
    combined = track1.overlay(track2)
    
    # Export
    combined.export("output.mp3", format="mp3")
```


## 5. Deployment Strategy
Since you are a **DevOps/SRE** engineer, I recommend a **Docker Compose** setup similar to your RiffGen project:
1. **Service A (FastAPI):** Handles uploads and metadata.
2. **Service B (Redis):** The message broker.
3. **Service C (Worker):** A container dedicated to `pydub`/`ffmpeg` processing.
4. **Volume:** A shared `/app/media` volume so the API can save the file and the Worker can read it.

**Pro Tip:** Since you mentioned using **Hetzner**, ensure you mount a **Snapshot** or a dedicated **Volume** if you expect to store many user uploads, as the local NVMe on a 4 vCPU instance can fill up quickly with raw audio files.

Are you planning to build this as a standalone microservice to support your other AI music projects?

---

## 6. Audio Editing Features — Step-by-Step TODO

### Operations to implement

Cut, Split, Fade (in/out), Equalization (EQ), Looping, Mix, Overlay

### Libraries & tools needed

| Library | Install | Purpose |
|---------|---------|---------|
| **pydub** | `uv add "pydub>=0.25.1"` | High-level audio manipulation — cut, split, fade, loop, mix, overlay |
| **ffmpeg** | Already installed (used by demucs/separation) | Backend engine for pydub + direct subprocess for EQ filters |
| **httpx** | Already installed | Download source audio files from Supabase Storage URLs |

### How each operation works

| Operation | Library | Code | What it does |
|-----------|---------|------|-------------|
| **Cut/Trim** | pydub | `audio[start_ms:end_ms]` | Extract a time range from the audio |
| **Split** | pydub | `part1 = audio[:split_ms]`<br>`part2 = audio[split_ms:]` | Split into two separate files at a timestamp |
| **Fade In** | pydub | `audio.fade_in(duration_ms)` | Gradual volume ramp up at the start |
| **Fade Out** | pydub | `audio.fade_out(duration_ms)` | Gradual volume ramp down at the end |
| **EQ** | ffmpeg | `ffmpeg -i in.mp3 -af "equalizer=f=1000:width_type=o:width=2:g=5" out.mp3` | Apply frequency band adjustments (pydub has no native EQ) |
| **Loop** | pydub | `audio * count` | Repeat the audio N times |
| **Mix** | pydub | `track1.overlay(track2)` | Layer two tracks on top of each other from the start |
| **Overlay** | pydub | `base.overlay(track2, position=ms)` | Place a second track at a specific position on the base |

### Step-by-step TODO

- [ ] **Step 1 — Install pydub**
  - Run `uv add "pydub>=0.25.1"`
  - Verify: `python -c "from pydub import AudioSegment; print('ok')"`
  - ffmpeg is already on the system (used by stem separation service)

- [ ] **Step 2 — Create database table**
  - New migration: `migrations/005_create_audio_edits.sql`
  - Table: `audio_edits` with columns:
    - `id` (UUID, PK)
    - `user_id` (TEXT)
    - `project_id` (TEXT)
    - `operation` (TEXT) — `'cut'`, `'split'`, `'fade'`, `'eq'`, `'loop'`, `'mix'`, `'overlay'`
    - `operation_params` (JSONB) — operation-specific parameters
    - `source_url` (TEXT) — input audio URL
    - `status` (TEXT) — `PENDING` / `IN_PROGRESS` / `COMPLETED` / `FAILED`
    - `output_url` (TEXT) — result audio URL
    - `output_url_2` (TEXT) — second output (split operation only)
    - `output_duration` (FLOAT)
    - `output_format` (TEXT, default `'mp3'`)
    - `error_message` (TEXT, nullable)
    - `created_at`, `updated_at`
  - Run migration in Supabase SQL editor

- [ ] **Step 3 — Create Pydantic models**
  - New file: `models/audio_edit_model.py`
  - Request models (all share `user_id`, `project_id`, `output_format`):
    - `CutRequest` — `audio_url`, `start_ms`, `end_ms`
    - `SplitRequest` — `audio_url`, `split_ms`
    - `FadeRequest` — `audio_url`, `fade_in_ms`, `fade_out_ms`
    - `EqRequest` — `audio_url`, `bands: list[EqBand]` (each band: `frequency`, `width`, `gain`)
    - `LoopRequest` — `audio_url`, `count`
    - `MixRequest` — `audio_url_1`, `audio_url_2`
    - `OverlayRequest` — `audio_url_1`, `audio_url_2`, `position_ms`, `gain_db`
  - Response model:
    - `AudioEditResponse` — `id`, `status`, `output_url`, `output_url_2`, `output_duration`, `error_message`, etc.
  - Validations:
    - `output_format` must be `"mp3"` or `"wav"`
    - Cut: `end_ms > start_ms >= 0`
    - Fade: at least one of `fade_in_ms` / `fade_out_ms` > 0
    - EQ: 1–10 bands, gain range -20 to +20 dB
    - Loop: `2 <= count <= 10`

- [ ] **Step 4 — Create service (background processor)**
  - New file: `services/audio_edit_service.py`
  - Follow the same pattern as `services/separation_service.py`
  - Single function: `process_audio_edit(job_id, operation, user_id, project_id, audio_urls, params, output_format)`
  - Must be a plain `def` (not `async def`) — FastAPI auto-threads it via BackgroundTasks
  - Processing flow:
    1. Update DB: `status = 'IN_PROGRESS'`
    2. Download source audio(s) from URL(s) to temp files via httpx
    3. Load into pydub: `AudioSegment.from_file(temp_path)`
    4. Apply the operation (see code examples in the table above)
    5. For EQ: use `subprocess.run(["ffmpeg", ...])` instead of pydub
    6. Export result: `result.export(tmp_output, format=output_format)`
    7. Upload to Supabase Storage at `{user_id}/{project_id}/{job_id}/edited_{operation}.{format}`
    8. Get public URL via `get_public_url()`
    9. Update DB: `status = 'COMPLETED'`, set `output_url`, `output_duration`
    10. For split: also upload part 2 and set `output_url_2`
  - Error handling: `except` → update DB `status = 'FAILED'`, `error_message = str(e)`
  - Cleanup: `finally` → remove all temp files (never delete directories)

- [ ] **Step 5 — Create router**
  - New file: `routers/audio_edit_router.py`
  - Follow the same pattern as `routers/separation_router.py`
  - Prefix: `/audio-edit`, Tags: `["Audio Editing"]`
  - POST endpoints (one per operation):
    - `POST /audio-edit/cut`
    - `POST /audio-edit/split`
    - `POST /audio-edit/fade`
    - `POST /audio-edit/eq`
    - `POST /audio-edit/loop`
    - `POST /audio-edit/mix`
    - `POST /audio-edit/overlay`
  - GET status endpoint:
    - `GET /audio-edit/status?user_id=...&job_id=...`
  - Each POST endpoint does:
    1. Validate request params
    2. Generate `job_id = str(uuid4())`
    3. Insert `PENDING` row into `audio_edits` via `run_in_threadpool`
    4. `background_tasks.add_task(process_audio_edit, ...)`
    5. Return the inserted record immediately

- [ ] **Step 6 — Register router in main.py**
  - Import `audio_edit_router` in `main.py`
  - Add `app.include_router(audio_edit_router.router)`

- [ ] **Step 7 — Test all endpoints**
  - Start server: `uvicorn main:app --reload`
  - Test each operation with curl using a valid Supabase audio URL
  - Poll `GET /audio-edit/status` until `COMPLETED`
  - Verify `output_url` returns playable audio
  - Test split returns both `output_url` and `output_url_2`
  - Test error cases: invalid timestamps, bad URL, out-of-range EQ gain

### Architecture note

Uses **FastAPI BackgroundTasks** (same pattern as stem separation), **NOT Celery**. These are fast local CPU operations (<5 seconds) — no external API polling needed. If high concurrency becomes an issue later, can migrate to a dedicated Celery queue.s