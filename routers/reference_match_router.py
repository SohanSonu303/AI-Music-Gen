"""
Reference Track Matching Router
================================
Endpoints for the "Make it sound like THIS song" feature.

Routes
------
  POST /reference-match/analyze      — fast analysis preview (no audio encode)
  POST /reference-match/process      — full pipeline; returns JSON {audio_b64, audio_format, report}
  POST /reference-match/vibe-prompt  — reference only → LLM MusicGPT prompt
  POST /reference-match/save         — upload result to Supabase + insert editing_table row
"""

import base64
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from routers.audio_edit_test_router import (
    _encode_to_bytes,
    _read_audio,
    _resolve_source,
    _upload_result,
    _validate_format,
)
from services.reference_match_service import (
    compute_power_spectrum,
    compute_spectral_correction_db,
    correction_to_eq_bands,
    extract_musical_fingerprint,
    extract_vibe_prompt,
    match_to_reference,
    measure_dynamics_profile,
    measure_stereo_width,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reference-match", tags=["Reference Match"])

_MIN_DURATION_S = 20  # reject reference tracks shorter than this


def _check_min_duration(audio: "np.ndarray", sr: int, label: str = "Reference") -> None:
    """Raise 422 if audio is shorter than the minimum required duration."""
    import numpy as np  # local import avoids linting noise in module scope
    duration = audio.shape[-1] / sr
    if duration < _MIN_DURATION_S:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{label} track is too short ({duration:.1f}s). "
                f"Please use a clip of at least {_MIN_DURATION_S}s for reliable spectral analysis."
            ),
        )


@router.post("/analyze")
async def analyze_reference(
    ref_file: Optional[UploadFile] = File(None, description="Upload reference audio file"),
    ref_url: Optional[str] = Form(None, description="Reference audio URL"),
    target_file: Optional[UploadFile] = File(None, description="Upload your track (optional for preview)"),
    target_url: Optional[str] = Form(None, description="Your track URL (optional for preview)"),
):
    """
    Fast analysis preview — returns fingerprint + projected EQ changes without processing audio.

    If target is omitted, only the reference fingerprint + spectral profile is returned.
    ~0.5–1s response time.
    """
    ref_path = await _resolve_source(ref_file, ref_url, label="ref")
    target_path = None
    has_target = (target_file is not None) or (target_url is not None)
    if has_target:
        target_path = await _resolve_source(target_file, target_url, label="target")

    try:
        ref_audio, sr_ref, _ = _read_audio(ref_path)
        _check_min_duration(ref_audio, sr_ref, "Reference")

        def _run():
            fingerprint = extract_musical_fingerprint(ref_audio, sr_ref)
            spectral = {}
            projected_eq = []

            if has_target and target_path:
                target_audio, sr_tgt, _ = _read_audio(target_path)
                freqs, ref_pwr = compute_power_spectrum(ref_audio, sr_ref)
                # Resample ref spectrum to target SR if needed
                import numpy as np
                if sr_ref != sr_tgt:
                    import librosa
                    ref_mono = ref_audio.mean(axis=0).astype(np.float32)
                    ref_resampled = librosa.resample(ref_mono, orig_sr=sr_ref, target_sr=sr_tgt)
                    ref_for_spec = ref_resampled[np.newaxis, :]
                    freqs, ref_pwr = compute_power_spectrum(ref_for_spec, sr_tgt)
                _, tgt_pwr = compute_power_spectrum(target_audio, sr_tgt)
                _, correction = compute_spectral_correction_db(ref_pwr, tgt_pwr, freqs)
                projected_eq = correction_to_eq_bands(freqs, correction)
                ref_dyn = measure_dynamics_profile(ref_audio, sr_ref)
                tgt_dyn = measure_dynamics_profile(target_audio, sr_tgt)
                ref_width = measure_stereo_width(ref_audio)
                tgt_width = measure_stereo_width(target_audio)
                spectral = {
                    "dynamics_delta_db": round(
                        tgt_dyn["crest_factor_db"] - ref_dyn["crest_factor_db"], 2
                    ),
                    "stereo_width_delta": round(ref_width - tgt_width, 3),
                    "ref_dynamics": ref_dyn,
                    "target_dynamics": tgt_dyn,
                    "ref_stereo_width": ref_width,
                    "target_stereo_width": tgt_width,
                }
            return fingerprint, projected_eq, spectral

        fingerprint, projected_eq, spectral = await run_in_threadpool(_run)
    finally:
        os.unlink(ref_path)
        if target_path:
            os.unlink(target_path)

    return JSONResponse({
        "reference_fingerprint": fingerprint,
        "projected_eq_bands":    projected_eq,
        **spectral,
    })


