# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

For installation, setup, and folder structure see [README.md](README.md).

---

## Architecture

FastAPI backend for an AI music generation app using Supabase (database + file storage) and MusicGPT API for generation.

**Request flow:** `main.py` → `routers/` → `services/` → `supabase_client.py`

- `routers/` — HTTP routing only, delegates logic to services and enqueues Celery tasks
- `services/` — business logic as static methods; `music_service.py` pre-inserts QUEUED records and returns `(records, celery_params)` tuples; `separation_service.py` runs sync background processing via `BackgroundTasks`; `album_service.py` dispatches Celery tasks for album generation; `warmth_service.py` contains the full AI Analog Warmth DSP pipeline (spectral analysis, adaptive parameter engine, 7-stage processing, vocal mode); `enhancer_service.py` contains the AI Style Enhancer preset engine (6 genre presets, stereo widening, dry/wet blend, loudness match)
- `models/` — Pydantic models for request validation and API responses
- `agents/` — LangGraph agents; `album_agent.py` is a 4-node planning graph (analyze → plan → prompts → lyrics); `auto_edit_agent.py` is a single-node window selector + loop arrangement planner for AIME
- `tasks/` — Celery tasks; `music_tasks.py` contains `submit_and_poll_task` (all single-track operations) and `process_album_track_task` (album tracks)
- `celery_app.py` — Celery instance with one queue: `musicgpt_album` (concurrency = `MUSICGPT_MAX_PARALLEL`)
- `supabase_client.py` — singleton client shared across all services

For full user flow diagrams, sequence flows, and file responsibility breakdown see [userflow.md](userflow.md).

---

## AI Audio Feature Highlights

**AI Analog Warmth** — Fixes the cold, metallic "AI music" sound by running a 7-stage adaptive DSP pipeline (spectral analysis → de-harshness → body EQ → tube saturation → Moog LPF → compression → loudness match) that makes AI-generated tracks feel like they were mixed on real analog gear. *Marketing: "Turn your AI-generated music from digital and harsh into warm, tape-saturated, and production-ready — in one click."*

**AI Style Enhancer** — Applies a genre-matched mastering chain (6 presets: Lo-Fi, EDM, Cinematic, Pop, Chill, Vintage) to colour and shape audio without destroying the original — intensity slider controls dry/wet blend so users go from subtle polish to full genre transformation. *Marketing: "Give your track the sonic identity of a professional genre — lo-fi bedroom vibes, club-ready EDM punch, or cinematic grandeur — instantly."*

**AIME (Automated AI Music Editor / Auto Trim)** — Detects BPM, segments the track structurally (intro/verse/chorus/drop etc.), scores candidate windows by energy and musical quality, then uses an LLM to pick the best section and loop it to any target duration with beat-synced crossfades. *Marketing: "Tell it 'give me a punchy 30-second drop' and it finds, trims, and loops the perfect section of your track — automatically."*

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

**Sound generation flow:**
1. `POST /sound_generator/` validates `user_id`, calls MusicGPT `POST /sound_generator`, inserts 1 row into `sound_generations` with `type='sfx'`, returns immediately
2. One `BackgroundTask` polls MusicGPT `GET /byId` (`conversionType=SOUND_GENERATOR`) every 5s independently
3. On `COMPLETED`: downloads the generated audio, uploads it to Supabase Storage at `{SFX_BUCKET_NAME}/{user_id}/{task_id}/{conversion_id}.mp3` or `.wav`, and updates the `sound_generations` row with the public storage URL
4. `GET /sound_generator/?user_id=<id>&task_id=<id>` fetches the persisted SFX row from `sound_generations`
5. `GET /sound_generator/status?user_id=<id>&task_id=<id>` returns a debug payload (`is_completed`, `has_audio`, `ready_for_download`, and `error_message`) for quick troubleshooting

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

**Audio editing flow:**
1. `GET /test-edit/ui` serves `audio_edit_test.html` — test UI with WaveSurfer.js waveform display
2. All edit endpoints (`POST /test-edit/{op}`) accept source audio as either a URL (`url` form field, downloaded via httpx) or file upload (`file` form field)
3. Audio is decoded once to numpy float32 `(channels, samples)` via `pedalboard.io.AudioFile`, all operations run on the array, encoded once to MP3 (`quality="V0"`) or WAV on output — no intermediate files
4. Operations: `cut` (array slice), `fade` (linspace multiply), `loop` (np.tile), `split` (returns part 1), `mix` (pad + clip add), `overlay` (add at position), `eq` (`PeakFilter`)
5. `POST /test-edit/save` — receives the already-processed audio blob from the browser (no re-processing), uploads to Supabase Storage at `{user_id}/{project_id}/{uuid}.{fmt}`, inserts one `editing_table` row, returns `{ id, output_url, output_duration }`
6. Router: `routers/audio_edit_test_router.py`, prefix `/test-edit`, tags `["Audio Edit Testing"]`
7. Libraries: `pedalboard` (AudioFile I/O, PeakFilter), `numpy` (all array ops), `httpx` (URL download)

