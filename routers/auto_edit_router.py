"""
Auto Edit Router — v2
=====================
Prefix: /auto-edit   Tags: ["Auto Edit"]

Full AIME pipeline:
  POST /auto-edit/analyze  — extract BPM, beats, downbeats, segments; optionally score candidates (v2)
  POST /auto-edit/trim     — full pipeline: analyze → candidates → LLM/manual → trim → JSON response (v2)
  POST /auto-edit/save     — upload to Supabase Storage + insert editing_table row
"""

import base64
import io
import json
import logging
import os
import tempfile
import urllib.parse
from dataclasses import asdict
from typing import Optional
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from routers.audio_edit_test_router import (
    _encode_to_bytes,
    _read_audio,
    _resolve_source,
    _validate_format,
)
from services.auto_edit_service import (
    MIN_SOURCE_DURATION,
    Window,
    analyze_audio,
    execute_trim,
    find_candidate_windows,
)
from supabase_client import supabase

logger = logging.getLogger(__name__)

STORAGE_BUCKET = os.environ.get("BUCKET_NAME", "music-generated")

VALID_ENERGY_PREFS = (
    "high_energy",   # raw energy — prefer loud energetic sections
    "climax",        # peak / drop / chorus — the most intense moment
    "drop",          # EDM drop specifically
    "chorus",        # hook / harmonic richness
    "verse",         # melodic, narrative section
    "build",         # rising tension / riser
    "chill",         # low energy, relaxed, ambient
    "outro",         # late/closing section
    "intro_heavy",   # early/opening section
)

router = APIRouter(prefix="/auto-edit", tags=["Auto Edit"])


# ── Quality-control helpers ────────────────────────────────────────────────────

def _nearest_beat_deviation_ms(timestamp: float, beat_times: list[float]) -> float:
    """Return deviation in ms from ``timestamp`` to the nearest detected beat."""
    if not beat_times:
        return 0.0
    return round(min(abs(timestamp - bt) for bt in beat_times) * 1000.0, 2)


def _check_click(audio: np.ndarray) -> tuple[bool, float]:
    """
    Flag a potential click at the start of the trimmed output.

    Returns (has_click, first_sample_amplitude).
    """
    if audio.shape[1] == 0:
        return False, 0.0
    first_amp = float(np.abs(audio[:, 0]).max())
    peak_amp = float(np.abs(audio).max()) if audio.size > 0 else 1.0
    has_click = (first_amp / max(peak_amp, 1e-8)) > 0.15
    return has_click, round(first_amp, 4)


# ── CPU-bound pipeline helpers ─────────────────────────────────────────────────

def _analyze_pipeline(
    audio: np.ndarray,
    sr: int,
    target_duration: float,
    energy_pref: Optional[str],
    strictness: float = 0.5,
):
    """Run analyze_audio + find_candidate_windows in a single threadpool call."""
    analysis = analyze_audio(audio, sr)
    # Downmix to mono for spectral quality scoring (Phase 15)
    mono = audio.mean(axis=0).astype(np.float32)
    candidates = find_candidate_windows(
        analysis, target_duration, energy_pref,
        strictness=strictness, mono=mono, sr=sr,
    )
    return analysis, candidates


def _trim_encode_pipeline(
    audio: np.ndarray,
    sr: int,
    ch: int,
    chosen: Window,
    target_duration: float,
    fmt: str,
    bpm: float = 120.0,
    crossfade_beats: float = 1.0,
    analysis=None,
    loop_arrangement: Optional[list] = None,
):
    """Run execute_trim + click-check + encode in a single threadpool call."""
    trimmed = execute_trim(
        audio, sr, chosen.start, chosen.end, target_duration,
        bpm=bpm, crossfade_beats=crossfade_beats,
        analysis=analysis, loop_arrangement=loop_arrangement,
    )
    has_click, cut_amp = _check_click(trimmed)
    data = _encode_to_bytes(trimmed, sr, ch, fmt)
    actual_dur = round(trimmed.shape[1] / sr, 3)
    return data, actual_dur, has_click, cut_amp


