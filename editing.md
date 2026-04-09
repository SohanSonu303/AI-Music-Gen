For a production-grade FastAPI music editor on a 4 vCPU server, you need a stack that avoids memory exhaustion while maintaining low latency.

Here is the recommended tech stack and concurrency strategy.

## 1. The Core Tech Stack

| Component | Technology | Why? |
| :--- | :--- | :--- |
| **Framework** | **FastAPI** | High performance, native `async` support, and easy to containerize. |
| **Audio Engine** | **Pedalboard** (Spotify) + **numpy** | Lossless numpy pipeline, native EQ/filters, 4x faster reads, single MP3 encode. FFmpeg still available for edge cases. |
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
| **pedalboard** | `uv add "pedalboard"` | Spotify's C++/JUCE audio engine — lossless read/write, native EQ/filters, 4x faster |
| **numpy** | Included with pedalboard | All audio operations on float32 arrays — cut, fade, loop, mix, overlay |
| **ffmpeg** | Already installed (used by demucs/separation) | Fallback for edge cases only |
| **httpx** | Already installed | Download source audio files from Supabase Storage URLs |

### How each operation works

| Operation | Library | Code | What it does |
|-----------|---------|------|-------------|
| **Cut/Trim** | numpy | `audio[:, start_sample:end_sample]` | Extract a time range (lossless array slice) |
| **Split** | numpy | `part1 = audio[:, :split_sample]`<br>`part2 = audio[:, split_sample:]` | Split into two arrays at a sample index |
| **Fade In** | numpy | `audio[:, :n] *= np.linspace(0, 1, n)` | Linear volume ramp 0→100% over first N samples |
| **Fade Out** | numpy | `audio[:, -n:] *= np.linspace(1, 0, n)` | Linear volume ramp 100→0% over last N samples |
| **EQ** | pedalboard | `PeakFilter(cutoff_frequency_hz=1000, gain_db=5, q=1.41).process(audio, sr)` | Native parametric EQ — no ffmpeg subprocess |
| **Loop** | numpy | `np.tile(audio, (1, count))` | Repeat the audio N times (lossless tile) |
| **Mix** | numpy | `np.clip(padded_a1 + padded_a2, -1, 1)` | Add two arrays, clip to prevent clipping |
| **Overlay** | numpy | `base[:, pos:pos+len] += overlay; np.clip(...)` | Add overlay at sample position, clip |

### Step-by-step TODO

- [x] **Step 1 — Install pydub**
  - Run `uv add "pydub>=0.25.1"`
  - Verify: `python -c "from pydub import AudioSegment; print('ok')"`
  - ffmpeg is already on the system (used by stem separation service)

- [x] **Step 2 — Create test router**
  - Sub-steps:
    - [x] **Step 2.5 — Create test UI (HTML)**
      - New file: `audio_edit_test.html` in project root
      - Served at `GET /test-edit/ui` via `FileResponse` (no extra deps)
      - One card per operation (cut, fade, loop, split, mix, overlay, eq)
      - Each card: URL input OR file upload toggle, operation params, Run button, inline `<audio>` player
      - Dual-source cards (mix, overlay): two independent source selectors
      - JS: `fetch()` → `POST /test-edit/{op}` with `FormData` → `createObjectURL(blob)` → audio player
  - New file: `routers/audio_edit_test_router.py`
  - Prefix: `/test-edit`, Tags: `["Audio Edit Testing"]`
  - Synchronous GET endpoints — no DB, no BackgroundTasks, no Supabase uploads
  - Each endpoint: downloads audio from URL via httpx → applies operation inline → returns `StreamingResponse` (Content-Type: audio/mpeg)
  - Endpoints:
    - `GET /test-edit/cut?url=...&start_ms=0&end_ms=10000`
    - `GET /test-edit/fade?url=...&fade_in_ms=2000&fade_out_ms=3000`
    - `GET /test-edit/loop?url=...&count=3`
    - `GET /test-edit/mix?url1=...&url2=...`
    - `GET /test-edit/overlay?url1=...&url2=...&position_ms=5000`
    - `GET /test-edit/split?url=...&split_ms=15000` (returns part1 only)
    - `GET /test-edit/eq?url=...&freq=1000&gain=5`
  - Register in `main.py`
  - Test with curl: `curl "http://localhost:8000/test-edit/cut?url=<url>&start_ms=0&end_ms=10000" --output test_cut.mp3`
  - Validates: pydub importable, ffmpeg subprocess works, httpx download from Supabase works, output audio is not corrupted

- [x] **Step 3 — Switch to Pedalboard (lossless audio pipeline)**
  - Run `uv add pedalboard` — installs Spotify's C++/JUCE audio engine (v0.9.22)
  - Verify: `python -c "from pedalboard.io import AudioFile; from pedalboard import PeakFilter; print('ok')"`
  - Rewrite `routers/audio_edit_test_router.py` to use pedalboard + numpy instead of pydub
  - Pipeline: MP3 → decode once → numpy float32 `(channels, samples)` → all ops lossless → encode to MP3 once with `quality="V0"`
  - EQ now uses native `PeakFilter` — no more ffmpeg subprocess
  - Test all 7 operations via `GET /test-edit/ui`