**AI Analog Warmth flow:**
1. `POST /test-edit/warmth` — accepts `file/url` + `intensity` (0.0–1.0, default 0.5) + `vocal_mode` (bool, default false) + `output_format`
2. Runs `apply_warmth(audio, sr, intensity, vocal_mode)` in threadpool (CPU-bound — keeps event loop free)
3. `apply_warmth` pipeline in `services/warmth_service.py`:
   - **Stage 0:** `analyze_spectrum()` — windowed FFT (8192, Hanning, 50% overlap), computes 6 band energies + 5 adaptive metrics (`harshness_ratio`, `spectral_tilt`, `crest_factor_db`, `mid_scoop_ratio`, `overall_rms_db`)
   - **`compute_warmth_params()`** — maps metrics + intensity → concrete DSP parameter dict; all EQ frequencies and gain values adapt to the track; fully different parameter set when `vocal_mode=True`
   - **Stage 1:** `HighpassFilter(30Hz)` — subsonic cleanup
   - **Stage 2:** `PeakFilter` x2 + `HighShelfFilter` — de-harshness; normal mode targets 3.5kHz + 7kHz (metallic sheen); vocal mode targets 5.5kHz + 8.5kHz (sibilance)
   - **Stage 3:** `LowShelfFilter` + `PeakFilter` — body; normal mode 200Hz + 800Hz; vocal mode 300Hz chest + 3kHz presence
   - **Stage 4:** `analog_saturate()` (numpy) — asymmetric tanh `x + asymmetry*(x²)` generates even harmonics (2nd, 4th); lighter drive in vocal mode
   - **Stage 5:** `LadderFilter(LPF24)` — Moog-style 24dB/oct HF rolloff; vocal mode uses higher cutoff (16–18kHz) to preserve breath
   - **Stage 5.5 (vocal mode only):** `Reverb(room_size, damping=0.8, wet=5–13%)` — small room reverb
   - **Stage 6:** `Compressor` — glue compression; vocal mode uses lower ratio (1.5:1–2.5:1) + faster attack
   - **Stage 7:** numpy RMS loudness match (output RMS corrected to input RMS) + `Limiter(-0.5 dBFS)`
4. `POST /test-edit/warmth/analyze` — runs `analyze_spectrum` + `compute_warmth_params`, returns JSON `{ spectral_profile, diagnostics, planned_adjustments, vocal_mode, summary }`
5. Save works via existing `POST /test-edit/save` with `operation="warmth"`
6. Libraries: `pedalboard` (`HighpassFilter`, `HighShelfFilter`, `LowShelfFilter`, `PeakFilter`, `LadderFilter`, `Compressor`, `Limiter`, `Reverb`, `Pedalboard`), `numpy` (FFT, saturation, loudness match)

**AI Style Enhancer flow:**
1. `GET /test-edit/enhance/presets` — returns 6 preset metadata objects `{ id, name, description, tags }` with no audio required
2. `POST /test-edit/enhance` — accepts `file/url` + `preset` (lofi/edm/cinematic/pop/chill/vintage) + `intensity` (0.0–1.0, default 0.7) + `output_format`
3. Runs `apply_preset(audio, sr, preset_id, intensity)` in threadpool; pipeline in `services/enhancer_service.py`:
   - Measures `input_rms`, `input_peak`, `input_crest` before processing
   - `dry = audio.copy()` — preserved for blending
   - Builds and applies a fresh `Pedalboard` chain from `PRESETS[preset_id]["chain_def"]`
   - **Stereo widening** (EDM/Cinematic/Pop only): numpy mid-side `mid=(L+R)/2`, `side=(L-R)/2*(1+width)`, recombine
   - **Analog saturation** (Vintage only): reuses `analog_saturate(drive=1.3, asymmetry=0.08)` from `warmth_service.py`
   - **Dry/wet blend**: `output = dry*(1-intensity) + processed*intensity`
   - Crest-factor-aware loudness match (same formula as warmth) + `Limiter(-0.5 dBFS)`