@router.post("/process")
async def process_reference_match(
    ref_file: Optional[UploadFile] = File(None, description="Upload reference audio file"),
    ref_url: Optional[str] = Form(None, description="Reference audio URL"),
    target_file: Optional[UploadFile] = File(None, description="Upload your track"),
    target_url: Optional[str] = Form(None, description="Your track URL"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    """
    Apply the reference track's sonic character to the target track.

    Response shape:
    {
      "audio_b64":    "<base64 string>",
      "audio_format": "mp3",
      "report": {
        "eq_bands_applied":        [{freq, gain_db, q}, ...],
        "dynamics":                {ref, target_before, target_after},
        "stereo_width":            {ref, target_before, target_after},
        "reference_fingerprint":   {bpm, key, mode},
        "target_fingerprint":      {bpm, key, mode},
        "changes_summary":         [str, ...]
      }
    }
    """
    fmt = _validate_format(output_format)
    ref_path    = await _resolve_source(ref_file, ref_url, label="ref")
    target_path = await _resolve_source(target_file, target_url, label="target")

    try:
        ref_audio,    sr_ref, _      = _read_audio(ref_path)
        target_audio, sr_target, ch  = _read_audio(target_path)
        _check_min_duration(ref_audio, sr_ref, "Reference")

        processed, report = await run_in_threadpool(
            match_to_reference, target_audio, sr_target, ref_audio, sr_ref
        )
        data = _encode_to_bytes(processed, sr_target, ch, fmt)
    finally:
        os.unlink(ref_path)
        os.unlink(target_path)

    audio_b64 = base64.b64encode(data).decode("utf-8")
    logger.info(
        "reference-match/process: eq_bands=%d  fmt=%s",
        len(report.get("eq_bands_applied", [])), fmt,
    )
    return JSONResponse({"audio_b64": audio_b64, "audio_format": fmt, "report": report})


@router.post("/vibe-prompt")
async def vibe_prompt(
    ref_file: Optional[UploadFile] = File(None, description="Upload reference audio file"),
    ref_url: Optional[str] = Form(None, description="Reference audio URL"),
):
    """
    Analyse a reference track and return a MusicGPT-ready generation prompt.

    The LLM extracts BPM, key, spectral character, and mood — then writes
    a vivid prompt you can paste directly into the music generator.

    Response: { "prompt": str, "fingerprint": {bpm, key, mode} }
    """
    ref_path = await _resolve_source(ref_file, ref_url, label="ref")
    try:
        ref_audio, sr_ref, _ = _read_audio(ref_path)
        _check_min_duration(ref_audio, sr_ref, "Reference")
        result = await extract_vibe_prompt(ref_audio, sr_ref)
    finally:
        os.unlink(ref_path)

    logger.info("reference-match/vibe-prompt: bpm=%.1f key=%s %s",
                result["fingerprint"]["bpm"],
                result["fingerprint"]["key"],
                result["fingerprint"]["mode"])
    return JSONResponse(result)


@router.post("/save")
async def save_reference_match(
    audio_file: UploadFile = File(..., description="The processed audio blob from the browser"),
    user_id: str = Form(...),
    project_id: str = Form(...),
    operation_params: str = Form("{}", description="JSON string with matching report"),
    source_url: str = Form(""),
    output_format: str = Form("mp3"),
):
    """Upload the matched audio to Supabase Storage and insert editing_table row."""
    fmt = _validate_format(output_format)
    data = await audio_file.read()
    if not data:
        raise HTTPException(status_code=422, detail="audio_file is empty")

    try:
        op_params = json.loads(operation_params)
    except Exception:
        op_params = {}

    result = await run_in_threadpool(
        _upload_result,
        data=data,
        user_id=user_id,
        project_id=project_id,
        op="reference_match",
        op_params=op_params,
        source_url=source_url,
        fmt=fmt,
    )
    return JSONResponse(result)