- [x] **Step 4 — Create `editing_table` migration**
  - New migration: `migrations/005_create_editing_table.sql`
  - Table: `editing_table` — only populated when user explicitly clicks **Save** (not on every edit)
  - Columns:
    - `id` (UUID, PK, default `gen_random_uuid()`)
    - `user_id` (TEXT)
    - `project_id` (TEXT)
    - `operation` (TEXT) — `'cut'`, `'split'`, `'fade'`, `'eq'`, `'loop'`, `'mix'`, `'overlay'`
    - `operation_params` (JSONB) — operation-specific parameters
    - `source_url` (TEXT) — input audio URL
    - `output_url` (TEXT) — Supabase Storage public URL of saved result
    - `output_format` (TEXT, default `'mp3'`)
    - `output_duration` (FLOAT)
    - `created_at` (TIMESTAMPTZ, default `now()`)
  - Run migration in Supabase SQL editor

- [x] **Step 5 — Add Save endpoint to existing test router**
  - Add `POST /test-edit/save` to `routers/audio_edit_test_router.py`
  - Accepts: same FormData as edit endpoints (url or file upload + operation params) plus `user_id` (str), `project_id` (str), `operation` (str)
  - Flow:
    1. Re-run the edit operation inline (same pedalboard + numpy logic as existing endpoints)
    2. Upload result bytes to Supabase Storage at `{user_id}/{project_id}/{uuid4()}.{format}`
    3. Get public URL via `get_public_url()`
    4. Insert row into `editing_table` with metadata
    5. Return JSON `{ "id": ..., "output_url": ..., "output_duration": ... }`
  - No background tasks — all operations complete in <5s

- [x] **Step 6 — Update UI with Download + Save buttons**
  - Update `audio_edit_test.html`
  - Add global `user_id` and `project_id` text inputs at the top of the page (needed for Save)
  - After each operation runs and the audio player appears, show two action buttons:
    - **Download** — `<a download href="{blobUrl}">Download</a>` using the existing blob URL
    - **Save to Cloud** — calls `POST /test-edit/save` with the same FormData + `user_id`, `project_id`, `operation`; displays the returned `output_url` on success
  - Show save status inline (spinner → success with URL, or error message)