4. Save works via existing `POST /test-edit/save` with `operation="enhance"`
5. Preset DSP chains:
   - `lofi`: `HighpassFilter(80Hz)` + `LowShelf(200Hz,+2dB)` + `HighShelf(8kHz,-4dB)` + `Bitcrush(12bit)` + `Chorus` + `Reverb(small)` + `Compressor(3:1)`
   - `edm`: `HighpassFilter(40Hz)` + `PeakFilter(60Hz,+3dB)` + `PeakFilter(3.5kHz,+2dB)` + `HighShelf(12kHz,+2dB)` + stereo widen + `Compressor(4:1)` + `Limiter`
   - `cinematic`: `HighpassFilter(30Hz)` + `LowShelf(120Hz,+1.5dB)` + `PeakFilter(800Hz,-1dB)` + `HighShelf(10kHz,+1dB)` + `Reverb(hall,0.7)` + stereo widen + `Compressor(2:1 slow)`
   - `pop`: `HighpassFilter(60Hz)` + `PeakFilter(200Hz,-1.5dB)` + `PeakFilter(3kHz,+1.5dB)` + `HighShelf(10kHz,+2dB)` + stereo widen + `Compressor(3:1)` + `Limiter`
   - `chill`: `HighpassFilter(60Hz)` + `LowShelf(200Hz,+1dB)` + `HighShelf(8kHz,-2dB)` + `Chorus(slow)` + `Reverb(medium)` + `Compressor(2:1 slow)`
   - `vintage`: `HighpassFilter(50Hz)` + `LowShelf(150Hz,+2dB)` + `PeakFilter(3.5kHz,-1dB)` + `HighShelf(12kHz,-2dB)` + `analog_saturate` + `Compressor(2.5:1)` + `Reverb(small)`
6. Libraries: `pedalboard` (`Bitcrush`, `Chorus`, `Compressor`, `HighpassFilter`, `HighShelfFilter`, `LowShelfFilter`, `Limiter`, `PeakFilter`, `Reverb`, `Pedalboard`), `numpy` (stereo widening, dry/wet blend, loudness match)

**Stem separation flow:**
1. `POST /separate/` receives `user_id`, `project_id`, and an uploaded audio file (multipart/form-data)
2. Saves the upload to `inputs/`, inserts a `PENDING` row into `audio_separations`, returns immediately
3. A `BackgroundTask` converts the file to WAV (via ffmpeg if needed), runs `demucs` (`htdemucs` model) — status set to `IN_PROGRESS`
4. On success: uploads `vocals.wav`, `drums.wav`, `bass.wav`, `other.wav` to Supabase Storage at `{user_id}/{project_id}/{job_id}/{stem}.wav`, updates row with public URLs and `COMPLETED`
5. On failure: sets status to `FAILED` with `error_message`
6. Cleanup: always deletes only this job's input file, converted WAV, and demucs output subfolder — `inputs/` and `outputs/` root folders are never removed (safe for concurrent jobs)

**AIME (Automated AI Music Editor) flow:**

Router: `routers/auto_edit_router.py`, prefix `/auto-edit`, tags `["Auto Edit"]`
Service: `services/auto_edit_service.py`
Agent: `agents/auto_edit_agent.py` (LangGraph single-node window selector + loop arrangement planner)
Models: `models/auto_edit_model.py` (`AutoTrimRequest`, `AutoTrimResponse`, `CandidateWindow`, `AudioAnalysis`, `SegmentInfo`)
UI: `audio_edit_test.html` (✦ Auto Trim tab, served via `GET /test-edit/ui`)

**Endpoints:**
- `POST /auto-edit/analyze` — BPM detection, beat tracking, structural segment labeling; accepts optional `target_duration` + `energy_preference` + `strictness` to also score and return candidate trim windows (used for analyze-before-trim preview)
- `POST /auto-edit/suggest` — accepts a free-text `description` (e.g. "punchy 30s drop for a DJ mix"), calls LLM to infer and return `{target_duration, energy_preference, strictness, crossfade_beats, explanation}`; used by the "Auto-fill params" button
- `POST /auto-edit/preview` — analyze + LLM window selection with no audio encoding (~1–3s); returns `{bpm, segments, candidates, chosen_index, window_start, window_end, agent_reasoning}`; used by the "Find Best Section" button to show the AI suggestion before the user commits
- `POST /auto-edit/trim` — full pipeline: analyze → candidates → LLM/manual select → trim/loop → encode; returns JSON `{audio_b64, audio_format, bpm, window_start, window_end, actual_duration, beat_deviation_ms, was_looped, used_fallback, agent_reasoning, user_description, quality_warning, chosen_index, candidates}`; keeps `X-AIME-*` headers for backward compat
- `POST /auto-edit/save` — uploads trimmed audio blob to Supabase Storage, inserts `editing_table` row with `operation="auto_trim"`

