"""
Celery task for MusicGPT stem extraction.

process_extraction_task  → queue: musicgpt_album
    Router pre-inserts an audio_extractions row with status=QUEUED and a stable UUID job_id,
    saves the uploaded file to a temp path, then enqueues this task.
    The task calls MusicGPT /Extraction, updates the row with real task_id/conversion_id,
    polls /byId until completion, downloads each stem, uploads to Supabase Storage,
    then marks the row COMPLETED. Temp file is always cleaned up in finally.
"""
import json
import logging
import os
import time
from urllib.parse import urlparse

import httpx

from celery_app import celery_app
from supabase_client import supabase

logger = logging.getLogger(__name__)

MUSICGPT_BASE_URL = "https://api.musicgpt.com/api/public/v1"
MUSICGPT_API_KEY = os.environ.get("MUSICGPT_API_KEY")
EXTRACTION_BUCKET = os.environ.get("EXTRACTION_BUCKET_NAME", os.environ.get("BUCKET_NAME", "music-generated"))

EXTRACTION_TABLE = "audio_extractions"
POLL_INTERVAL = 10
MAX_POLL_SECONDS = 500
TERMINAL_STATUSES = {"COMPLETED", "ERROR", "FAILED"}
CONVERSION_TYPE = "EXTRACTION"

STEM_COLUMN = {
    "vocals": "vocals_url",
    "drums":  "drums_url",
    "bass":   "bass_url",
    "piano":  "piano_url",
    "guitar": "guitar_url",
}


def _mark_failed(job_id: str, message: str) -> None:
    supabase.table(EXTRACTION_TABLE).update({
        "status": "FAILED",
        "error_message": message,
    }).eq("id", job_id).execute()


def _cleanup(temp_path: str | None) -> None:
    if not temp_path:
        return
    try:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            logger.info("Removed temp extraction file: path=%s", temp_path)
    except Exception as exc:
        logger.warning("Failed to remove temp file %s: %s", temp_path, exc)


def _ext_from_url(url: str) -> str:
    return "wav" if urlparse(url).path.lower().endswith(".wav") else "mp3"


def _content_type_for_file(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".ogg"):
        return "audio/ogg"
    return "audio/mpeg"


