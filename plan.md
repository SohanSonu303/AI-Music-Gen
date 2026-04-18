You’re essentially building a **"Musical Tailor"**—a system that takes "raw fabric" (your long audio file) and "hems" it to the perfect fit using AI-driven logic.

Below is the **Product Requirements Document (PRD)** for the **Automated AI Music Editor (AIME)**.

---

# PRD: Automated AI Music Editor (AIME)

**Version:** 1.0  
**Status:** Draft / Technical Specification  
**Objective:** To provide precise, musically-aware audio duration control using an LLM-Agent and signal processing.

---

## 1. Executive Summary
The AIME system solves the "duration gap" in AI music generation. While models generate great content, they lack temporal precision. AIME uses an Agentic framework to analyze uploaded MP3/WAV files and programmatically edit them to match user-defined lengths (e.g., 30s, 60s) while maintaining musical integrity (beat-matching, phrasing, and smooth transitions).

## 2. User Input & Parameters
The system must accept the following inputs via API or UI:
* **Audio File:** `.mp3`, `.wav`.
* **Target Duration:** Integer/Float (Seconds)
* **Energy Preference:** (Optional) "High energy," "Climax," or "Intro-heavy."

---

## 3. Core Functional Requirements

### FR-1: Audio Feature Extraction (The "Hearing")
The system must extract metadata using libraries like **Librosa** or **Essentia**:
* **BPM & Beat Timestamps:** Identifying exactly when every beat occurs.
* **Segment Mapping:** Identifying "Structural Onsets" (verse, chorus, bridge) based on energy and frequency changes.
* **Downbeat Detection:** Ensuring cuts happen on the "1" of a 4/4 bar.

### FR-2: Intelligent Segment Selection (The "Decision")
The AI Agent (DeepSeek) must use the extracted data to:
* Scan the audio for the "best" window that matches the target length.
* Calculate the **Musical Deviation**: If the user wants 30s, but the nearest bar ends at 30.2s, the Agent chooses 30.2s to avoid a rhythmic break.

### FR-3: Automated Editing Execution (The "Cutting")
Using **Pydub** or **FFmpeg**, the system must:
* **Trim:** Slice the file at the calculated timestamps.
* **Crossfade:** If multiple segments are joined, apply a $50ms$ - $200ms$ crossfade to prevent clicking.
* **Outro Fade:** Apply a logarithmic fade-out over the final 1.5 seconds.

---

## 4. Technical Architecture


### The Agentic Loop (LangGraph Implementation)
1.  **State Definition:** Store `file_path`, `bpm`, `bar_map`, and `target_duration`.
2.  **Tooling:**
    * `get_music_structure()`: Returns timestamps of high-energy sections.
    * `calculate_trim_points()`: Logic to snap the target duration to the nearest beat.
    * `edit_engine()`: The final export function.

---

## 5. Success Metrics & Quality Control
* **Beat Consistency:** $100\%$ of cuts must occur within $15ms$ of a detected beat.
* **No "Ghost Artifacts":** Zero audible pops or clicks at transition points.

---

## 6. Future Scope
* **Stem Separation:** Automatically removing vocals if the clip is too short for a full verse.
* **Visual Sync:** Generating a video-ready file that pulses with the beat.

---

## 7. Implementation Plan (v1)

### 7.1 Locked Decisions
| Area | Decision |
|---|---|
| Beat / downbeat / segment detection | **librosa** (add to `requirements.txt`) |
| Agent strategy | **Hybrid** — algorithm produces top-K candidate windows; LLM picks the best one using segment labels + user energy pref |
| `target > source` behaviour | **Loop** source audio (`np.tile` + crossfade at seam) then trim |
| v1 scope | **Single contiguous window** (no multi-segment stitching) |
| Router | **New `/auto-edit/*` router** (standalone, not under `/test-edit`) |
| Persistence | **`editing_table`** with `operation="auto_trim"` |
| Energy preference | **UI control** → passed as optional API param |

### 7.2 Architecture (follows warmth / enhancer pattern)

```
POST /auto-edit/trim
  ↓
routers/auto_edit_router.py     ← HTTP + file/url ingest + threadpool dispatch
  ↓
services/auto_edit_service.py   ← pipeline: analyze → candidates → execute
  ↓ (when ≥2 candidates)
agents/auto_edit_agent.py       ← LangGraph single-node window selector
                                   (OpenRouter DeepSeek v3.2, reuses _call_openrouter pattern)
  ↓
pedalboard AudioFile I/O + numpy  ← trim / loop / crossfade / fade-out / encode
  ↓
POST /auto-edit/save → editing_table
```

