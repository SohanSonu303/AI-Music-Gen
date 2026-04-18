import io
import json
import tempfile
import os
import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4

import httpx
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pedalboard.io import AudioFile
from pedalboard import (
    PeakFilter,
    HighShelfFilter,
    LowShelfFilter,
    HighpassFilter,
    Compressor,
    Limiter,
    LadderFilter,
    Reverb,
    Chorus,
    Bitcrush,
)

from services.warmth_service import apply_warmth, get_analysis_report
from services.enhancer_service import apply_preset, get_presets_list

from supabase_client import supabase

STORAGE_BUCKET = os.environ.get("BUCKET_NAME", "music-generated")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test-edit", tags=["Audio Edit Testing"])

_HTML = Path(__file__).parent.parent / "audio_edit_test.html"


@router.get("/ui", include_in_schema=False)
def test_ui():
    return FileResponse(_HTML, media_type="text/html")


async def _resolve_source(file: Optional[UploadFile], url: Optional[str], label: str = "audio") -> str:
    """
    Accepts either an uploaded file or a URL — exactly one must be provided.
    Returns the path to a temp file. Caller is responsible for deleting it.
    """
    if file is None and url is None:
        raise HTTPException(status_code=422, detail=f"Provide either '{label}_file' or '{label}_url', not neither")
    if file is not None and url is not None:
        raise HTTPException(status_code=422, detail=f"Provide either '{label}_file' or '{label}_url', not both")

    if file is not None:
        suffix = os.path.splitext(file.filename)[1] if file.filename else ".mp3"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".mp3")
        tmp.write(await file.read())
        tmp.flush()
        tmp.close()
        return tmp.name

    # URL path
    resp = httpx.get(url, follow_redirects=True, timeout=30)
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Failed to download {label}: HTTP {resp.status_code}")
    content_type = resp.headers.get("content-type", "").lower()
    url_lower = url.lower()
    if "wav" in url_lower or "wav" in content_type:
        suffix = ".wav"
    elif "flac" in url_lower or "flac" in content_type:
        suffix = ".flac"
    else:
        suffix = ".mp3"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(resp.content)
    tmp.flush()
    tmp.close()
    return tmp.name


def _read_audio(path: str) -> tuple[np.ndarray, int, int]:
    """Read audio file via pedalboard. Returns (audio, sample_rate, num_channels)."""
    with AudioFile(path) as f:
        audio = f.read(f.frames)  # shape: (channels, samples), dtype: float32
        return audio, f.samplerate, f.num_channels


def _ms_to_samples(ms: int, sr: int) -> int:
    return int(ms * sr / 1000)


def _duration_ms(audio: np.ndarray, sr: int) -> float:
    return audio.shape[1] / sr * 1000