@celery_app.task(
    name="tasks.extraction_task.process_extraction_task",
    queue="musicgpt_album",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def process_extraction_task(
    self,
    job_id: str,
    temp_file_path: str,
    filename: str,
    stems: list,
    user_id: str,
    project_id: str,
):
    """
    job_id        : UUID stored as audio_extractions.id (returned to client for polling)
    temp_file_path: local path of the uploaded audio file saved by the router
    filename      : original upload filename (used for content-type detection)
    stems         : list of stem names to extract, e.g. ["vocals", "drums", "bass"]
    user_id       : used for storage path
    project_id    : used for storage path
    """
    logger.info(
        "Celery: extraction started — job_id=%s stems=%s filename=%s",
        job_id, stems, filename,
    )

    # ── Step 1: Submit to MusicGPT /Extraction ───────────────────────────────
    result: dict | None = None
    try:
        headers = {"Authorization": MUSICGPT_API_KEY, "accept": "application/json"}
        with open(temp_file_path, "rb") as audio_file:
            files = {"audio_file": (filename, audio_file, _content_type_for_file(filename))}
            data = {"stems": json.dumps(stems), "audio_url": ""}

            with httpx.Client(timeout=httpx.Timeout(60.0, read=120.0)) as client:
                response = client.post(
                    f"{MUSICGPT_BASE_URL}/Extraction",
                    headers=headers,
                    files=files,
                    data=data,
                )

        if not response.is_success:
            logger.error(
                "MusicGPT /Extraction error %s: %s", response.status_code, response.text
            )
        response.raise_for_status()
        result = response.json()

    except httpx.HTTPError as exc:
        logger.error("Extraction submit HTTP error: job_id=%s error=%s", job_id, exc)
        _mark_failed(job_id, str(exc))
        _cleanup(temp_file_path)
        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        if status_code is not None and 400 <= status_code < 500:
            return
        try:
            raise self.retry(exc=exc)
        except Exception:
            return
    except Exception as exc:
        logger.error("Extraction submit error: job_id=%s error=%s", job_id, exc)
        _mark_failed(job_id, str(exc))
        _cleanup(temp_file_path)
        return

    if not result:
        _mark_failed(job_id, "MusicGPT returned no payload")
        _cleanup(temp_file_path)
        return

    musicgpt_task_id = result.get("task_id")
    conversion_id = result.get("conversion_id")
    if not conversion_id:
        _mark_failed(job_id, f"MusicGPT response missing conversion_id: {result}")
        _cleanup(temp_file_path)
        return

    logger.info(
        "MusicGPT Extraction queued: job_id=%s task_id=%s conversion_id=%s eta=%s",
        job_id, musicgpt_task_id, conversion_id, result.get("eta"),
    )

    # ── Step 2: Update DB with real MusicGPT IDs ─────────────────────────────
    supabase.table(EXTRACTION_TABLE).update({
        "task_id": musicgpt_task_id,
        "conversion_id": conversion_id,
        "status": "IN_QUEUE",
    }).eq("id", job_id).execute()

    # ── Step 3: Poll /byId until terminal status ──────────────────────────────
    headers = {"Authorization": MUSICGPT_API_KEY}
    params = {"conversionType": CONVERSION_TYPE, "conversion_id": conversion_id}
    elapsed = 0

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            while elapsed < MAX_POLL_SECONDS:
                poll_resp = client.get(
                    f"{MUSICGPT_BASE_URL}/byId",
                    headers=headers,
                    params=params,
                )
                poll_resp.raise_for_status()
                payload = poll_resp.json()
                conversion = payload.get("conversion", payload)
                status = conversion.get("status")

                if not status:
                    raise ValueError(
                        f"Missing status in poll response for conversion_id={conversion_id}"
                    )

                logger.info(
                    "Extraction poll [%ds]: job_id=%s conversion_id=%s status=%s",
                    elapsed, job_id, conversion_id, status,
                )

                if status not in TERMINAL_STATUSES:
                    time.sleep(POLL_INTERVAL)
                    elapsed += POLL_INTERVAL
                    continue

                # ── Terminal status reached ───────────────────────────────────
                if status == "COMPLETED":
                    db_update = _download_and_store(
                        client, conversion, job_id, conversion_id, stems, user_id, project_id
                    )
                    db_update["status"] = "COMPLETED"
                    db_update["error_message"] = None
                else:
                    logger.error(
                        "MusicGPT Extraction failed: job_id=%s status=%s message=%s",
                        job_id, status, conversion.get("message"),
                    )
                    db_update = {
                        "status": status,
                        "error_message": conversion.get("message") or f"MusicGPT returned status {status}",
                    }

                supabase.table(EXTRACTION_TABLE).update(db_update).eq("id", job_id).execute()
                logger.info("Extraction done: job_id=%s status=%s", job_id, status)
                _cleanup(temp_file_path)
                return

        # Timed out
        logger.warning(
            "Extraction polling timed out after %ds: job_id=%s conversion_id=%s",
            MAX_POLL_SECONDS, job_id, conversion_id,
        )
        _mark_failed(job_id, f"Polling timed out after {MAX_POLL_SECONDS} seconds")

    except Exception as exc:
        logger.error("Extraction poll/store error: job_id=%s error=%s", job_id, exc)
        _mark_failed(job_id, str(exc))

    finally:
        _cleanup(temp_file_path)


def _parse_stem_urls(conversion_path: str) -> dict:
    """
    MusicGPT returns conversion_path as a string like:
      "https://lalals.s3.amazonaws.com/{\"vocals\": \"https://...\", \"drums\": \"https://...\"}"

    Extract the JSON object starting at the first '{' and parse it into a stem→url dict.
    """
    idx = conversion_path.find("{")
    if idx == -1:
        return {}
    try:
        return json.loads(conversion_path[idx:])
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse stem URLs from conversion_path: %s", exc)
        return {}


def _download_and_store(
    client: httpx.Client,
    conversion: dict,
    job_id: str,
    conversion_id: str,
    stems: list,
    user_id: str,
    project_id: str,
) -> dict:
    """Download each stem from MusicGPT and upload to Supabase Storage. Returns DB update dict."""
    db_update: dict = {}

    # MusicGPT embeds stem URLs as a JSON object inside the conversion_path string.
    # Use MP3 (conversion_path); conversion_path_wav has higher-quality WAV alternatives.
    stem_urls: dict = _parse_stem_urls(conversion.get("conversion_path", ""))

    if not stem_urls:
        raise ValueError(
            f"COMPLETED but no stem URLs found in conversion_path. "
            f"Raw value: {conversion.get('conversion_path')!r}"
        )

    for stem, url in stem_urls.items():
        col = STEM_COLUMN.get(stem)
        if not col:
            logger.warning("Unknown stem '%s' in MusicGPT response — skipping", stem)
            continue

        logger.info("Downloading stem '%s': job_id=%s url=%s", stem, job_id, url)
        audio_resp = client.get(url)
        audio_resp.raise_for_status()

        ext = _ext_from_url(url)
        content_type = "audio/wav" if ext == "wav" else "audio/mpeg"
        storage_path = f"{user_id}/{project_id}/{job_id}/{stem}.{ext}"

        supabase.storage.from_(EXTRACTION_BUCKET).upload(
            storage_path,
            audio_resp.content,
            {"content-type": content_type},
        )
        public_url = supabase.storage.from_(EXTRACTION_BUCKET).get_public_url(storage_path)
        db_update[col] = public_url
        logger.info("Uploaded stem '%s' -> %s", stem, public_url)

    return db_update