**Reuses:** pedalboard AudioFile decode/encode, numpy slice ops, OpenRouter client pattern from [agents/album_agent.py](agents/album_agent.py), save flow from [routers/audio_edit_test_router.py](routers/audio_edit_test_router.py).

### 7.3 TODO Checklist

**Phase 1 — Foundation** ✅
- [x] Add `librosa` to `requirements.txt` + `pyproject.toml`; installed via `uv add librosa` (0.11.0 + numba 0.65.0 — no conflicts)
- [x] Create `services/auto_edit_service.py` skeleton with module docstring
- [x] Create `routers/auto_edit_router.py` with prefix `/auto-edit`, tags `["Auto Edit"]`
- [x] Register router in `main.py`
- [x] Add Pydantic request/response models in `models/auto_edit_model.py` (`AutoTrimRequest`, `AutoTrimResponse`, `SegmentInfo`, `AudioAnalysis`)

**Phase 2 — Audio Analysis (FR-1: "The Hearing")** ✅
- [x] `analyze_audio(audio: np.ndarray, sr: int) -> AnalysisResult` in `services/auto_edit_service.py`:
  - `bpm: float` (via `librosa.beat.beat_track`)
  - `beat_times: list[float]` (seconds)
  - `downbeat_times: list[float]` (every 4th beat under 4/4 assumption for v1)
  - `segment_boundaries` + `segment_energies` + `segment_labels` (via `librosa.segment.agglomerative` on MFCC)
  - `duration: float`
- [x] Downmix to mono for analysis only; original stereo array untouched
- [x] Guard: reject source < 8s with 422 (in router)
- [x] `POST /auto-edit/analyze` live; `POST /auto-edit/trim` + `/save` wired as 501 stubs

**Phase 3 — Candidate Window Generation (FR-2 algorithmic half)** ✅
- [x] `find_candidate_windows(analysis, target_duration, energy_pref, top_k=3) -> list[Window]` in `services/auto_edit_service.py`
- [x] Each candidate starts and ends on a detected downbeat (beat_deviation_ms = 0 by construction)
- [x] Duration deviation ≤ 1 bar from target (`tolerance = 4 * 60 / bpm`)
- [x] Ranked by weighted score: 50% duration closeness + 30% energy match + 20% structural completeness
- [x] Returns top-3 (fewer if less viable); single loop-window returned when target > source (`needs_loop=True`)
- [x] Pure function — smoke-tested with synthetic `AnalysisResult` (no real audio needed)
- [x] Helper `_window_segment_info()` — overlap fraction, avg energy, n_complete count
- [x] Helper `_energy_score()` — handles `high_energy`, `climax`, `intro_heavy`, None

**Phase 4 — LLM Selection (Hybrid B / FR-2 agent half)** ✅
- [x] `agents/auto_edit_agent.py` — `select_window(candidates, energy_pref) -> (Window, reasoning, used_fallback)`
- [x] LangGraph single-node graph (`_select_window_node`); calls OpenRouter DeepSeek v3.2 via `_call_openrouter()`
- [x] Prompt asks LLM to return `{"chosen_index": int, "reasoning": str}` as JSON; strips markdown fences if present
- [x] Reuses `_call_openrouter()` from `services/prompt_service` (300 s read timeout, 3 retries, 5/10/15 s backoff)
- [x] **Short-circuit:** returns rank-0 immediately when `len(candidates) == 1` — no API call
- [x] **Fallback:** catches any exception, returns index 0 with `used_fallback=True` and error note
- [x] Smoke-tested: short-circuit path verified; graph structure confirmed (`__start__` → `select_window`)

**Phase 5 — Editing Execution (FR-3: "The Cutting")** ✅
- [x] `execute_trim(audio, sr, start_sec, end_sec, target_duration=None) -> np.ndarray` in `services/auto_edit_service.py`
- [x] **Loop mode**: `_loop_to_target()` uses overlap-add (step = src_len − xfade_n) with 100 ms equal-power cos²/sin² crossfades — cleaner than np.tile, no clicks at seams
- [x] Logarithmic outro fade: `np.logspace(0, -4, fade_samples)` over last 1.5 s applied after any loop fill
- [x] Returns float32 numpy array — encoding to MP3/WAV handled in router (Phase 6)
- [x] Smoke-tested: trim ✓, loop-fill to exact target ✓, empty-segment guard ✓, fade-to-silence at last sample ✓