def _upload_and_insert(
    data: bytes,
    user_id: str,
    project_id: str,
    op_params: dict,
    source_url: str,
    fmt: str,
) -> dict:
    """
    Upload audio bytes to Supabase Storage and insert an editing_table row.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{fmt}")
    try:
        tmp.write(data)
        tmp.flush()
        tmp.close()
        audio, sr, _ = _read_audio(tmp.name)
        duration = round(audio.shape[1] / sr, 3)
    except Exception:
        duration = 0.0
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    job_id = str(uuid4())
    storage_path = f"{user_id}/{project_id}/{job_id}.{fmt}"
    content_type = "audio/mpeg" if fmt == "mp3" else "audio/wav"

    supabase.storage.from_(STORAGE_BUCKET).upload(
        file=data,
        path=storage_path,
        file_options={"content-type": content_type},
    )
    output_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)

    supabase.table("editing_table").insert({
        "id": job_id,
        "user_id": user_id,
        "project_id": project_id,
        "operation": "auto_trim",
        "operation_params": op_params,
        "source_url": source_url or "unknown",
        "output_url": output_url,
        "output_format": fmt,
        "output_duration": duration,
    }).execute()

    logger.info(
        "auto_edit/save: user=%s project=%s → %s (%.3fs)",
        user_id, project_id, output_url, duration,
    )
    return {"id": job_id, "output_url": output_url, "output_duration": duration}


def _windows_to_payload(candidates: list[Window]) -> list[dict]:
    """Serialise candidate Windows to JSON-ready dicts with rank index."""
    return [
        {
            "index": i,
            "start": c.start,
            "end": c.end,
            "duration": c.duration,
            "duration_score": c.duration_score,
            "energy_score": c.energy_score,
            "structural_score": c.structural_score,
            "spectral_quality_score": c.spectral_quality_score,
            "total_score": c.total_score,
            "segment_labels": c.segment_labels,
            "needs_loop": c.needs_loop,
        }
        for i, c in enumerate(candidates)
    ]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze_track(
    file: Optional[UploadFile] = File(None, description="Upload audio file (mp3/wav)"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    target_duration: Optional[float] = Form(
        None, gt=0,
        description="(v2) When provided, also score and return candidate trim windows",
    ),
    energy_preference: Optional[str] = Form(
        None,
        description="(v2) Energy bias for candidate scoring: high_energy | climax | intro_heavy",
    ),
    strictness: float = Form(
        0.5,
        description="(v2) Strictness used when scoring candidates (0.0=musical · 1.0=precise)",
    ),
):
    """
    Analyse an audio file and return its musical structure.

    Returns JSON with **bpm**, **duration**, **beat_times**, **downbeat_times**,
    and **segments** ``{start, end, energy, label}``.

    **v2:** Pass ``target_duration`` to also receive a **candidates** list —
    the top-3 beat-aligned trim windows pre-scored for the UI preview.
    This lets you show the analysis *before* committing to a trim.
    """
    if energy_preference and energy_preference not in VALID_ENERGY_PREFS:
        raise HTTPException(
            status_code=422,
            detail=f"energy_preference must be one of {VALID_ENERGY_PREFS} or omitted.",
        )

    path = await _resolve_source(file, url)
    try:
        audio, sr, _ = _read_audio(path)
        duration = audio.shape[1] / sr
        if duration < MIN_SOURCE_DURATION:
            raise HTTPException(
                status_code=422,
                detail=f"Audio too short ({duration:.1f}s). Minimum required: {MIN_SOURCE_DURATION}s.",
            )
        result = await run_in_threadpool(analyze_audio, audio, sr)

        candidates_payload = None
        if target_duration is not None:
            mono_ref = audio.mean(axis=0).astype(np.float32)
            candidates = await run_in_threadpool(
                find_candidate_windows, result, target_duration, energy_preference,
                3, strictness, mono_ref, sr,
            )
            candidates_payload = _windows_to_payload(candidates)
    finally:
        os.unlink(path)

    return JSONResponse({
        "bpm": result.bpm,
        "duration": result.duration,
        "beat_times": result.beat_times,
        "downbeat_times": result.downbeat_times,
        "segments": [asdict(s) for s in result.segments],
        "candidates": candidates_payload,
        "used_beat_fallback": result.used_beat_fallback,
    })


@router.post("/suggest")
async def suggest_params(
    description: str = Form(..., description="Natural-language description of what the user wants"),
    source_duration: Optional[float] = Form(None, description="Source audio duration in seconds (helps the LLM give realistic suggestions)"),
):
    """
    Parse a natural-language description and return suggested AIME parameters.

    The LLM fills in ``target_duration``, ``energy_preference``, ``strictness``,
    and ``crossfade_beats`` from the user's plain-text intent.

    Example input: *"I need a punchy 30-second drop for my DJ mix"*
    Example output: ``{target_duration: 30, energy_preference: "climax", strictness: 0.5, crossfade_beats: 0.5, explanation: "..."}``
    """
    from services.prompt_service import _call_openrouter

    system = """\
