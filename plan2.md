# Premium Audio Features — Implementation TODO

**Build order: Feature 1 → Feature 2 → Feature 3** (Feature 3 imports from Feature 1)

---

## User Flows

### Feature 1: AI Platform Mastering — User Flow

1. User opens the audio editor UI and loads their track (file upload or URL)
2. They click the **✦ Master** tab
3. They see 6 platform cards — Spotify, YouTube, TikTok, Podcast, Apple Music, SoundCloud — each showing the target LUFS and true peak ceiling
4. They click one (e.g. "Spotify") — it highlights
5. They hit **"Master Now"**
6. A few seconds later the result waveform appears with a **Report box** showing:
   - Before: `-18.2 LUFS / -0.3 dBTP`
   - After: `-14.0 LUFS / -1.0 dBTP` (shown in green = compliant)
   - Gain applied: `+3.8 dB`
   - Changes made: "Air shelf EQ +1dB at 12kHz", "Glue compression 2:1", "LUFS gain +3.8dB", "True peak limited to -1.0dBFS"
7. They preview the mastered audio, hit **Download** or **Save to Cloud**

**Aha moment:** They upload the same track to Spotify and it sounds just as loud as every other song. They never have to think about LUFS again.

---

### Feature 2: Reference Track Matching — User Flow

**Sub-flow A — Match sonic character**

1. User loads their AI-generated track in the main source panel
2. They click the **✦ Reference Match** tab
3. A second upload widget appears — they upload or paste a URL to a reference track (e.g. a Drake song, a lo-fi playlist track)
4. They hit **"Analyze Reference"** first (optional but recommended)
   - A preview box appears instantly: "Reference: 92 BPM, A minor. Projected changes: +3dB at 60Hz, -2dB at 3.5kHz, stereo width +0.2"
5. They hit **"Match to Reference"**
6. Result appears with a report:
   - EQ bands applied (e.g. "60Hz +2.8dB, 200Hz -1.1dB, 3.5kHz -1.9dB...")
   - Dynamics: "Reference is more compressed (crest factor 8dB vs your 14dB) — applied 1.7:1 compression"
   - Stereo: "Reference width 0.6 vs your 0.3 — widened by +0.3"
7. They A/B compare, download or save

**Sub-flow B — Generate in this vibe**