**Phase 6 — API & Persistence** ✅
- [x] `POST /auto-edit/analyze` — accepts `file`/`url`, returns BPM + beats + segments JSON
- [x] `POST /auto-edit/trim` — full pipeline in `routers/auto_edit_router.py`: analyze → candidates → `select_window` (async LLM) → `execute_trim` → encode; all CPU stages in `run_in_threadpool`; returns audio blob + `X-AIME-*` metadata headers
- [x] `POST /auto-edit/save` — uploads blob to Supabase Storage, inserts `editing_table` row with `operation="auto_trim"` and full `operation_params` dict (target_duration, energy_preference, window, actual_duration, was_looped, agent_reasoning, bpm)
- [x] `energy_preference` validated against allowed values; 501 stubs removed
- [x] Import of `select_window` is local to the endpoint (avoids circular import at module level)

**Phase 7 — Quality Control (Success Metrics)** ✅
- [x] `_nearest_beat_deviation_ms()` — measures how far cut points deviate from nearest detected beat; logged + warning if > 15ms
- [x] `_check_click()` — flags potential clicks when first-sample amplitude is > 15% of peak; returns `(has_click, cut_amp)` included in quality_warning header
- [x] All quality metrics returned in `X-AIME-Beat-Dev-MS` and `X-AIME-Quality-Warning` response headers; UI surfaces them in the metadata box
- [ ] Manual QA: run on 5 real MusicGPT outputs at 15s / 30s / 45s / 60s / 90s targets — pending first real audio test

**Phase 8 — UI Integration** ✅
- [x] `✦ Auto Trim` op-tab added to `audio_edit_test.html` (premium gradient styling)
- [x] `panel-auto_trim` panel: target duration input (seconds) + energy preference dropdown (`auto / high_energy / climax / intro_heavy`)
- [x] `aime-meta` metadata box: BPM, window timestamps, actual duration, beat-deviation badge, looped badge, fallback badge, AI reasoning line, quality warning
- [x] WaveSurfer region overlay on source waveform after trim completes (green region marking the chosen window)
- [x] JS: `getRunEndpoint()` routes `auto_trim` → `/auto-edit/trim`; `getSaveEndpoint()` routes save to `/auto-edit/save`
- [x] `getOpParams('auto_trim')` includes full trim metadata in the save payload
- [x] `fmtSec()` helper for `M:SS.d` display of sub-second precision

### 7.4 Edge Cases
- Source < 8s → `422 Unprocessable Entity`
- `target_duration == source_duration` → return original unchanged, log as no-op
- No detectable downbeats (ambient / no transients) → fall back to beat grid; log warning in response
- `target ≫ source` (e.g. 60s from 10s) → loop 6× with crossfade; include `quality_warning` in response
- Stereo input → all ops preserve channel count; analysis downmixes mono internally only

### 7.5 Non-goals for v1
- Stem separation (deferred to Section 6)
- Visual sync (deferred to Section 6)
- Non-contiguous multi-segment stitching (e.g., intro + chorus + outro)
- Time-stretching / tempo change — always cut, never stretch

### 7.6 Open Risks
- **librosa install weight** — numba/llvmlite can fail on some Python versions; verify on dev before committing
- **Downbeat detection accuracy** — librosa beat tracker gives beats, not downbeats; the 4/4 assumption may drift on tracks with pickup bars. If this becomes a problem, evaluate `madmom.features.downbeats` as a follow-up.
- **LLM latency** — adds ~2–5s per request; acceptable since feature is not real-time. Short-circuit when only 1 candidate keeps the common case fast.

---

## 8. v2 Production-Readiness Improvements

v1 (Phases 1–8) is functional end-to-end but feels like a prototype compared to warmth/enhancer. v2 closes the polish gap: structured responses, user-visible analysis, candidate transparency, adaptive controls, better audio intelligence.

### 8.1 TODO Checklist

