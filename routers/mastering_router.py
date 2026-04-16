"""
AI Platform Mastering Router
==============================
Endpoints for the platform mastering feature.

Routes
------
  GET  /master/platforms  — list all platform profiles with loudness targets
  POST /master/process    — apply mastering chain; returns JSON {audio_b64, audio_format, report}
  POST /master/save       — upload mastered audio to Supabase Storage + insert editing_table row
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
from services.mastering_service import PLATFORM_PROFILES, master_for_platform

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/master", tags=["Mastering"])


@router.get("/platforms")
def list_platforms():
    """Return all platform profiles with loudness targets."""
    platforms = [
        {
            "id": pid,
            "name": p["name"],
            "target_lufs": p["target_lufs"],
            "true_peak_db": p["true_peak_db"],
            "description": p["description"],
            "icon": p["icon"],
        }
        for pid, p in PLATFORM_PROFILES.items()
    ]
    return JSONResponse({"platforms": platforms})


@router.post("/process")
async def process_mastering(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    platform: str = Form(..., description="Platform: spotify | youtube | tiktok | podcast | apple | soundcloud"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    """
    Apply the platform mastering chain and return base64-encoded audio + report.

    Response shape:
    {
      "audio_b64":    "<base64 string>",
      "audio_format": "mp3",
      "report": {
        "platform":          "Spotify",
        "target_lufs":       -14.0,
        "true_peak_ceiling": -1.0,
        "before": { "lufs": -18.2, "true_peak_db": -0.3 },
        "after":  { "lufs": -14.0, "true_peak_db": -1.0 },
        "gain_applied_db":   3.8,
        "changes":           ["Music EQ: …", "Glue compression: …", …]
      }
    }
    """
    if platform not in PLATFORM_PROFILES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown platform '{platform}'. Valid: {list(PLATFORM_PROFILES)}",
        )
    fmt = _validate_format(output_format)
    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        mastered, report = await run_in_threadpool(master_for_platform, audio, sr, platform)
        data = _encode_to_bytes(mastered, sr, ch, fmt)
    finally:
        os.unlink(path)

    audio_b64 = base64.b64encode(data).decode("utf-8")
    logger.info(
        "master/process: platform=%s  before=%.1fLUFS  after=%.1fLUFS  fmt=%s",
        platform, report["before"]["lufs"], report["after"]["lufs"], fmt,
    )
    return JSONResponse({"audio_b64": audio_b64, "audio_format": fmt, "report": report})


@router.post("/save")
async def save_mastered(
    audio_file: UploadFile = File(..., description="The mastered audio blob from the browser"),
    user_id: str = Form(...),
    project_id: str = Form(...),
    operation_params: str = Form("{}", description="JSON string with mastering report"),
    source_url: str = Form(""),
    output_format: str = Form("mp3"),
):
    """
    Upload the already-mastered audio blob to Supabase Storage and insert
    one editing_table row. No re-processing happens here.
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
        _upload_result,
        data=data,
        user_id=user_id,
        project_id=project_id,
        op="mastering",
        op_params=op_params,
        source_url=source_url,
        fmt=fmt,
    )
    return JSONResponse(result)