1. User loads any reference track (doesn't need their own track)
2. Clicks **"Generate Vibe Prompt"**
3. A text area appears with a ready-to-use MusicGPT prompt like:
   > *"Melancholic trap beat at 92 BPM in A minor. Deep 808 sub bass, airy hi-hats, dark piano chords. Sparse atmospheric production with heavy reverb. Cinematic and introspective, late-night studio feel."*
4. They copy it straight into the music generation flow

**Aha moment:** Instead of trying to describe in words what they want, they just upload a song they love. The AI does the translation.

---

### Feature 3: AI Podcast Producer — User Flow

1. User loads their raw podcast recording in the main source panel (could be a 30-min Zoom recording, single mic, background noise, uneven levels)
2. They click the **✦ Podcast** tab
3. They optionally upload background music in the second upload widget (e.g. a chill instrumental or a track generated with the existing music generator)
4. They configure options via checkboxes (all on by default):
   - ✅ Noise Reduction *(warning badge: "~2–5 min for long audio")*
   - ✅ Voice EQ & Leveling
   - ✅ Add Intro/Outro Music
5. They adjust: Intro Duration (8s), Outro Duration (8s), Music Duck Level (-18dB)
6. They hit **"Produce Episode"** — a spinner shows "Running vocal separation..."
7. Result appears with a report:
   - "Before: -23 LUFS → After: -16 LUFS (podcast standard)"
   - "Speech duration: 28m 14s → Total episode: 28m 30s"
   - Changes: "Vocal isolation + noise gate applied", "Voice EQ applied", "Music ducked -18dB under speech", "Intro/outro attached with 500ms crossfade"
8. They download the finished `.mp3` ready to upload to Spotify Podcasts, Apple Podcasts, etc.

**Aha moment:** What used to be 2 hours of work in Audacity (cleanup, leveling, adding music, manual ducking) takes one click and 3 minutes.

---

### How the flows connect

All 3 features feed into each other naturally:

- User generates a track → **masters it for Spotify** (Feature 1)
- User wants to match a vibe → **gets a prompt** (Feature 2) → generates a track → masters it (Feature 1)
- Podcaster **generates background music** with the existing music generator → feeds it into **Podcast Producer** (Feature 3) for auto-ducking

---

## Feature 1: AI Platform Mastering
*"One button: Master for Spotify / YouTube / TikTok / Podcast"*

**Why creators pay:** They don't know what -14 LUFS means — they just know their track sounds quiet on Spotify. This removes that confusion entirely.

### New Files
- `services/mastering_service.py`
- `routers/mastering_router.py`

### TODO

**Service (`services/mastering_service.py`)**
- [x] Define `PLATFORM_PROFILES` dict: Spotify (-14 LUFS, -1dBTP), YouTube (-13 LUFS, -1dBTP), TikTok (-14 LUFS, -2dBTP), Podcast (-16 LUFS, -1dBTP), Apple Music (-16 LUFS), SoundCloud (-14 LUFS)
- [x] `measure_lufs(audio, sr) -> float` — use `pyloudnorm.Meter` with `.T` transpose (pyloudnorm expects `(samples, channels)`, codebase uses `(channels, samples)`)
- [x] `measure_true_peak_db(audio) -> float` — compute dBFS from absolute max
- [x] `apply_mastering_eq(audio, sr, platform) -> np.ndarray` — platform-specific tonal shaping via pedalboard filters (podcast: HPF 80Hz, de-harsh at 5kHz; music: air shelf +1dB at 12kHz)
- [x] `apply_glue_compression(audio, sr, platform) -> np.ndarray` — music: 2:1 ratio 40ms attack; podcast: 3:1 ratio 10ms attack
- [x] `apply_lufs_gain(audio, sr, target_lufs, current_lufs) -> np.ndarray` — linear gain from dB delta, clamp to ±20dB guard
- [x] `apply_true_peak_limiter(audio, sr, ceiling_db) -> np.ndarray` — `pedalboard.Limiter(threshold_db=ceiling_db)`
- [x] `master_for_platform(audio, sr, platform) -> tuple[np.ndarray, dict]` — full pipeline: EQ → stereo widen (import `stereo_widen` from `enhancer_service`) → compress → measure LUFS → gain → limit → return (audio, report)
- [x] Guard: if `current_lufs < -70.0`, skip gain and include warning in report (near-silent file protection)
- [x] `report_dict` shape: `{platform, target_lufs, true_peak_ceiling, before: {lufs, true_peak_db}, after: {lufs, true_peak_db}, gain_applied_db, changes: [str]}`

**Router (`routers/mastering_router.py`)**
- [x] `GET /master/platforms` → list of all platform profiles with name, target_lufs, true_peak_db
- [x] `POST /master/process` — accept `file`/`url` + `platform` + `output_format`; run in `run_in_threadpool`; return `{audio_b64, audio_format, report}`
- [x] `POST /master/save` — standard save pattern; `operation="mastering"`, `operation_params` includes full report

**main.py**
- [x] Import and `app.include_router(mastering_router.router)`

**Dependencies**
- [x] Add `"pyloudnorm>=0.1.1"` to `pyproject.toml` — installed `pyloudnorm==0.2.0`

**UI (`audio_edit_test.html`)**
- [x] Add `✦ Master` premium tab button
- [x] Platform selection grid (6 cards): each shows platform name + target LUFS + true peak ceiling; selected card gets highlight
- [x] "Master Now" button + output format toggle
- [x] Post-process: "Report" panel showing before/after LUFS (green = compliant), gain applied, bulleted changes list
- [x] Standard waveform result + Download + Save to Cloud

---

## Feature 2: Reference Track Matching
*"Make it sound like THIS song"*

**Why creators pay:** Every music brief starts with "make it sound like [reference]." This is the #1 ask from music creators. Currently requires a professional mastering engineer.

### New Files
- `services/reference_match_service.py`
- `routers/reference_match_router.py`

### TODO

**Service (`services/reference_match_service.py`)**
- [x] `compute_power_spectrum(audio, sr, n_fft=16384) -> (freqs, power_db)` — windowed FFT with Hann window, 50% overlap (same pattern as `warmth_service.analyze_spectrum`)
- [x] `compute_spectral_correction_db(ref_power, target_power, freqs) -> (freqs, correction_db)` — `ref - target`, smooth with `scipy.ndimage.gaussian_filter1d(sigma=20)`, clamp to ±12dB
- [x] `correction_to_eq_bands(freqs, correction_db, n_bands=10) -> list[dict]` — map continuous correction to 10 log-spaced PeakFilter bands (60Hz–16kHz), each ±0.3 octave window average, Q=1.0
- [x] `apply_spectral_eq(audio, sr, bands) -> np.ndarray` — build `pedalboard.Pedalboard` from PeakFilter list, skip bands with `abs(gain_db) < 0.3`
- [x] `measure_dynamics_profile(audio, sr) -> dict` — crest_factor_db, rms_db, dynamic_range_db (RMS in 100ms windows, 90th–10th percentile spread)
- [x] `apply_dynamics_match(audio, sr, ref_profile, target_profile) -> np.ndarray` — if ref is more compressed: apply `pedalboard.Compressor` with proportional ratio; if ref is more dynamic: skip (no expansion in v1, note in report)
- [x] `measure_stereo_width(audio) -> float` — M-S: `side_rms / (mid_rms + side_rms)`, returns 0.0–1.0
- [x] `apply_stereo_match(audio, ref_width, target_width) -> np.ndarray` — import `stereo_widen` from `enhancer_service`; widen or narrow (M-S narrowing), clamp adjustment to ±0.4
- [x] `extract_musical_fingerprint(audio, sr) -> dict` — BPM via `librosa.beat.beat_track`, key via `librosa.feature.chroma_cqt` + Krumhansl-Schmuckler profiles; returns `{bpm, key, mode}`
- [x] `match_to_reference(target, sr_target, reference, sr_ref) -> tuple[np.ndarray, dict]` — full pipeline: resample ref if SR mismatch → spectral EQ → dynamics → stereo → crest-factor loudness match (Stage 7 pattern from `warmth_service`) → limiter -1dBFS → return (audio, report)
- [x] Minimum duration check: reject reference tracks under 20s with clear error message
- [x] `report_dict` shape: `{eq_bands_applied, dynamics: {ref, target_before, target_after}, stereo_width: {ref, target_before, target_after}, reference_fingerprint, target_fingerprint, changes_summary}`

**"Generate Vibe Prompt" mode**
- [x] `extract_vibe_prompt(audio, sr) -> dict` — runs `extract_musical_fingerprint` + `analyze_spectrum` (from `warmth_service`), calls `_call_openrouter` (from `prompt_service`) to produce a MusicGPT-ready prompt from the fingerprint data; returns `{prompt, fingerprint}`

**Router (`routers/reference_match_router.py`)**
- [x] `POST /reference-match/analyze` — accept two sources (reference + target file/url), return analysis report only (no audio encode, fast ~0.5s preview)
- [x] `POST /reference-match/process` — full pipeline, return `{audio_b64, audio_format, report}`
- [x] `POST /reference-match/vibe-prompt` — reference only → LLM-generated MusicGPT prompt
- [x] `POST /reference-match/save` — standard save; `operation="reference_match"`

**main.py**
- [x] Import and `app.include_router(reference_match_router.router)`

**Dependencies**
- [x] Add `"scipy>=1.13.0"` to `pyproject.toml`

**UI (`audio_edit_test.html`)**
- [x] Add `✦ Reference Match` premium tab
- [x] Two-source layout: main source panel = "Your Track"; second upload widget (file/url toggle) = "Reference Track"
- [x] "Analyze Reference" button → pre-process insight box: reference BPM, key, top 3 projected EQ changes
- [x] "Match to Reference" primary button
- [x] "Generate Vibe Prompt" secondary button → copyable text area with generated MusicGPT prompt
- [x] Post-process report: EQ bands applied, dynamics change, stereo width change
- [x] Standard waveform result + Download + Save to Cloud

---

## Feature 3: AI Podcast Producer
*"Upload raw podcast → get production-ready episode"*

**Why creators pay:** Podcast editing is the most tedious audio task. Noise reduction + leveling + music + ducking covers 80% of what editors actually do.

**v1 scope (buildable now):** noise gate, voice EQ/leveling, LUFS normalization, intro/outro music attach, auto-ducking
**v2 scope (future):** Whisper filler word removal (requires ~1GB model, 5–15min processing for long audio — intentionally excluded from v1)

> **Dependency on Feature 1:** `mastering_service.measure_lufs` and `apply_lufs_gain` must exist before Feature 3 can be built.

### New Files
- `services/podcast_service.py`
- `routers/podcast_router.py`

### TODO

**Service (`services/podcast_service.py`)**
- [x] `apply_spectral_noise_gate(vocal_audio, sr, threshold_db=-50.0) -> np.ndarray` — `pedalboard.NoiseGate`
- [x] `apply_voice_eq(vocal_audio, sr) -> np.ndarray` — HPF 80Hz + PeakFilter 200Hz -2dB + PeakFilter 3kHz +1.5dB + HighShelf 10kHz -1dB + Compressor 3:1 10ms attack
- [x] `compute_speech_activity(speech_audio, sr, frame_size_ms=50.0, threshold_db=-40.0) -> np.ndarray` — RMS per 50ms frame → binary activity array
- [x] `compute_duck_envelope(activity, sr, frame_size_ms, duck_db=-18.0, attack_frames=4, release_frames=10) -> np.ndarray` — exponential smoothed gain envelope upsampled to sample level
- [x] `apply_ducking(music_audio, envelope) -> np.ndarray` — `music * envelope[np.newaxis, :]` (stereo broadcast)
- [x] `crossfade_join(a, b, sr, fade_ms=500.0) -> np.ndarray` — overlap-add crossfade at junction
- [x] `build_podcast_episode(speech_audio, music_audio, sr, ...) -> tuple[np.ndarray, dict]` — loop music bed, duck, mix, crossfade join intro→body→outro
- [x] `run_demucs_separation_sync(input_path, output_dir) -> dict[str, str]` — synchronous subprocess demucs, returns stem paths
- [x] `produce_podcast(speech_audio, sr_speech, music_audio, sr_music, options) -> tuple[np.ndarray, dict]` — full pipeline
- [x] Add comment: demucs on 60-min audio = 5–15 min; must migrate to Celery task for production

**Router (`routers/podcast_router.py`)**
- [x] `POST /podcast/produce` — accept speech + optional music + all options; run in `run_in_threadpool`; return `{audio_b64, audio_format, report}`
- [x] `POST /podcast/save` — standard save; `operation="podcast_produce"`

**main.py**
- [x] Import and `app.include_router(podcast_router.router)`

**UI (`audio_edit_test.html`)**
- [x] Add `✦ Podcast` premium tab
- [x] Speech source: uses main source panel
- [x] Music source: second upload widget (file/url toggle), labeled "Background Music (optional)"
- [x] Checklist options: Noise Reduction (default on, with "⚠ slow on long audio" badge), Voice EQ & Leveling (default on), Add Intro/Outro Music (default on, dims controls when unchecked)
- [x] Intro/Outro Duration inputs; Music Duck Level slider (−6 to −24 dB, default −18 dB)
- [x] "Produce Episode" button + busy message "Producing episode — this may take a few minutes…"
- [x] Post-process report: before/after LUFS, speech duration, episode duration, processing chain
- [x] Standard waveform result + Download + Save to Cloud

---

## Shared Changes

- [x] Add `"pyloudnorm>=0.1.1"` to `pyproject.toml` — installed `pyloudnorm==0.2.0`
- [x] Add `"scipy>=1.13.0"` to `pyproject.toml`
- [x] Register `mastering_router` in `main.py`
- [x] Register `reference_match_router` in `main.py`
- [x] Register `podcast_router` in `main.py`
- [ ] No new DB tables — all 3 features use `editing_table` with operation strings: `"mastering"`, `"reference_match"`, `"podcast_produce"`

## Verification

- [x] Feature 1: Upload a track, master for Spotify, verify LUFS report shows ~-14.0 after — smoke tested ✓
- [ ] Feature 2: Upload your track + a reference, verify EQ bands and report show meaningful changes
- [ ] Feature 2 vibe-prompt: Upload a reference, verify returned prompt is MusicGPT-ready and reflects the track's genre/tempo
- [ ] Feature 3: Upload a podcast clip + background music, verify ducking audibly reduces music under speech
- [ ] All 3: Save to Cloud, verify `editing_table` row inserted with correct `operation` and `operation_params`