You map a music editor's natural-language request to AIME parameters. \
Return ONLY valid JSON — no markdown fences, no extra text:
{
  "target_duration": <float|null — seconds; null if unclear>,
  "energy_preference": <"high_energy"|"climax"|"intro_heavy"|null>,
  "strictness": <float 0.0–1.0>,
  "crossfade_beats": <0.5|1.0|2.0|4.0>,
  "explanation": "<one sentence summarising your choices>"
}

Rules:
- target_duration: extract from description ("30 seconds"→30.0, "half a minute"→30.0, "a minute"→60.0). \
  If unclear or not mentioned, use null.
- energy_preference: choose ONE of the following or null: \
  "high_energy" — energetic, hype, intense, loud, powerful; \
  "climax"      — the most intense moment, punchiest, climax, biggest section; \
  "drop"        — EDM drop, bass drop, the drop specifically; \
  "chorus"      — hook, refrain, sing-along, memorable section; \
  "verse"       — melodic, narrative, story, lyrics section; \
  "build"       — riser, build-up, tension, anticipation before drop; \
  "chill"       — calm, relaxed, ambient, lo-fi, background, low energy; \
  "outro"       — ending, fade-out, closing, wind-down section; \
  "intro_heavy" — opening, intro, beginning, calm start, lead-in; \
  null          — balanced, general, best overall, no specific preference.
- strictness: 0.0 for "best sounding / musical", 1.0 for "exactly N seconds / precise". \
  Default 0.5 unless user strongly implies one extreme.