- [x] **Step 7 — AI Analog Warmth (Paid Feature)**
  - One-click feature that fixes AI music's "metallic sheen" and adds analog warmth character
  - **No new pip dependencies** — uses pedalboard plugins already installed (`Compressor`, `Limiter`, `LadderFilter`, `HighShelfFilter`, `LowShelfFilter`, `HighpassFilter`, `Gain`) + numpy FFT
  - Sub-steps:
    - [x] **Step 7a — Create `services/warmth_service.py`**
      - New file following existing router → service pattern
      - **`analyze_spectrum(audio, sr)`** — numpy FFT spectral analysis:
        - Windowed FFT (8192 window, Hanning, 50% overlap) on mono-mixed signal
        - Compute 6 band energies: Sub (20–60Hz), Bass (60–250Hz), LowMid (250–2kHz), HighMid (2–6kHz), Presence (6–12kHz), Air (12–20kHz)
        - Derive adaptive metrics:
          - `harshness_ratio` = (HighMid + Presence) / (LowMid + Bass) — drives de-harshness strength
          - `spectral_tilt` = regression slope across log-frequency bands — drives HF rolloff
          - `crest_factor` = peak/RMS in dB — drives saturation and compression amounts
          - `mid_scoop_ratio` = LowMid / (Bass + HighMid) — drives body boost
          - `overall_rms_db` = 20 * log10(RMS) — drives compression threshold
      - **`compute_warmth_params(analysis, intensity)`** — maps spectral metrics → adaptive DSP parameters, all scaled by intensity (0.0–1.0)
      - **`analog_saturate(audio, drive, asymmetry)`** — even-harmonic saturation via asymmetric tanh:
        - `x = audio * drive; x = x + asymmetry * (x ** 2); result = np.tanh(x)` — generates 2nd/4th harmonics (tube/tape character)
        - Remove DC offset from asymmetry, normalize output
        - `drive` = 1.1–1.8 normal / 1.1–1.5 vocal (scaled by intensity, inversely by crest_factor)
        - `asymmetry` = 0.05–0.15 (subtle even harmonics — the actual "analog warmth")
      - **`apply_warmth(audio, sr, intensity=0.5)`** — 7-stage adaptive pipeline:
        - **Stage 1: Subsonic Cleanup** — `HighpassFilter(30Hz)`, fixed, removes DC + sub-rumble
        - **Stage 2: Adaptive De-harshness** — `PeakFilter(3.5kHz, -1 to -4 dB)` + `PeakFilter(7kHz, -0.5 to -3 dB)` + `HighShelfFilter(10kHz, -0.5 to -2.5 dB)`, all scaled by harshness_ratio/spectral_tilt
        - **Stage 3: Body Enhancement** — `LowShelfFilter(200Hz, +0.5 to +2 dB)` + `PeakFilter(800Hz, +0.5 to +1.5 dB)`, inversely scaled from Bass energy and mid_scoop_ratio
        - **Stage 4: Analog Saturation** — `analog_saturate()` (numpy, NOT pedalboard Distortion — even harmonics vs harsh odd harmonics)
        - **Stage 5: Moog-Style LPF** — `LadderFilter(LPF24, cutoff=14–18kHz, resonance=0.0–0.1)`, 24dB/oct analog tape HF rolloff
        - **Stage 6: Glue Compression** — `Compressor(threshold=-12 to -28 dB, ratio=1.2–2.0:1 normal / 1.1–1.7:1 vocal, attack=40–20ms, release=250–100ms)`
        - **Stage 7: Loudness Match + Limiter** — crest-factor-aware RMS correction (penalty applied when compression reduces dynamic range) + `Limiter(threshold_db=-0.5)` for streaming-safe ceiling
      - Pipeline flow: `Input → [Pedalboard chain 1] Stages 1-3 → [numpy] Stage 4 saturation → [Pedalboard chain 2] Stages 5-6 → [numpy] Stage 7 loudness match → [Pedalboard] Limiter → Output`
      - **`get_analysis_report(audio, sr, intensity=0.5)`** — returns JSON-serializable dict with spectral_profile, diagnostics, planned_adjustments, and summary string for `/analyze` endpoint
    - [x] **Step 7b — Add endpoints to `routers/audio_edit_test_router.py`**
      - Add pedalboard imports: `Compressor`, `Limiter`, `Gain`, `HighShelfFilter`, `LowShelfFilter`, `HighpassFilter`, `LadderFilter`
      - Add `from services.warmth_service import apply_warmth, get_analysis_report`
      - `POST /test-edit/warmth` — same pattern as `/eq`: resolve source → read audio → `apply_warmth(audio, sr, intensity)` → encode → StreamingResponse
        - Params: `file/url` + `intensity: float = Form(0.5, ge=0.0, le=1.0)` + `output_format`
      - `POST /test-edit/warmth/analyze` — resolve source → read audio → `get_analysis_report(audio, sr, intensity)` → JSONResponse
        - Returns: `{ spectral_profile, diagnostics, planned_adjustments, summary }`
      - Add `"warmth"` to the allowed operations list in `save_edit()` (line 379)
    - [x] **Step 7c — Update `audio_edit_test.html`**
      - Add "AI Warmth" tab to `.op-tabs` with premium styling (gradient border or distinct color)
      - Add `#panel-warmth` panel with:
        - Headline: "AI Analog Warmth" + subtitle explaining one-click fix
        - Intensity range slider (0–100) with labeled stops: Subtle (30), Standard (50), Warm (70), Heavy (100)
        - 4 preset quick-pick buttons that set the slider value
      - Update JS `opLabels` map: add `warmth: 'AI Warmth'`
      - Update `buildFD()`: warmth case appends `intensity` (slider value / 100)
      - Update `getOpParams()`: warmth case returns `{ intensity: <value> }`
      - `runBtn.textContent` updates to "Run AI Warmth" when tab selected

    - [x] **Step 7d — Vocal Mode (`vocal_mode=True`)**
      - Problem: AI vocals still sound robotic after general warmth — different artifacts need different treatment
      - AI vocal-specific artifacts: harsh sibilance (6–9kHz "s/sh"), dry/no space, flat dynamics, weak chest resonance
      - Add `vocal_mode: bool = False` param to `apply_warmth`, `compute_warmth_params`, `get_analysis_report`, and both router endpoints
      - **`services/warmth_service.py` changes:**
        - Add `Reverb` to pedalboard imports
        - Add frequency params to `compute_warmth_params` output so chain uses them instead of hardcoded values: `deharsh_freq1`, `deharsh_freq2`, `body_boost_freq`, `bass_boost_freq`
        - When `vocal_mode=True`, override params:
          - Stage 2: shift de-harshness to sibilance zone — `deharsh_freq1=5500Hz` (consonant harshness), `deharsh_freq2=8500Hz` (sibilance peak) with stronger cuts (-2 to -6dB)
          - Stage 3: shift to vocal body — `bass_boost_freq=300Hz` (chest resonance), `body_boost_freq=3000Hz` (vocal presence/intelligibility)
          - Stage 4: lighter saturation — `drive` max 1.5 (not 2.5), `asymmetry` 0.03–0.08 (avoid distorting vocals)
          - Stage 5: higher LPF cutoff 16–18kHz (preserve vocal air, don't dull the top end)
          - Stage 5.5 NEW: `Reverb(room_size=0.15–0.30, damping=0.8, wet_level=0.05–0.13)` — inserts a subtle room reverb between LadderFilter and Compressor, only in vocal mode; wet level scales with intensity
          - Stage 6: faster attack (15→5ms), lower ratio (1.5:1–2.5:1), shorter release (100→50ms) — gentler dynamics for natural breath variation
        - Add reverb params to `compute_warmth_params` output: `reverb_room_size`, `reverb_wet_level`, `reverb_damping`
        - `apply_warmth`: read `deharsh_freq1/2`, `body_boost_freq`, `bass_boost_freq` from params dict (instead of hardcoded); conditionally add `Reverb` to chain2 when `vocal_mode=True`
      - **`routers/audio_edit_test_router.py` changes:**
        - Add `vocal_mode: bool = Form(False)` to `POST /test-edit/warmth` and `POST /test-edit/warmth/analyze`
        - Pass `vocal_mode` through to `apply_warmth()` and `get_analysis_report()`
        - Add `Reverb` to pedalboard imports block
      - **`audio_edit_test.html` changes:**
        - Add vocal mode toggle checkbox inside `#panel-warmth` below the preset buttons
        - Update `buildFD()` warmth case: append `vocal_mode` as `"true"` or `"false"` string
        - Update `getOpParams()` warmth case: include `vocal_mode` boolean

- [x] **Step 7e–7h — AI Style Enhancer (Preset Enhancement — Paid Feature)**
  - Preset-driven enhancement: user picks a genre style, intensity controls dry/wet blend (0% = bypass, 100% = full)
  - 6 presets: **Lo-Fi**, **EDM / Club**, **Cinematic**, **Pop / Radio**, **Chill / Ambient**, **Vintage / Classic**
  - No new pip dependencies — `Chorus`, `Bitcrush`, `Delay` already in pedalboard 0.9.22
  - Reuses `analog_saturate()` from `warmth_service.py` for the Vintage preset
  - Reuses same crest-factor-aware loudness match + Limiter pattern from warmth
  - [x] **Step 7e — Create `services/enhancer_service.py`**
    - `PRESETS` dict — maps preset id → `{ name, description, tags, chain_config, stereo_widen_width, use_saturation }`
    - `stereo_widen(audio, width)` — numpy mid-side widening; mono passthrough fallback
    - `_build_chain(preset_id)` → `Pedalboard` — constructs plugin chain at call time (not module load)
    - `apply_preset(audio, sr, preset_id, intensity=0.7)` → float32
      - `dry = audio.copy()` → apply chain → stereo widen (if preset uses it) → saturation (Vintage only)
      - Dry/wet blend: `output = dry*(1-intensity) + processed*intensity`
      - Crest-factor-aware loudness match + `Limiter(-0.5dBFS)`
    - `get_presets_list()` → list of `{ id, name, description, tags }` for the GET endpoint
  - [x] **Step 7f — Add endpoints to `routers/audio_edit_test_router.py`**
    - Add imports: `Chorus`, `Bitcrush` from pedalboard; `apply_preset`, `get_presets_list` from enhancer_service
    - `GET /enhance/presets` → `JSONResponse({ "presets": get_presets_list() })`
    - `POST /enhance` → `file/url + preset: str + intensity: float(0.7) + output_format` → `StreamingResponse`
    - Add `"enhance"` to the save whitelist in `save_edit()`
  - [x] **Step 7g — Update `audio_edit_test.html`**
    - Add CSS: `.enhance-grid` (2×3 card grid), `.enhance-card` (selectable), `.enhance-card.selected` (purple highlight)
    - Add `✦ Style Enhance` tab with `.op-tab-premium` class
    - Add `#panel-enhance`: headline, 6 preset cards (name + description + tag pills), blend intensity slider (0–100, default 70), hidden `<input id="enhance_preset" value="lofi">`
    - JS: add `enhance` to `opLabels`; `buildFD()` case appends `preset` + `intensity`; `getOpParams()` returns `{ preset, intensity }`; card click sets hidden input + toggles `.selected`
  - [x] **Step 7h — Update `plan.md`**

  **Preset DSP recipes:**
  | Preset | Key plugins | Character |
  |--------|-------------|-----------|
  | Lo-Fi | HPF 80Hz + LowShelf +2dB + HighShelf -4dB@8kHz + Bitcrush(12bit) + Chorus + Reverb(small) + Compressor(3:1) | Warm, dusty, cassette |
  | EDM | HPF 40Hz + PeakFilter +3dB@60Hz + +2dB@3.5kHz + HighShelf +2dB@12kHz + stereo widen + Compressor(4:1 fast) + Limiter | Punchy, wide, loud |
  | Cinematic | HPF 30Hz + LowShelf +1.5dB@120Hz + PeakFilter -1dB@800Hz + HighShelf +1dB@10kHz + Reverb(hall 0.7) + stereo widen + Compressor(2:1 slow) | Grand, spacious |
  | Pop | HPF 60Hz + PeakFilter -1.5dB@200Hz + +1.5dB@3kHz + HighShelf +2dB@10kHz + stereo widen + Compressor(3:1) + Limiter | Bright, polished |
  | Chill | HPF 60Hz + LowShelf +1dB + HighShelf -2dB@8kHz + Chorus(slow) + Reverb(medium) + Compressor(2:1 slow) | Soft, dreamy |
  | Vintage | HPF 50Hz + LowShelf +2dB@150Hz + PeakFilter -1dB@3.5kHz + HighShelf -2dB@12kHz + `analog_saturate(1.3, 0.08)` + Compressor(2.5:1) + Reverb(small) | Warm, tube, 70s |

- [ ] **Step 8 — Test**
  - Start server: `uvicorn main:app --reload`
  - Open `GET /test-edit/ui`
  - Run any operation → preview audio plays inline
  - Click **Download** → file saves to local machine
  - Fill in `user_id` + `project_id`, click **Save to Cloud** → row appears in `editing_table`, `output_url` is a valid playable Supabase Storage URL
  - Test all 7 original operations with both URL input and file upload toggle
  - **AI Warmth specific tests:**
    - Load an AI-generated track → select "AI Warmth" tab → test at different intensities (0.3, 0.5, 0.7, 1.0)
    - Verify progressive warmth effect (subtle → heavy)
    - Verify loudness match: output should NOT be perceptibly louder than input
    - Test `/warmth/analyze` via curl → verify JSON response with spectral profile + diagnostics
    - Test with varied content: harsh EDM, soft acoustic, vocal-heavy
    - Test Save to Cloud with operation="warmth" → row appears in `editing_table`
  - **AI Style Enhancer specific tests:**
    - `GET /test-edit/enhance/presets` → JSON with 6 preset entries (id, name, description, tags)
    - Load a track → select "Style Enhance" tab → click each of the 6 preset cards → Run → distinct character per preset
    - Test intensity=0% → output identical to input (pure dry)
    - Test intensity=100% → full preset applied
    - Verify loudness match: output not perceptibly louder than input
    - Test Save to Cloud with operation="enhance" → row in `editing_table`

### Architecture note

**Stateless editing:** All edit operations (Steps 1–3) are stateless — no DB writes on every edit. The server processes the audio and streams the result back immediately. The user previews in the UI.

**Explicit Save only:** The DB (`editing_table`) is written only when the user clicks **Save to Cloud**. This keeps the common path (edit + preview + download) entirely serverless from a storage perspective.

**User flow:**
1. User applies an edit operation → result streams back → audio player shows
2. User listens → satisfied → clicks **Download** (local save, no server storage) or **Save to Cloud** (uploads to Supabase Storage, inserts one `editing_table` row)

**Lossless pipeline:** All audio processing uses **Spotify Pedalboard** + **numpy**. Audio is decoded to float32 once on read, all operations happen on the numpy array (zero quality loss), and encoded to MP3 only once on final export with `quality="V0"` (highest VBR quality). EQ uses native `PeakFilter` — no ffmpeg subprocess needed.

**AI Analog Warmth — Feature Reference**

### The Problem

AI music generators (MusicGPT, Suno, Udio, etc.) produce audio entirely in the digital domain — no physical hardware involved. This creates a characteristic "metallic sheen" that makes AI music easy to identify:

- **Too much 2–8kHz energy** — synthesized instruments sound harsh and brittle in this range
- **No harmonic distortion** — real tubes, transformers, and tape add subtle even-order overtones (2nd, 4th harmonics) that make audio feel "alive"; digital audio has zero of this
- **Sterile dynamics** — AI tracks are perfectly even; real recordings have subtle compression character from analog signal chains
- **Overly bright top end** — no natural HF rolloff that tape machines and analog consoles introduce above 14–16kHz
- **AI vocals specifically** — also suffer from harsh sibilance (s/sh sounds), complete dryness (no room), and flat dynamics that sound robotic

---

### How It Works — Adaptive Pipeline

The feature does **spectral analysis first**, then adapts every parameter to that specific track. A harsh EDM track and a soft acoustic track get completely different EQ curves, saturation amounts, and compression settings. It is not a fixed preset.

**Files:**
- `services/warmth_service.py` — all DSP logic
- `routers/audio_edit_test_router.py` — `POST /test-edit/warmth` and `POST /test-edit/warmth/analyze`
- `audio_edit_test.html` — "✦ AI Warmth" tab with intensity slider + Vocal Mode toggle

---

### Stage 0 — Spectral Analysis (`analyze_spectrum`)

**What it does:** Runs a windowed FFT (8192-sample Hanning window, 50% overlap) on the mono-mixed signal. Computes energy in 6 frequency bands and derives 5 adaptive metrics.

**6 Band Energies:**
- Sub (20–60Hz), Bass (60–250Hz), LowMid (250–2kHz), HighMid (2–6kHz), Presence (6–12kHz), Air (12–20kHz)

**5 Adaptive Metrics — these drive every subsequent stage:**
| Metric | Formula | Drives |
|--------|---------|--------|
| `harshness_ratio` | (HighMid + Presence) / (LowMid + Bass) | How aggressively to cut Stage 2 |
| `spectral_tilt` | Slope of log-energy vs log-freq regression | How much HF rolloff to apply |
| `crest_factor_db` | 20·log10(peak/RMS) | Saturation drive + compression threshold |
| `mid_scoop_ratio` | LowMid / (Bass + HighMid) | Whether to boost body in Stage 3 |
| `overall_rms_db` | 20·log10(RMS) | Compression threshold in Stage 6 |

**Why it matters:** This is what replaces the mastering engineer's ears. Instead of a trained human identifying "too much 3.5kHz," the FFT measures it numerically and every downstream parameter adapts automatically. Studio equivalent: iZotope Ozone's Master Assistant / FabFilter Pro-Q spectrum analyzer.

---

### Stage 1 — Subsonic Cleanup

**What it does:** `HighpassFilter(cutoff_frequency_hz=30.0)` — fixed, always applied.

**Why:** Removes DC offset and sub-bass rumble below 30Hz. This energy is inaudible but wastes headroom and causes issues in the saturation stage. Every professional mastering chain starts with this.

---

### Stage 2 — Adaptive De-harshness

**What it does:** Two `PeakFilter` cuts + one `HighShelfFilter`, all adaptive.

**Normal mode (full mix):**
- `PeakFilter(3500Hz, -1 to -4 dB, q=1.0)` — cuts the core metallic sheen zone
- `PeakFilter(7000Hz, -0.5 to -3 dB, q=0.8)` — tames presence harshness
- `HighShelfFilter(10000Hz, -0.5 to -2.5 dB)` — analog-style HF rolloff

**Vocal mode:**
- `PeakFilter(5500Hz, -2 to -6 dB)` — consonant harshness zone (where "t", "k" sounds are harsh)
- `PeakFilter(8500Hz, -1.5 to -5 dB)` — sibilance peak (where "s", "sh" sounds are unnaturally sharp)
- `HighShelfFilter(10000Hz, -0.2 to -1 dB)` — lighter rolloff to preserve vocal air

**Why:** The cut amounts scale with `harshness_ratio`. A warm acoustic track gets -1dB. A harsh AI EDM track gets -4dB. Studio equivalent: mastering engineer making surgical EQ cuts with a parametric EQ (SSL, Neve 1073, FabFilter Pro-Q).

---

### Stage 3 — Body Enhancement

**What it does:** `LowShelfFilter` + `PeakFilter` boost, adaptive.

**Normal mode (full mix):**
- `LowShelfFilter(200Hz, +0.5 to +2 dB)` — bass/warmth shelf
- `PeakFilter(800Hz, +0.5 to +1.5 dB, q=0.5)` — low-mid body (only when `mid_scoop_ratio` indicates hollow midrange)

**Vocal mode:**
- `LowShelfFilter(300Hz, +0.5 to +1.5 dB)` — chest resonance (the "body" of the human voice)
- `PeakFilter(3000Hz, +1 to +2 dB, q=0.5)` — vocal presence and intelligibility

**Why:** AI music often lacks the low-mid body that real recordings have because analog gear (consoles, preamps, transformers) naturally adds warmth at these frequencies. The boost amount is inversely scaled from the track's existing bass content — a track with strong bass gets a lighter boost. Studio equivalent: Neve 1073 low-shelf boost, SSL 4000 console EQ.

---

### Stage 4 — Analog Saturation (numpy — not pedalboard)

**What it does:** Asymmetric tanh waveshaping that generates even-order harmonics.

```python
x = audio * drive
x = x + asymmetry * (x ** 2)   # x² generates 2nd harmonic, x⁴ generates 4th
result = np.tanh(x)             # soft clip — no harsh distortion
result -= mean(result)          # remove DC offset from asymmetry
```

**Parameters:**
- Normal mode: `drive` 1.1–2.5, `asymmetry` 0.05–0.15
- Vocal mode: `drive` 1.1–1.5, `asymmetry` 0.03–0.08 (lighter — heavy drive distorts vocal formants)
- `drive` scales inversely with `crest_factor_db` — already-compressed audio gets less drive

**Why this is the core of the feature:** Real analog gear (tubes, transformers, tape) generates even harmonics (2nd, 4th) as a physical byproduct. When a note plays at 440Hz, a tube amp produces faint energy at 880Hz and 1760Hz — which human ears perceive as warmth and richness. Digital audio has zero of this. Pedalboard's `Distortion`/`Clipping` plugins generate odd harmonics (3rd, 5th) which sound harsh — not warm. The `x²` term in the formula is the only way to correctly generate even harmonics. Studio equivalent: $10,000–$50,000 Neve transformer preamps, Studer A820 tape machine, Universal Audio 1176.

---

### Stage 5 — Moog-Style LPF

**What it does:** `LadderFilter(mode=LPF24, cutoff_hz=14–18kHz, resonance=0–0.05, drive=1.0–1.3)`

**Normal mode:** Cutoff 14–18kHz (lower at higher intensity)
**Vocal mode:** Cutoff 16–18kHz (stays higher — preserves vocal breath and air above 16kHz)

**Why:** Analog tape machines and consoles naturally roll off high frequencies above 14–16kHz due to physical bandwidth limitations of the hardware. This is the signature "analog silk" sound — the top end gets softer and less fatiguing. The `LadderFilter`'s 24dB/oct slope is steeper and more musical than a shelf filter, and the subtle resonance at the cutoff adds the characteristic "analog silk" that simpler filters don't produce. Studio equivalent: running audio through a tape machine (Studer, Ampex), SSL or Neve console output stage.

---

### Stage 5.5 — Room Reverb (vocal mode only)

**What it does:** `Reverb(room_size=0.15–0.30, damping=0.8, wet_level=5–13%, dry_level=100%)`

- Room size and wet level scale with intensity (more intensity = larger room + more wet)
- `damping=0.8` — damps the reverb tail so it doesn't get washy or bright

**Why:** AI vocals are completely dry — they have zero acoustic environment. Even 8% wet mix transforms the vocal from "synthesized in a computer" to "recorded in a real room." This is the single biggest perceptual improvement for AI vocals. The reverb is applied before compression so the room tail gets gently controlled. Studio equivalent: recording in a real room, or running vocals through a hardware reverb unit (Lexicon 480L, EMT 140 plate reverb).

---

### Stage 6 — Glue Compression

**What it does:** `Compressor` with adaptive threshold, followed by gain correction.

**Normal mode (full mix glue):**
- Ratio: 2:1 → 4:1 (scales with intensity)
- Attack: 30ms → 10ms, Release: 200ms → 80ms
- Threshold: driven by `overall_rms_db - 5dB` (always catches the signal)

**Vocal mode (dynamics control):**
- Ratio: 1.5:1 → 2.5:1 (lower — preserves natural breath variation)
- Attack: 15ms → 5ms (faster — catches harsh consonants before they hit)
- Release: 100ms → 50ms (shorter — natural breath movement)

**Why:** The full-mix compressor "glues" all the elements together the way an analog bus compressor does — it subtly pumps and breathes with the music, creating cohesion. The vocal compressor is tuned differently: faster attack to control harsh consonants, lower ratio to preserve the natural rise and fall of the voice. Studio equivalent: SSL G-Bus Compressor (mix glue), Universal Audio 1176 or LA-2A (vocals).

---

### Stage 7 — Loudness Match + Safety Limiter

**What it does:**
1. Measures input RMS before any processing
2. Measures output RMS after all processing
3. Applies exact gain correction: `gain = input_rms / output_rms` (clamped to ±12dB)
4. `Limiter(threshold_db=-0.5, release_ms=50)` — final ceiling

**Why this matters:** Most "mastering" or "enhancement" tools make output louder than input. Louder always sounds better to human ears (the Fletcher-Munson effect) — so users think the processing improved the track when really they're just hearing volume. This feature corrects to identical loudness so users hear the actual tonal improvement, not just a level boost. The -0.5 dBFS limiter matches Spotify, Apple Music, and YouTube's inter-sample peak requirements. Studio equivalent: mastering engineer's RMS metering and true peak limiter.

**Crest-factor-aware matching (added after v1):**
Stage 7 now measures both RMS and peak before processing to compute `input_crest = input_peak / input_rms`.
After processing: `crest_penalty = sqrt(output_crest / input_crest)`, clamped `[0.6, 1.0]`.
Final gain = `(input_rms / output_rms) × crest_penalty`.
When compression reduces dynamic range, `output_crest < input_crest` → penalty < 1.0 → gain pulled back to compensate for perceived loudness increase from flattened dynamics.

---

### Tuning History / Rollback Reference

If the audio feels wrong after a future change, these are the values at each revision:

#### v1 — Initial implementation
| Parameter | Value |
|-----------|-------|
| Normal saturation drive | `1.1 + 1.4 * drive_scale * intensity` → **1.1 to 2.5** |
| Vocal saturation drive | `1.1 + 0.4 * drive_scale * intensity` → **1.1 to 1.5** |
| Normal comp ratio | `2.0 + 2.0 * intensity` → **2.0:1 to 4.0:1** |
| Normal comp attack | `30ms → 10ms` |
| Normal comp release | `150ms → 80ms` |
| Vocal comp ratio | `1.5 + 1.0 * intensity` → **1.5:1 to 2.5:1** |
| Loudness match | RMS-only: `gain = input_rms / output_rms` |
| **User complaint** | Audio felt heavy and loud — more like mastering than warmth |

#### v2 — Compression reduced, crest-factor loudness match added (current)
| Parameter | Value |
|-----------|-------|
| Normal saturation drive | `1.1 + 0.7 * drive_scale * intensity` → **1.1 to 1.8** |
| Vocal saturation drive | unchanged — `1.1 to 1.5` |
| Normal comp ratio | `1.2 + 0.8 * intensity` → **1.2:1 to 2.0:1** |
| Normal comp attack | `40ms → 20ms` (slower — less pumping) |
| Normal comp release | `250ms → 100ms` |
| Vocal comp ratio | `1.1 + 0.6 * intensity` → **1.1:1 to 1.7:1** |
| Loudness match | Crest-aware: `gain = (input_rms / output_rms) × crest_penalty` |
| **Rationale** | Lighter saturation (colour not distortion) + gentler compression (glue not mastering) + crest penalty removes perceived loudness from dynamic flattening |

---

### Adaptive Logic Summary

Every parameter adapts to the track — this is not a fixed preset:

| If the track has... | The pipeline automatically... |
|---------------------|-------------------------------|
| High `harshness_ratio` (>1.5) | Cuts Stage 2 more aggressively (-4dB instead of -1dB) |
| Positive `spectral_tilt` (bright) | Applies more HF rolloff in Stage 2 shelf |
| Low `bass_pct` (<10%) in spectrum | Boosts Stage 3 low shelf more (+2dB instead of +0.5dB) |
| Low `crest_factor_db` (<10dB, compressed) | Uses less saturation drive (avoids over-distorting) |
| Low `overall_rms_db` (quiet track) | Sets lower compression threshold to still catch the signal |

---

### Vocal Mode vs Normal Mode — Key Differences

| Parameter | Normal (Full Mix) | Vocal Mode |
|-----------|-------------------|------------|
| De-harshness target | 3.5kHz + 7kHz (metallic sheen) | 5.5kHz + 8.5kHz (sibilance) |
| Body boost | 200Hz warmth + 800Hz body | 300Hz chest + 3kHz presence |
| Saturation drive | 1.1–**1.8** (max at intensity=1.0) | 1.1–1.5 (won't distort formants) |
| LPF cutoff | 14–18kHz | 16–18kHz (preserves breath/air) |
| Room reverb | None | 5–13% wet small room |
| Compression ratio | **1.2:1–2.0:1** | **1.1:1–1.7:1** |
| Compression attack | **40ms → 20ms** | 15ms → 5ms (catches consonants) |
| Compression release | **250ms → 100ms** | 100ms → 50ms |
| Loudness match | **Crest-factor-aware** (RMS × crest penalty) | same |

---

### Studio Engineer Equivalent

This feature automates what a mastering engineer ($50–$500/track, 1–3 hours/song) does manually:

| Engineer Action | Studio Hardware | This Feature |
|-----------------|-----------------|--------------|
| Spectrum analysis | iZotope Ozone, FabFilter Pro-Q | `analyze_spectrum()` — numpy FFT |
| Parametric EQ cuts | SSL 4000, Neve 1073 | Stages 2 & 3 adaptive PeakFilters |
| Tape/tube warmth | Neve preamp, Studer A820 tape | Stage 4 asymmetric tanh saturation |
| Console HF rolloff | SSL/Neve output stage | Stage 5 LadderFilter LPF24 |
| Vocal room | Lexicon 480L, EMT 140 plate | Stage 5.5 Reverb (vocal mode) |
| Bus compression | SSL G-Bus, Neve 33609 | Stage 6 Compressor |
| Level matching | VU/RMS meters | Stage 7 RMS correction |
| Streaming limiting | True peak limiter | Stage 7 Limiter at -0.5 dBFS |

**Processing time:** 3–6 seconds for a 3-minute track on 2 vCPU / 4GB RAM. All processing is local — no external API calls, no per-use cost.


 Analog Warmth — fixes AI music's digital flaws. Analyzes the track's      
  frequency spectrum and adaptively corrects harshness, adds tube/tape      
  saturation, rolls off harsh highs. Same process every time, parameters    
  change per track. Think "doctor fixing problems."                         
                                                                            
  Style Enhancer — stamps a genre identity onto the music. You pick Lo-Fi /
  EDM / Cinematic / Pop / Chill / Vintage and it applies that aesthetic's
  complete DSP recipe. Blend slider controls how much. Think "costume       
  change."                                                                  
                                                                            
  Key difference: Warmth is adaptive (reads the track, fixes it). Enhancer  
  is preset (you choose the vibe, it applies it). Use Warmth first to clean,
   then Enhancer to style.