**Phase 9 — Structured JSON Response (S)** ✅
- [x] Expand `AutoTrimResponse` in `models/auto_edit_model.py` with full metadata: `bpm`, `window_start`, `window_end`, `actual_duration`, `beat_deviation_ms`, `quality_warning`, `was_looped`, `agent_reasoning`, `candidates` list, `chosen_index`
- [x] Add `CandidateWindow` model: `index`, `start`, `end`, `duration`, `duration_score`, `energy_score`, `structural_score`, `total_score`, `segment_labels`, `needs_loop`
- [x] Update `POST /auto-edit/trim` in `routers/auto_edit_router.py`: return JSON with `audio_b64` (base64) + all metadata + all candidates
- [x] Keep `X-AIME-*` headers as backward-compatible fallback; primary response is now JSON
- [x] Update `audio_edit_test.html` JS — `handleAimeTrimResponse()` parses JSON, decodes base64 to Blob

**Phase 10 — Analyze-Before-Trim Preview (S)** ✅
- [x] Accept optional `target_duration` and `energy_preference` form params in `POST /auto-edit/analyze`
- [x] When `target_duration` is provided, run `find_candidate_windows()` and include candidates in the analyze response
- [x] Add "Analyze Audio First" button in `audio_edit_test.html` auto_trim panel — calls `/auto-edit/analyze` with target duration + energy preference
- [x] Render analysis preview: BPM badge, segment timeline (coloured blocks by label), candidate windows as waveform regions
- [x] Candidate preview cards shown after analyze (read-only, no "Use this" button)

**Phase 11 — Candidate Comparison UI + Manual Override (M)** ✅
- [x] Return all candidates in the `/trim` JSON response
- [x] Display candidates as selectable cards: start/end, score breakdown (dur/energy/struct), segment labels, AI-chosen card highlighted green
- [x] Add `chosen_window_index` optional form param to `POST /auto-edit/trim` — when provided, skip LLM and use that candidate directly
- [x] WaveSurfer region overlay: chosen = green, others = semi-transparent gray
- [x] "Use this" button on non-chosen cards calls `retrimWithCandidate(i)` — re-POSTs `/trim` with `chosen_window_index=i`

**Phase 12 — Strictness Slider (M)** ✅
- [x] Add `strictness` float (0.0–1.0, default 0.5) to `AutoTrimRequest` in `models/auto_edit_model.py`
- [x] Parameterize weight split in `find_candidate_windows()`: at `strictness=1.0` → 80/10/10; at `strictness=0.0` → 20/40/40; linear interpolation between
- [x] Add slider + label ("Musical / Balanced / Precise") in `audio_edit_test.html`; passes to both Analyze and Run
- [x] Threaded through `/analyze` (candidate scoring) and `/trim` (candidate generation) in `routers/auto_edit_router.py`

**Phase 13 — Beat-Synced Crossfade (M)** ✅
- [x] Replace hardcoded 100ms crossfade with `xfade_ms = crossfade_beats * (60/bpm) * 1000`; clamped 20–500ms
- [x] Add `crossfade_beats` param (default 1.0) to `execute_trim()` and `AutoTrimRequest`; also accepted by router
- [x] Fade-in applied at trim start boundary (not just loop seams) — smooths abrupt entries
- [x] UI: "Half beat / 1 beat (default) / 2 beats / 1 bar" dropdown in auto_trim panel

**Phase 14 — Spectral Segment Labeling (L)** ✅
- [x] Added `_compute_spectral_features(mono, sr, bound_times)` — returns per-segment chroma_var, contrast, onset_density (all normalised 0–1)
- [x] Rewrote `_label_segments()` to use spectral features: chorus (high energy + high chroma var), drop (high energy + high onset density), verse (moderate + chroma), build (moderate + rising onset), bridge/intro/outro (low energy + positional)
- [x] Graceful fallback to v1 energy-only heuristic if spectral extraction fails
- [x] Expanded label set: `intro | verse | build | chorus | peak | drop | bridge | outro`
- [x] Updated CSS in `audio_edit_test.html` with distinct colour per label (verse=purple, chorus=green, drop=red, bridge=blue)
- [x] Updated LLM system prompt with full label glossary, decision hints about musical storytelling, `needs_loop` awareness

**Phase 15 — Spectral Quality Scoring (L)** ✅
- [x] Added `_spectral_quality_score(audio_mono, sr, start, end)` in `services/auto_edit_service.py`: crest factor, spectral centroid stability (std over frames), harshness ratio (2–5kHz / total energy)
- [x] Integrated into `find_candidate_windows()` with 10% fixed weight; interpolated 4-axis split becomes `(0.18→0.72 dur) / (0.36→0.09 energy) / (0.36→0.09 struct) / 0.10 spectral` across strictness range
- [x] Added `spectral_quality_score: float = 0.5` field to `CandidateWindow` model in `models/auto_edit_model.py`
- [x] Per-window spectral scores logged via `logger.info` for debugging