- crossfade_beats: 0.5 for tight/punchy/DJ, 1.0 default, 2.0 for smooth/relaxed, 4.0 for very gentle."""

    user_msg_parts = [f'User request: "{description}"']
    if source_duration:
        user_msg_parts.append(f"Source audio duration: {round(source_duration, 1)}s")
    user_msg = "\n".join(user_msg_parts)

    try:
        raw = await _call_openrouter(system, user_msg)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        parsed = json.loads(cleaned)
        return JSONResponse({
            "target_duration":   parsed.get("target_duration"),
            "energy_preference": parsed.get("energy_preference"),
            "strictness":        float(parsed.get("strictness", 0.5)),
            "crossfade_beats":   float(parsed.get("crossfade_beats", 1.0)),
            "explanation":       str(parsed.get("explanation", "")),
        })
    except Exception as exc:
        logger.warning("suggest_params: LLM failed (%s) — returning defaults", exc)
        return JSONResponse({
            "target_duration":   None,
            "energy_preference": None,
            "strictness":        0.5,
            "crossfade_beats":   1.0,
            "explanation":       "Could not parse suggestion — please fill in parameters manually.",
        })


@router.post("/preview")
async def preview_trim(
    file: Optional[UploadFile] = File(None, description="Upload audio file (mp3/wav)"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    target_duration: float = Form(..., gt=0, description="Target output duration in seconds"),
    energy_preference: Optional[str] = Form(None, description="high_energy | climax | intro_heavy"),
    strictness: float = Form(0.5),
    user_description: Optional[str] = Form(None, description="Free-text user intent"),
):
    """
    Analyze + LLM window selection — returns metadata only, no audio encoding.

    Much faster than /trim (~1–3s vs 5–15s). Use this to show the user which
    section will be cut before they commit. The chosen ``window_index`` can then
    be passed to ``/trim`` as ``chosen_window_index`` to skip the LLM on the
    second call.

    Returns: bpm, segments, all candidates, chosen_index, window_start/end,
    agent_reasoning, user_description.
    """
    from agents.auto_edit_agent import select_window

    if energy_preference and energy_preference not in VALID_ENERGY_PREFS:
        raise HTTPException(
            status_code=422,
            detail=f"energy_preference must be one of {VALID_ENERGY_PREFS} or omitted.",
        )

    source_duration = 0.0
    analysis = None
    candidates = []
    path = await _resolve_source(file, url)
    try:
        audio, sr, _ = _read_audio(path)
        source_duration = audio.shape[1] / sr
        if source_duration < MIN_SOURCE_DURATION:
            raise HTTPException(
                status_code=422,
                detail=f"Audio too short ({source_duration:.1f}s). Minimum: {MIN_SOURCE_DURATION}s.",
            )

        analysis, candidates = await run_in_threadpool(
            _analyze_pipeline, audio, sr, target_duration, energy_preference, strictness
        )
    finally:
        os.unlink(path)

    if not candidates:
        bpm_hint = f", bpm={analysis.bpm:.1f}" if analysis else ""
        raise HTTPException(
            status_code=422,
            detail=(
                f"No beat-aligned window found for {target_duration}s "
                f"(source={source_duration:.1f}s{bpm_hint}). "
                "Try a target within ±1 bar of a natural phrase boundary."
            ),
        )

    chosen, reasoning, used_fallback = await select_window(
        candidates, energy_preference, user_description
    )
    chosen_idx = next(
        (i for i, c in enumerate(candidates) if c.start == chosen.start and c.end == chosen.end),
        0,
    )

    logger.info(
        "preview: bpm=%.1f chosen=[%.2f–%.2f]s reasoning=%r",
        analysis.bpm, chosen.start, chosen.end, reasoning,
    )

    return JSONResponse({
        "bpm":              round(analysis.bpm, 1),
        "source_duration":  round(source_duration, 3),
        "segments":         [asdict(s) for s in analysis.segments],
        "candidates":       _windows_to_payload(candidates),
        "chosen_index":     chosen_idx,
        "window_start":     chosen.start,
        "window_end":       chosen.end,
        "window_duration":  round(chosen.end - chosen.start, 3),
        "agent_reasoning":  reasoning,
        "user_description": user_description or None,
        "used_fallback":    used_fallback,
        "needs_loop":       chosen.needs_loop,
    })


@router.post("/trim")
async def auto_trim(
    file: Optional[UploadFile] = File(None, description="Upload audio file (mp3/wav)"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    target_duration: float = Form(..., gt=0, description="Target output duration in seconds"),
    energy_preference: Optional[str] = Form(
        None, description="high_energy | climax | intro_heavy (omit for auto)"
    ),
    output_format: str = Form("mp3", description="mp3 or wav"),
    chosen_window_index: Optional[int] = Form(
        None,
        description="(v2) When set, skip LLM and use this candidate index (0=best-scored)",
    ),
    strictness: float = Form(
        0.5,
        description="(v2) 0.0=Musical integrity priority · 1.0=Precise duration hit · default 0.5",
    ),
    crossfade_beats: float = Form(
        1.0,
        description="(v2) Crossfade length in beats at loop seams + trim boundary (0.5/1/2/4)",
    ),
    user_description: Optional[str] = Form(
        None,
        description="(v2) Free-text intent from the user — forwarded to the LLM agent to guide window selection",
    ),
):
    """
    Beat-accurate auto-trim pipeline.

    Steps:
    1. Analyse audio (BPM, beats, downbeats, segments) — CPU threadpool
    2. Generate top-3 candidate windows aligned to downbeats — CPU threadpool
    3. LLM agent selects best window **or** use ``chosen_window_index`` to bypass LLM (v2)
    4. Trim + loop-fill if needed + outro fade + encode — CPU threadpool

    **v2:** Returns JSON ``{audio_b64, audio_format, bpm, window_start, window_end,
    actual_duration, beat_deviation_ms, was_looped, used_fallback, agent_reasoning,
    quality_warning, chosen_index, candidates}`` instead of a raw audio stream.
    ``X-AIME-*`` headers are still included for backward compatibility.
    """
    from agents.auto_edit_agent import select_window

    fmt = _validate_format(output_format)

    if energy_preference and energy_preference not in VALID_ENERGY_PREFS:
        raise HTTPException(
            status_code=422,
            detail=f"energy_preference must be one of {VALID_ENERGY_PREFS} or omitted.",
        )

    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        source_duration = audio.shape[1] / sr

        if source_duration < MIN_SOURCE_DURATION:
            raise HTTPException(
                status_code=422,
                detail=f"Audio too short ({source_duration:.1f}s). Minimum: {MIN_SOURCE_DURATION}s.",
            )

        # ── No-op guard ────────────────────────────────────────────────────────
        _NOOP_THRESHOLD_S = 0.1
        if abs(target_duration - source_duration) < _NOOP_THRESHOLD_S:
            logger.info(
                "auto_trim: target (%.3fs) ≈ source (%.3fs) — no-op, returning original",
                target_duration, source_duration,
            )
            data = await run_in_threadpool(_encode_to_bytes, audio, sr, ch, fmt)
            audio_b64 = base64.b64encode(data).decode("ascii")
            return JSONResponse({
                "audio_b64": audio_b64,
                "audio_format": fmt,
                "chosen_index": 0,
                "window_start": 0.0,
                "window_end": round(source_duration, 3),
                "actual_duration": round(source_duration, 3),
                "bpm": 0.0,
                "beat_deviation_ms": 0.0,
                "was_looped": False,
                "used_fallback": False,
                "agent_reasoning": "No-op: target duration equals source duration.",
                "quality_warning": None,
                "candidates": [],
            })

        # ── Step 1 & 2: analysis + candidate generation ────────────────────────
        analysis, candidates = await run_in_threadpool(
            _analyze_pipeline, audio, sr, target_duration, energy_preference, strictness
        )

        if not candidates:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"No beat-aligned window found for {target_duration}s "
                    f"(source={source_duration:.1f}s, bpm={analysis.bpm:.1f}). "
                    "Try a target within ±1 bar of a natural phrase boundary."
                ),
            )

        # ── Step 3: LLM selection or manual override ───────────────────────────
        used_fallback = False
        if chosen_window_index is not None:
            idx = min(max(chosen_window_index, 0), len(candidates) - 1)
            chosen = candidates[idx]
            chosen_idx = idx
            reasoning = f"Manual override: candidate {idx} selected by user."
            logger.info("auto_trim: manual override → candidate %d [%.2f–%.2f]s", idx, chosen.start, chosen.end)
        else:
            chosen, reasoning, used_fallback = await select_window(
                candidates, energy_preference, user_description
            )
            # Find chosen index by matching start/end
            chosen_idx = next(
                (i for i, c in enumerate(candidates) if c.start == chosen.start and c.end == chosen.end),
                0,
            )

        # ── Step 3b: LLM loop arrangement (Phase 16) ──────────────────────────
        # Only called when the chosen window requires looping AND we have enough
        # segments for intelligent restructuring.
        loop_arrangement = None
        if chosen.needs_loop and len(analysis.segments) >= 3:
            from agents.auto_edit_agent import plan_loop_arrangement
            seg_info = [
                {
                    "index": i,
                    "label": s.label,
                    "duration": round(s.end - s.start, 3),
                }
                for i, s in enumerate(analysis.segments)
            ]
            loop_arrangement = await plan_loop_arrangement(seg_info, target_duration)
            logger.info("auto_trim: LLM loop arrangement = %s", loop_arrangement)

        # ── Step 4: trim + encode ──────────────────────────────────────────────
        data, actual_dur, has_click, cut_amp = await run_in_threadpool(
            _trim_encode_pipeline, audio, sr, ch, chosen, target_duration, fmt,
            analysis.bpm, crossfade_beats, analysis, loop_arrangement,
        )

    finally:
        os.unlink(path)

    # ── Quality metrics ────────────────────────────────────────────────────────
    beat_dev_ms = max(
        _nearest_beat_deviation_ms(chosen.start, analysis.beat_times),
        _nearest_beat_deviation_ms(chosen.end, analysis.beat_times),
    )
    if beat_dev_ms > 15.0:
        logger.warning(
            "auto_trim: beat deviation %.2fms exceeds 15ms at [%.2f–%.2f]s",
            beat_dev_ms, chosen.start, chosen.end,
        )

    quality_parts = []
    if chosen.needs_loop:
        loop_multiplier = target_duration / max(source_duration, 0.001)
        quality_parts.append(f"Source looped {loop_multiplier:.1f}×")
    if analysis.used_beat_fallback:
        quality_parts.append("No beat grid detected — used evenly-spaced 120 BPM anchors")
    if has_click:
        quality_parts.append(f"Potential click at cut (amp={cut_amp:.3f})")
    quality_warning = "; ".join(quality_parts) or None

    logger.info(
        "auto_trim: bpm=%.1f window=[%.2f–%.2f]s actual=%.3fs dev=%.2fms "
        "looped=%s fallback=%s chosen_idx=%d warning=%r",
        analysis.bpm, chosen.start, chosen.end, actual_dur,
        beat_dev_ms, chosen.needs_loop, used_fallback, chosen_idx, quality_warning,
    )

    # ── Build JSON response ────────────────────────────────────────────────────
    audio_b64 = base64.b64encode(data).decode("ascii")
    candidates_payload = _windows_to_payload(candidates)

    # Keep X-AIME-* headers for backward compat (existing UI code still reads them)
    expose = (
        "X-AIME-BPM,X-AIME-Window-Start,X-AIME-Window-End,"
        "X-AIME-Actual-Duration,X-AIME-Beat-Dev-MS,X-AIME-Was-Looped,"
        "X-AIME-Used-Fallback,X-AIME-Reasoning,X-AIME-Quality-Warning"
    )
    compat_headers = {
        "X-AIME-BPM":             str(round(analysis.bpm, 1)),
        "X-AIME-Window-Start":    str(chosen.start),
        "X-AIME-Window-End":      str(chosen.end),
        "X-AIME-Actual-Duration": str(actual_dur),
        "X-AIME-Beat-Dev-MS":     str(beat_dev_ms),
        "X-AIME-Was-Looped":      "true" if chosen.needs_loop else "false",
        "X-AIME-Used-Fallback":   "true" if used_fallback else "false",
        "X-AIME-Reasoning":       urllib.parse.quote(reasoning or "")[:500],
        "X-AIME-Quality-Warning": urllib.parse.quote(quality_warning or "")[:300],
        "Access-Control-Expose-Headers": expose,
    }

    return JSONResponse(
        content={
            "audio_b64": audio_b64,
            "audio_format": fmt,
            "chosen_index": chosen_idx,
            "window_start": chosen.start,
            "window_end": chosen.end,
            "actual_duration": actual_dur,
            "bpm": round(analysis.bpm, 1),
            "beat_deviation_ms": beat_dev_ms,
            "was_looped": chosen.needs_loop,
            "used_fallback": used_fallback,
            "agent_reasoning": reasoning or None,
            "user_description": user_description or None,
            "quality_warning": quality_warning,
            "candidates": candidates_payload,
        },
        headers=compat_headers,
    )


@router.post("/save")
async def save_auto_edit(
    audio_file: UploadFile = File(..., description="Processed audio blob from the browser"),
    user_id: str = Form(...),
    project_id: str = Form(...),
    operation_params: str = Form(
        "{}",
        description=(
            "JSON string with trim metadata: "
            "{target_duration, energy_preference, chosen_window_start, "
            "chosen_window_end, actual_duration, was_looped, agent_reasoning, bpm}"
        ),
    ),
    source_url: str = Form(""),
    output_format: str = Form("mp3"),
):
    """
    Persist a processed Auto Trim result to Supabase Storage and ``editing_table``.

    No re-processing — the audio the browser previewed is uploaded as-is.
    """
    fmt = _validate_format(output_format)

    data = await audio_file.read()
    if not data:
        raise HTTPException(status_code=422, detail="audio_file is empty")

    try:
        op_params = json.loads(operation_params)
    except Exception:
        op_params = {}

    result = await run_in_threadpool(
        _upload_and_insert,
        data=data,
        user_id=user_id,
        project_id=project_id,
        op_params=op_params,
        source_url=source_url,
        fmt=fmt,
    )
    return JSONResponse(result)