def _encode_to_bytes(audio: np.ndarray, sr: int, num_channels: int, fmt: str = "mp3") -> bytes:
    """Encode numpy audio array to bytes. Single encode — no intermediate files."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{fmt}")
    tmp.close()
    try:
        quality = "V0" if fmt == "mp3" else None
        kwargs = {"samplerate": sr, "num_channels": num_channels}
        if quality:
            kwargs["quality"] = quality
        with AudioFile(tmp.name, "w", **kwargs) as f:
            f.write(audio)
        with open(tmp.name, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp.name)


def _validate_format(fmt: str) -> str:
    fmt = fmt.strip().lower()
    if fmt not in ("mp3", "wav"):
        raise HTTPException(status_code=422, detail="output_format must be 'mp3' or 'wav'")
    return fmt


def _bytes_response(data: bytes, fmt: str = "mp3") -> StreamingResponse:
    media_type = "audio/mpeg" if fmt == "mp3" else "audio/wav"
    return StreamingResponse(io.BytesIO(data), media_type=media_type)


@router.post("/cut")
async def test_cut(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    start_ms: int = Form(..., ge=0, description="Start position in milliseconds"),
    end_ms: int = Form(..., description="End position in milliseconds"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    if end_ms <= start_ms:
        raise HTTPException(status_code=422, detail="end_ms must be greater than start_ms")
    fmt = _validate_format(output_format)

    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        start = _ms_to_samples(start_ms, sr)
        end = _ms_to_samples(end_ms, sr)
        result = audio[:, start:end]
        logger.info("cut: %dms→%dms (output=%.0fms, fmt=%s)", start_ms, end_ms, _duration_ms(result, sr), fmt)
        data = _encode_to_bytes(result, sr, ch, fmt)
    finally:
        os.unlink(path)

    return _bytes_response(data, fmt)


@router.post("/fade")
async def test_fade(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    fade_in_ms: int = Form(0, ge=0, description="Fade-in duration in milliseconds"),
    fade_out_ms: int = Form(0, ge=0, description="Fade-out duration in milliseconds"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    if fade_in_ms == 0 and fade_out_ms == 0:
        raise HTTPException(status_code=422, detail="At least one of fade_in_ms or fade_out_ms must be > 0")
    fmt = _validate_format(output_format)

    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        result = audio.copy()

        if fade_in_ms > 0:
            n = min(_ms_to_samples(fade_in_ms, sr), result.shape[1])
            result[:, :n] *= np.linspace(0.0, 1.0, n, dtype=np.float32)

        if fade_out_ms > 0:
            n = min(_ms_to_samples(fade_out_ms, sr), result.shape[1])
            result[:, -n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)

        logger.info("fade: in=%dms out=%dms fmt=%s", fade_in_ms, fade_out_ms, fmt)
        data = _encode_to_bytes(result, sr, ch, fmt)
    finally:
        os.unlink(path)

    return _bytes_response(data, fmt)


@router.post("/loop")
async def test_loop(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    count: int = Form(..., ge=2, le=10, description="Number of times to repeat (2–10)"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    fmt = _validate_format(output_format)
    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        result = np.tile(audio, (1, count))
        logger.info("loop: count=%d output=%.0fms fmt=%s", count, _duration_ms(result, sr), fmt)
        data = _encode_to_bytes(result, sr, ch, fmt)
    finally:
        os.unlink(path)

    return _bytes_response(data, fmt)


@router.post("/mix")
async def test_mix(
    file1: Optional[UploadFile] = File(None, description="Upload base audio file"),
    url1: Optional[str] = Form(None, description="Base audio URL"),
    file2: Optional[UploadFile] = File(None, description="Upload audio file to mix on top"),
    url2: Optional[str] = Form(None, description="Audio URL to mix on top"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    fmt = _validate_format(output_format)
    path1 = await _resolve_source(file1, url1, label="audio1")
    path2 = await _resolve_source(file2, url2, label="audio2")
    try:
        a1, sr1, ch1 = _read_audio(path1)
        a2, sr2, ch2 = _read_audio(path2)

        # Pad shorter to match longer
        max_len = max(a1.shape[1], a2.shape[1])
        if a1.shape[1] < max_len:
            a1 = np.pad(a1, ((0, 0), (0, max_len - a1.shape[1])))
        if a2.shape[1] < max_len:
            a2 = np.pad(a2, ((0, 0), (0, max_len - a2.shape[1])))

        result = np.clip(a1 + a2, -1.0, 1.0).astype(np.float32)
        logger.info("mix: output=%.0fms fmt=%s", _duration_ms(result, sr1), fmt)
        data = _encode_to_bytes(result, sr1, ch1, fmt)
    finally:
        os.unlink(path1)
        os.unlink(path2)

    return _bytes_response(data, fmt)


@router.post("/overlay")
async def test_overlay(
    file1: Optional[UploadFile] = File(None, description="Upload base audio file"),
    url1: Optional[str] = Form(None, description="Base audio URL"),
    file2: Optional[UploadFile] = File(None, description="Upload audio file to overlay"),
    url2: Optional[str] = Form(None, description="Audio URL to overlay"),
    position_ms: int = Form(..., ge=0, description="Position in base track to place overlay (ms)"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    fmt = _validate_format(output_format)
    path1 = await _resolve_source(file1, url1, label="audio1")
    path2 = await _resolve_source(file2, url2, label="audio2")
    try:
        base, sr1, ch1 = _read_audio(path1)
        overlay, sr2, ch2 = _read_audio(path2)

        pos = _ms_to_samples(position_ms, sr1)
        end_pos = pos + overlay.shape[1]

        result = base.copy()
        # Extend base if overlay exceeds it
        if end_pos > result.shape[1]:
            result = np.pad(result, ((0, 0), (0, end_pos - result.shape[1])))

        result[:, pos:pos + overlay.shape[1]] += overlay
        result = np.clip(result, -1.0, 1.0).astype(np.float32)

        logger.info("overlay: position=%dms output=%.0fms fmt=%s", position_ms, _duration_ms(result, sr1), fmt)
        data = _encode_to_bytes(result, sr1, ch1, fmt)
    finally:
        os.unlink(path1)
        os.unlink(path2)

    return _bytes_response(data, fmt)


@router.post("/split")
async def test_split(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    split_ms: int = Form(..., ge=0, description="Split point in milliseconds"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    fmt = _validate_format(output_format)
    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        split_sample = _ms_to_samples(split_ms, sr)

        if split_sample >= audio.shape[1]:
            raise HTTPException(
                status_code=422,
                detail=f"split_ms ({split_ms}) must be less than audio duration ({_duration_ms(audio, sr):.0f}ms)"
            )

        part1 = audio[:, :split_sample]
        logger.info("split: at=%dms → part1=%.0fms part2=%.0fms fmt=%s",
                     split_ms, _duration_ms(part1, sr), _duration_ms(audio[:, split_sample:], sr), fmt)
        data = _encode_to_bytes(part1, sr, ch, fmt)
    finally:
        os.unlink(path)

    return _bytes_response(data, fmt)


@router.post("/eq")
async def test_eq(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    freq: int = Form(..., ge=20, le=20000, description="Center frequency in Hz"),
    gain: float = Form(..., ge=-20.0, le=20.0, description="Gain in dB (-20 to +20)"),
    q: float = Form(1.41, gt=0, description="Q factor / bandwidth (default 1.41 ≈ 1 octave)"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    fmt = _validate_format(output_format)
    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        eq = PeakFilter(cutoff_frequency_hz=float(freq), gain_db=float(gain), q=float(q))
        result = eq.process(audio, sr)
        logger.info("eq: freq=%dHz gain=%.1fdB q=%.2f fmt=%s", freq, gain, q, fmt)
        data = _encode_to_bytes(result, sr, ch, fmt)
    finally:
        os.unlink(path)

    return _bytes_response(data, fmt)


@router.post("/warmth")
async def test_warmth(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    intensity: float = Form(0.5, ge=0.0, le=1.0, description="Warmth intensity 0.0 (subtle) → 1.0 (heavy analog)"),
    vocal_mode: bool = Form(False, description="Enable vocal-optimised processing: sibilance de-essing, chest resonance, room reverb, gentle compression"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    fmt = _validate_format(output_format)
    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        result = await run_in_threadpool(apply_warmth, audio, sr, intensity, vocal_mode)
        data = _encode_to_bytes(result, sr, ch, fmt)
    finally:
        os.unlink(path)

    return _bytes_response(data, fmt)


@router.post("/warmth/analyze")
async def analyze_warmth(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    intensity: float = Form(0.5, ge=0.0, le=1.0, description="Intensity to simulate when computing planned adjustments"),
    vocal_mode: bool = Form(False, description="Simulate vocal mode parameters"),
):
    path = await _resolve_source(file, url)
    try:
        audio, sr, _ = _read_audio(path)
        report = await run_in_threadpool(get_analysis_report, audio, sr, intensity, vocal_mode)
    finally:
        os.unlink(path)

    return JSONResponse(report)


@router.get("/enhance/presets")
async def list_enhance_presets():
    """Return metadata for all 6 style presets — no audio required."""
    return JSONResponse({"presets": get_presets_list()})


@router.post("/enhance")
async def test_enhance(
    file: Optional[UploadFile] = File(None, description="Upload audio file"),
    url: Optional[str] = Form(None, description="Audio URL to download"),
    preset: str = Form("lofi", description="Preset id: lofi | edm | cinematic | pop | chill | vintage"),
    intensity: float = Form(0.7, ge=0.0, le=1.0, description="Blend intensity 0.0 (dry) → 1.0 (full preset)"),
    output_format: str = Form("mp3", description="Output format: mp3 or wav"),
):
    fmt  = _validate_format(output_format)
    path = await _resolve_source(file, url)
    try:
        audio, sr, ch = _read_audio(path)
        try:
            result = await run_in_threadpool(apply_preset, audio, sr, preset, intensity)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        data = _encode_to_bytes(result, sr, ch, fmt)
    finally:
        os.unlink(path)

    return _bytes_response(data, fmt)


def _upload_result(data: bytes, user_id: str, project_id: str, op: str,
                   op_params: dict, source_url: str, fmt: str) -> dict:
    """
    Plain def — runs in thread pool.
    Reads duration from the already-processed bytes, uploads to Supabase Storage,
    inserts one editing_table row. No audio re-processing happens here.
    """
    # get duration from the processed bytes
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
        "operation": op,
        "operation_params": op_params,
        "source_url": source_url or "unknown",
        "output_url": output_url,
        "output_format": fmt,
        "output_duration": duration,
    }).execute()

    logger.info("save: op=%s user=%s project=%s -> %s (%.3fs)", op, user_id, project_id, output_url, duration)
    return {"id": job_id, "output_url": output_url, "output_duration": duration}


@router.post("/save")
async def save_edit(
    audio_file: UploadFile = File(..., description="The processed audio blob from the browser"),
    user_id: str = Form(...),
    project_id: str = Form(...),
    operation: str = Form(..., description="cut|fade|loop|split|eq|mix|overlay"),
    operation_params: str = Form("{}", description="JSON string of operation params"),
    source_url: str = Form(""),
    output_format: str = Form("mp3"),
):
    """
    Receives the already-processed audio blob directly from the browser.
    No re-processing — what the user previewed is exactly what gets saved.
    """
    op = operation.strip().lower()
    if op not in ("cut", "fade", "loop", "split", "eq", "mix", "overlay", "warmth", "enhance"):
        raise HTTPException(status_code=422, detail=f"Unknown operation: {op}")
    fmt = _validate_format(output_format)

    # read the processed audio bytes (async — UploadFile.read())
    data = await audio_file.read()
    if not data:
        raise HTTPException(status_code=422, detail="audio_file is empty")

    try:
        op_params = json.loads(operation_params)
    except Exception:
        op_params = {}

    result = await run_in_threadpool(
        _upload_result,
        data=data, user_id=user_id, project_id=project_id,
        op=op, op_params=op_params, source_url=source_url, fmt=fmt,
    )
    return JSONResponse(result)
