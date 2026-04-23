"""
AI Podcast Producer Router
===========================
Routes
------
  POST /podcast/produce   — full pipeline; returns {audio_b64, audio_format, report}
  POST /podcast/save      — upload result to Supabase + insert editing_table row
"""

import base64
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
import os as _os
from services.token_service import require_tokens as _require_tokens


def require_tokens(user_id: str, amount: int, reason: str, job_id=None):
    if _os.environ.get("DEV_BYPASS_AUTH", "").lower() in ("1", "true", "yes"):
        return
    return _require_tokens(user_id, amount, reason, job_id)
from routers.audio_edit_test_router import (
    _encode_to_bytes,
    _read_audio,
    _resolve_source,
    _upload_result,
    _validate_format,
)
from services.podcast_service import produce_podcast

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/podcast", tags=["Podcast Producer"])


@router.post("/produce")
async def produce_podcast_endpoint(
    speech_file: Optional[UploadFile] = File(None, description="Upload speech/podcast audio file"),
    speech_url:  Optional[str]        = Form(None, description="Speech audio URL"),
    music_file:  Optional[UploadFile] = File(None, description="Upload background music file (optional)"),
    music_url:   Optional[str]        = Form(None, description="Background music URL (optional)"),
    noise_reduction:  str   = Form("true",  description="Run vocal isolation + noise gate"),
    voice_eq:         str   = Form("true",  description="Apply voice EQ & leveling chain"),
    add_music:        str   = Form("true",  description="Attach intro/outro music with auto-ducking"),
    duck_db:          float = Form(-18.0,   description="Music duck level in dB (e.g. -18)"),
    intro_duration_s: float = Form(8.0,     description="Intro music duration in seconds"),
    outro_duration_s: float = Form(8.0,     description="Outro music duration in seconds"),
    output_format:    str   = Form("mp3",   description="Output format: mp3 or wav"),
    user: UserContext = Depends(get_current_user),
):
    """
    Produce a podcast episode from raw speech audio.

    Applies noise reduction, voice EQ/leveling, LUFS normalisation to -16 LUFS,
    and optionally attaches background music with automatic speech-ducking.

    ⚠️  If noise_reduction=true, demucs runs synchronously and can take
    5–15 minutes for files > 5 min. For production, migrate to a Celery task.

    Response: { "audio_b64": str, "audio_format": str, "report": {...} }
    """
    require_tokens(str(user.id), token_costs.PODCAST_PRODUCE, "podcast_produce")
    fmt = _validate_format(output_format)

    if speech_file is None and not speech_url:
        raise HTTPException(status_code=422, detail="Provide speech_file or speech_url")

    has_music = music_file is not None or bool(music_url)

    speech_path = await _resolve_source(speech_file, speech_url, label="speech")
    music_path  = await _resolve_source(music_file, music_url, label="music") if has_music else None

    try:
        speech_audio, sr_speech, ch_speech = _read_audio(speech_path)

        music_audio, sr_music = None, None
        if music_path:
            music_audio, sr_music, _ = _read_audio(music_path)

        options = {
            "noise_reduction":  noise_reduction.lower() not in ("false", "0", "no"),
            "voice_eq":         voice_eq.lower()        not in ("false", "0", "no"),
            "add_music":        add_music.lower()       not in ("false", "0", "no"),
            "duck_db":          duck_db,
            "intro_duration_s": intro_duration_s,
            "outro_duration_s": outro_duration_s,
        }

        processed, report = await run_in_threadpool(
            produce_podcast,
            speech_audio, sr_speech,
            music_audio,  sr_music,
            options,
        )
        data = _encode_to_bytes(processed, sr_speech, processed.shape[0], fmt)

    finally:
        import os
        os.unlink(speech_path)
        if music_path:
            os.unlink(music_path)

    audio_b64 = base64.b64encode(data).decode("utf-8")
    logger.info(
        "podcast/produce: duration=%.1fs noise=%s voice_eq=%s music=%s fmt=%s",
        report.get("total_duration_s", 0),
        options["noise_reduction"],
        options["voice_eq"],
        options["add_music"],
        fmt,
    )
    return JSONResponse({"audio_b64": audio_b64, "audio_format": fmt, "report": report})


@router.post("/save")
async def save_podcast(
    audio_file:       UploadFile = File(..., description="The processed podcast audio blob"),
    project_id:       str        = Form(...),
    operation_params: str        = Form("{}", description="JSON string with production report"),
    source_url:       str        = Form(""),
    output_format:    str        = Form("mp3"),
    user: UserContext = Depends(get_current_user),
):
    """Upload the produced episode to Supabase Storage and insert editing_table row."""
    fmt  = _validate_format(output_format)
    data = await audio_file.read()
    if not data:
        raise HTTPException(status_code=422, detail="audio_file is empty")

    try:
        op_params = json.loads(operation_params)
    except Exception:
        op_params = {}

    try:
        from services.project_service import ProjectService
        ProjectService.assert_owns_project(project_id, str(user.id))
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    result = await run_in_threadpool(
        _upload_result,
        data=data,
        user_id=str(user.id),
        project_id=project_id,
        op="podcast_produce",
        op_params=op_params,
        source_url=source_url,
        fmt=fmt,
    )
    return JSONResponse(result)