**Phase 16 — Intelligent Loop Restructuring (L)** ✅
- [x] Added `_intelligent_loop(audio, sr, analysis, target_duration, bpm, crossfade_beats, arrangement)` in `services/auto_edit_service.py` — overlap-add stitch with beat-synced crossfades between reordered segments
- [x] Added `_build_arrangement(analysis, target_duration)` — algorithmic planner; prioritises intro→verse→chorus→outro order, repeats chorus/peak/drop, pads with all-segment repeats to hit target
- [x] Added `plan_loop_arrangement(segments, target_duration) -> list[int]` in `agents/auto_edit_agent.py` — LLM arrangement planner with `_ARRANGE_SYSTEM_PROMPT`; falls back to algorithmic repeat-all on failure
- [x] `execute_trim()` in `services/auto_edit_service.py` calls `_intelligent_loop` when `analysis` has ≥3 segments and `loop_arrangement` is provided; falls back to `_loop_to_target()` otherwise
- [x] Router calls `plan_loop_arrangement` async before threadpool when `needs_loop=True`; passes `loop_arrangement` into `_trim_encode_pipeline`

**Phase 17 — A/B Comparison UI (M)** ✅
- [x] `handleAimeTrimResponse()` captures source audio as `originalBlobUrl` (file → `createObjectURL`, URL input → string); shows `#ab-controls` div with "Trimmed" badge when source is available; resets on each new trim
- [x] `#ab-toggle-btn` click listener toggles `abMode` between `'trimmed'` and `'original'`; reads current playback position before destroy to enable position sync
- [x] Position mapping: trimmed→original adds `window_start`; original→trimmed subtracts `window_start` (clamped to 0)
- [x] Original view: gray waveform with `RegionsPlugin` overlay — green region = kept window, red-tint regions = removed sections before/after
- [x] Play/pause state preserved across toggle (was-playing flag captured before `wsResult.destroy()`)
- [x] A/B controls hidden and state reset when non-auto_trim operation runs

### 8.2 v2 Priority Order — ALL COMPLETE ✅
1. ✅ Phase 10 — Analyze preview
2. ✅ Phase 9 — Structured response
3. ✅ Phase 11 — Candidate comparison + manual override
4. ✅ Phase 12 — Strictness slider
5. ✅ Phase 13 — Beat-synced crossfade
6. ✅ Phase 17 — A/B comparison UI
7. ✅ Phase 14 — Spectral labeling (8-label decision tree)
8. ✅ Phase 15 — Spectral quality scoring
9. ✅ Phase 16 — Intelligent loop restructuring (LLM arrangement planner)

### 8.3 v2 Non-goals (unchanged)
- Real-time preview / streaming trim (latency budget is 5–15s, not real-time)
- Multi-track / stem-aware trimming (deferred to Section 6)
- Time-stretching / pitch-shifting (still cut-only in v2)
- Mobile-optimized UI (desktop browser is the target)

### 8.4 v2 Verification
- After each phase: run dev server (`uvicorn main:app --reload`), upload a real audio file, test full pipeline in browser
- Phase 10: verify `POST /auto-edit/analyze` with `target_duration` returns candidates + segments ✅
- Phase 11: verify candidate cards render, clicking "Use this" re-trims without re-analysis ✅
- Phase 12: verify strictness=0 picks the most musical window, strictness=1 hits exact target ✅
- Phase 13: verify crossfade sounds musical at different beat fractions ✅
- Phase 17: verify A/B toggle swaps audio without playback position reset — pending manual QA
- Phase 15: verify `spectral_quality_score` appears in candidate response and varies per window — pending manual QA
- Phase 16: verify intelligent loop produces musically coherent arrangement for target >> source — pending manual QA

### 8.5 Remaining Manual QA Checklist
- [ ] Upload 5 real MusicGPT outputs, run trim at 15s / 30s / 45s / 60s / 90s targets (Phase 7 item)
- [ ] A/B toggle: confirm position sync accuracy and region overlays are correctly positioned
- [ ] Intelligent loop: test with target 3× source length; confirm LLM arrangement planner fires and arrangement is musical
- [ ] Spectral quality score: log output to confirm it varies meaningfully across candidate windows
- [ ] Strictness extremes: confirm strictness=0.0 ignores duration, strictness=1.0 hits target within 1 beat

---