**Analysis pipeline (`analyze_audio`):**
- BPM via `librosa.beat.beat_track`; downbeats inferred as every 4th beat (4/4 assumption)
- Structural segmentation via `librosa.segment.agglomerative` on MFCC
- **Spectral labeling** (`_label_segments`): multi-feature decision tree using chroma variance (`librosa.feature.chroma_cqt`), spectral contrast, onset density, and energy; 8 labels: `intro | verse | build | chorus | peak | drop | bridge | outro`; graceful fallback to energy-only v1 if spectral extraction fails

**Candidate scoring (`find_candidate_windows`):**
- Windows anchored to detected downbeats; duration tolerance = ±1 bar
- 4-axis weighted score: `duration × energy × structural × spectral_quality` (spectral fixed at 10%)
- **Strictness slider** (0.0–1.0) interpolates weight poles: Musical (18/36/36/10) ↔ Precise (72/9/9/10)
- **Spectral quality score** (`_spectral_quality_score`): crest factor, centroid stability, harshness ratio (2–5kHz); requires mono array
- **9 energy preferences**: `high_energy | climax | drop | chorus | verse | build | chill | outro | intro_heavy`; each maps to a label-overlap scoring strategy via `_label_overlap_score`

**LLM agent (`agents/auto_edit_agent.py`):**
- `select_window(candidates, energy_preference, user_description)` — LangGraph single-node graph; calls OpenRouter DeepSeek v3.2 via `_call_openrouter()`; short-circuits when 1 candidate; falls back to rank-0 on failure
- `plan_loop_arrangement(segments, target_duration)` — LLM arranges segment indices musically (intro→verse→chorus→outro pattern) to fill target duration when looping; algorithmic fallback

**Trim execution (`execute_trim`):**
- **Beat-synced crossfade**: `xfade_ms = crossfade_beats × (60/bpm) × 1000`, clamped 20–500ms
- **Intelligent loop** (`_intelligent_loop`): when `target > source` and ≥3 segments, stitches segments in LLM-planned arrangement order using overlap-add with beat-synced crossfades; falls back to `_loop_to_target` (simple tile)
- Logarithmic outro fade over last 1.5s; fade-in at trim start boundary
- Quality checks: beat deviation ms, click detection at cut point

**UI features (`audio_edit_test.html` — ✦ Auto Trim tab):**
- **Find Best Section**: user types plain-language intent → calls `/suggest` (infers params) → calls `/preview` (LLM selects window) → shows highlighted region on source waveform + AI reasoning + segment labels → "Apply This Trim" button posts `/trim` with `chosen_window_index` (skips LLM on second call)
- **Auto-fill params only**: calls `/suggest` alone, populates form fields without analyzing audio
- **Analyze Audio First**: calls `/analyze` with target duration, shows BPM badge + coloured segment timeline + 3 candidate cards as waveform regions
- **Candidate cards**: all 3 scored candidates shown after trim; AI-chosen highlighted green; "Use this" button on unchosen cards re-posts `/trim` with `chosen_window_index` (skips LLM, ~2× faster)
- **Strictness slider**: Musical ↔ Balanced ↔ Precise label; passed to both analyze and trim
- **Crossfade dropdown**: Half beat / 1 beat / 2 beats / 1 bar
- **A/B compare**: after trim, "A/B Compare" button toggles result waveform between trimmed audio and original; position-synced (trimmed pos ↔ original pos via `window_start` offset); original view shows green (kept) + red-tint (removed) region overlays
- **Metadata box**: BPM, window timestamps, actual duration, beat-deviation badge, loop/fallback badges, "You:" user description line (purple), "AI:" reasoning line, quality warnings
- **Segment timeline**: coloured blocks per label (intro=gray, verse=purple, build=amber, chorus=green, peak=emerald, drop=red, bridge=blue, outro=muted)

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

**`editing_table` table**
`id` (UUID), `user_id` (TEXT), `project_id` (TEXT),
`operation` (TEXT — `cut`/`split`/`fade`/`eq`/`loop`/`mix`/`overlay`/`warmth`/`enhance`),
`operation_params` (JSONB — operation-specific params e.g. `{start_ms, end_ms}`, `{intensity, vocal_mode}`, or `{preset, intensity}`),
`source_url` (TEXT — input audio URL or `"file_upload"`), `output_url` (TEXT — Supabase Storage public URL),
`output_format` (TEXT, default `'mp3'`), `output_duration` (FLOAT), `created_at` (TIMESTAMPTZ)
— only written when user explicitly clicks **Save to Cloud**; never written on preview/download

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

**`sound_generations` table**
`user_id`, `created_at`, `user_name`, `task_id`, `project_id`, `audio_url`, `type`,
`status`, `updated_at`, `error_message`, `conversion_id`