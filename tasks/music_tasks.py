"""
Celery tasks for music generation.

submit_and_poll_task  → queue: musicgpt_album
    Handles all single-track MusicGPT submissions
    (generateMusic / inpaint / extend / remix / image_to_song).
    The router pre-inserts music_metadata rows with status=QUEUED and a stable UUID as task_id,
    then enqueues this task. The task calls MusicGPT, updates the rows with the real
    conversion_ids and musicgpt_task_id, then polls until completion and stores the audio.

process_album_track_task  → queue: musicgpt_album
    Submits one album track to MusicGPT, inserts music_metadata rows, updates album_tracks,
    then polls until completion and stores the audio.

Both tasks run in the musicgpt_album queue.
Worker concurrency = MUSICGPT_MAX_PARALLEL (env var, default 1).
Each running worker slot = one track being processed end-to-end.
Bump MUSICGPT_MAX_PARALLEL and restart the worker when upgrading plan.
"""
import os
import time
import tempfile
import logging

import httpx
from celery.exceptions import MaxRetriesExceededError

from celery_app import celery_app
from supabase_client import supabase

logger = logging.getLogger(__name__)

MUSICGPT_BASE_URL = "https://api.musicgpt.com/api/public/v1"
MUSICGPT_API_KEY = os.environ.get("MUSICGPT_API_KEY")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "music-generated")

POLL_INTERVAL_SECONDS = 5
MAX_POLL_DURATION_SECONDS = 300
TERMINAL_STATUSES = {"COMPLETED", "ERROR", "FAILED"}


class MusicGPTValidationError(Exception):
    """Raised for non-retryable MusicGPT validation/client errors."""


def _mark_music_failed(task_id: str, message: str, conversion_id: str | None = None) -> None:
    query = supabase.table("music_metadata").update({"status": "FAILED", "error_message": message}).eq(
        "task_id", task_id
    )
    if conversion_id:
        query = query.eq("conversion_id", conversion_id)
    query.execute()


def _cleanup_temp_image(image_file_path: str | None) -> None:
    if not image_file_path:
        return
    try:
        if os.path.exists(image_file_path):
            os.remove(image_file_path)
            logger.info("Removed temp image file: path=%s", image_file_path)
    except Exception as cleanup_exc:
        logger.warning("Failed to remove temp image file %s: %s", image_file_path, cleanup_exc)


def submit_image_to_song_request(
    client: httpx.Client,
    headers: dict,
    *,
    image_url: str | None = None,
    image_file_path: str | None = None,
    prompt: str | None = None,
    lyrics: str | None = None,
    make_instrumental: bool = False,
    vocal_only: bool = False,
    key: str | None = None,
    bpm: int | None = None,
    voice_id: str | None = None,
    webhook_url: str | None = None,
) -> dict:
    """
    Submit MusicGPT image_to_song request using either image_url or local image_file_path.
    Returns task_id, conversion_id_1, and eta.
    """
    if bool(image_url) == bool(image_file_path):
        raise MusicGPTValidationError("Provide exactly one of image_url or image_file_path")

    form_data: dict[str, str] = {}
    if image_url:
        form_data["image_url"] = image_url
    if prompt:
        form_data["prompt"] = prompt
    if lyrics:
        form_data["lyrics"] = lyrics
    if key:
        form_data["key"] = key
    if bpm is not None:
        form_data["bpm"] = str(bpm)
    if voice_id:
        form_data["voice_id"] = voice_id
    if webhook_url:
        form_data["webhook_url"] = webhook_url

    form_data["make_instrumental"] = "true" if make_instrumental else "false"
    form_data["vocal_only"] = "true" if vocal_only else "false"

    multipart_fields = [(key, (None, value)) for key, value in form_data.items()]

    response: httpx.Response
    if image_file_path:
        file_name = os.path.basename(image_file_path) or "image_upload"
        with open(image_file_path, "rb") as image_file:
            multipart_fields.append(("image_file", (file_name, image_file, "application/octet-stream")))
            response = client.post(
                f"{MUSICGPT_BASE_URL}/image_to_song",
                headers=headers,
                files=multipart_fields,
            )
    else:
        response = client.post(
            f"{MUSICGPT_BASE_URL}/image_to_song",
            headers=headers,
            files=multipart_fields,
        )

    if response.status_code == 422:
        raise MusicGPTValidationError(f"MusicGPT image_to_song validation failed: {response.text}")
    if response.status_code >= 500:
        response.raise_for_status()
    if not response.is_success:
        raise MusicGPTValidationError(f"MusicGPT image_to_song request failed: {response.status_code} {response.text}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise MusicGPTValidationError("MusicGPT image_to_song returned non-JSON response") from exc

    task_id = payload.get("task_id")
    conversion_id_1 = payload.get("conversion_id_1")
    if not task_id or not conversion_id_1:
        raise MusicGPTValidationError(f"MusicGPT image_to_song response missing IDs: {payload}")

    return {
        "task_id": task_id,
        "conversion_id_1": conversion_id_1,
        "conversion_id_2": payload.get("conversion_id_2", ""),
        "eta": payload.get("eta"),
    }


@celery_app.task(
    name="tasks.music_tasks.submit_and_poll_task",
    queue="musicgpt_album",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def submit_and_poll_task(
    self,
    operation: str,
    stable_task_id: str,
    record_ids: list,
    params: dict,
):
    """
    Submit a single-track request to MusicGPT then poll until done.

    operation     : "music" | "inpaint" | "extend" | "remix" | "image_to_song"
    stable_task_id: UUID pre-generated and stored as music_metadata.task_id (returned to client)
    record_ids    : IDs of the pre-inserted music_metadata rows (1 or 2 rows)
    params        : operation-specific request parameters including user_id
    """
    json_headers = {
        "Authorization": MUSICGPT_API_KEY,
        "Content-Type": "application/json",
    }
    form_headers = {"Authorization": MUSICGPT_API_KEY}

    logger.info(
        "Celery: submitting single-track — operation=%s stable_task_id=%s",
        operation, stable_task_id,
    )

    image_file_path = params.get("image_file_path") if operation == "image_to_song" else None
    result: dict | None = None

    # ── Step 1: Submit to MusicGPT ────────────────────────────────────────────
    try:
        with httpx.Client(timeout=httpx.Timeout(60.0, read=120.0)) as client:
            if operation == "music":
                payload: dict = {"prompt": " ".join(params["prompt"].split())}
                for field in ("music_style", "lyrics", "gender", "voice_id", "output_length"):
                    if params.get(field):
                        payload[field] = params[field]
                if params.get("make_instrumental"):
                    payload["make_instrumental"] = True
                if params.get("vocal_only"):
                    payload["vocal_only"] = True
                response = client.post(
                    f"{MUSICGPT_BASE_URL}/MusicAI",
                    json=payload,
                    headers=json_headers,
                )

            elif operation == "inpaint":
                logger.info(
                    "Downloading source audio for inpaint: stable_task_id=%s url=%s",
                    stable_task_id, params["audio_url"],
                )
                audio_resp = client.get(params["audio_url"])
                audio_resp.raise_for_status()

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(audio_resp.content)
                    tmp_path = tmp.name

                form_data: dict = {
                    "prompt": params["prompt"],
                    "replace_start_at": params["replace_start_at"],
                    "replace_end_at": params["replace_end_at"],
                    "num_outputs": params.get("num_outputs", 1),
                }
                for field in ("lyrics", "lyrics_section_to_replace", "gender"):
                    if params.get(field):
                        form_data[field] = params[field]

                try:
                    with open(tmp_path, "rb") as f:
                        response = client.post(
                            f"{MUSICGPT_BASE_URL}/inpaint",
                            headers=form_headers,
                            data=form_data,
                            files={"audio_file": ("audio.mp3", f, "audio/mpeg")},
                        )
                finally:
                    os.remove(tmp_path)
                    logger.info("Removed temp inpaint audio file: path=%s", tmp_path)

            elif operation == "extend":
                logger.info(
                    "Downloading source audio for extend: stable_task_id=%s url=%s",
                    stable_task_id, params["source_audio_url"],
                )
                audio_resp = client.get(params["source_audio_url"])
                audio_resp.raise_for_status()

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(audio_resp.content)
                    tmp_path = tmp.name

                form_data = {
                    "prompt": params["combined_prompt"],
                    "extend_after": params["extend_after"],
                    "num_outputs": 2,
                }

                try:
                    with open(tmp_path, "rb") as f:
                        response = client.post(
                            f"{MUSICGPT_BASE_URL}/extend",
                            headers=form_headers,
                            data=form_data,
                            files={"audio_file": ("audio.mp3", f, "audio/mpeg")},
                        )
                finally:
                    os.remove(tmp_path)
                    logger.info("Removed temp extend audio file: path=%s", tmp_path)

            elif operation == "remix":
                logger.info(
                    "Downloading source audio for remix: stable_task_id=%s url=%s",
                    stable_task_id, params["source_audio_url"],
                )
                audio_resp = client.get(params["source_audio_url"])
                audio_resp.raise_for_status()

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(audio_resp.content)
                    tmp_path = tmp.name

                form_data = {"prompt": params["prompt"]}
                for field in ("lyrics", "gender"):
                    if params.get(field):
                        form_data[field] = params[field]

                try:
                    with open(tmp_path, "rb") as f:
                        response = client.post(
                            f"{MUSICGPT_BASE_URL}/Remix",
                            headers=form_headers,
                            data=form_data,
                            files={"audio_file": ("audio.mp3", f, "audio/mpeg")},
                        )
                finally:
                    os.remove(tmp_path)
                    logger.info("Removed temp audio file: path=%s", tmp_path)

            elif operation == "image_to_song":
                result = submit_image_to_song_request(
                    client,
                    form_headers,
                    image_url=params.get("image_url"),
                    image_file_path=image_file_path,
                    prompt=params.get("prompt"),
                    lyrics=params.get("lyrics"),
                    make_instrumental=params.get("make_instrumental", False),
                    vocal_only=params.get("vocal_only", False),
                    key=params.get("key"),
                    bpm=params.get("bpm"),
                    voice_id=params.get("voice_id"),
                    webhook_url=params.get("webhook_url"),
                )

            else:
                raise ValueError(f"Unknown operation: {operation}")

        if operation != "image_to_song":
            if not response.is_success:
                logger.error(
                    "MusicGPT error %s for operation=%s: %s",
                    response.status_code, operation, response.text,
                )
            response.raise_for_status()
            result = response.json()

    except MusicGPTValidationError as exc:
        logger.error("submit_and_poll_task validation error: operation=%s error=%s", operation, exc)
        _mark_music_failed(stable_task_id, str(exc))
        _cleanup_temp_image(image_file_path)
        return
    except httpx.HTTPError as exc:
        status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        logger.error("submit_and_poll_task submit error: operation=%s error=%s", operation, exc)
        _mark_music_failed(stable_task_id, str(exc))
        if status_code is not None and 400 <= status_code < 500:
            _cleanup_temp_image(image_file_path)
            return
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            logger.error(
                "submit_and_poll_task retries exhausted: operation=%s stable_task_id=%s",
                operation, stable_task_id,
            )
            _cleanup_temp_image(image_file_path)
            return
    except Exception as exc:
        logger.error("submit_and_poll_task unexpected error: operation=%s error=%s", operation, exc)
        _mark_music_failed(stable_task_id, str(exc))
        _cleanup_temp_image(image_file_path)
        return

    if not result:
        logger.error("submit_and_poll_task did not receive MusicGPT response payload: operation=%s", operation)
        _mark_music_failed(stable_task_id, "MusicGPT response payload missing")
        _cleanup_temp_image(image_file_path)
        return

    musicgpt_task_id = result["task_id"]
    conv_id_1 = result["conversion_id_1"]
    conv_id_2 = result.get("conversion_id_2", "")
    use_conv_2 = (
        len(record_ids) > 1
        and conv_id_2
        and conv_id_2 != "single_song_generation_request"
    )

    logger.info(
        "MusicGPT job queued: operation=%s musicgpt_task_id=%s conv_id_1=%s conv_id_2=%s eta=%ss",
        operation, musicgpt_task_id, conv_id_1, conv_id_2, result.get("eta"),
    )

    # ── Step 2: Update pre-inserted records with real MusicGPT IDs ───────────
    supabase.table("music_metadata").update({
        "musicgpt_task_id": musicgpt_task_id,
        "conversion_id": conv_id_1,
        "status": "IN_QUEUE",
        "error_message": None,
    }).eq("id", record_ids[0]).execute()

    if use_conv_2:
        supabase.table("music_metadata").update({
            "musicgpt_task_id": musicgpt_task_id,
            "conversion_id": conv_id_2,
            "status": "IN_QUEUE",
            "error_message": None,
        }).eq("id", record_ids[1]).execute()
    elif len(record_ids) > 1:
        # MusicGPT returned only one conversion (e.g. inpaint with num_outputs=1)
        supabase.table("music_metadata").update({
            "status": "FAILED",
            "error_message": "MusicGPT returned a single conversion for this request",
        }).eq(
            "id", record_ids[1]
        ).execute()

    # ── Step 3: Poll each conversion until done ───────────────────────────────
    conversion_type_map = {
        "music": "MUSIC_AI",
        "inpaint": "INPAINT",
        "extend": "EXTEND",
        "remix": "REMIX",
        # MusicGPT image_to_song generates standard music conversions and is polled via MUSIC_AI.
        "image_to_song": "MUSIC_AI",
    }
    conversion_type = conversion_type_map[operation]
    poll_fallback_types = ["IMAGE_TO_SONG"] if operation == "image_to_song" else None
    user_id = params["user_id"]

    _poll_and_store(
        musicgpt_task_id=musicgpt_task_id,
        conversion_id=conv_id_1,
        user_id=user_id,
        db_task_id=stable_task_id,
        conversion_type=conversion_type,
        fallback_conversion_types=poll_fallback_types,
    )
    if use_conv_2:
        _poll_and_store(
            musicgpt_task_id=musicgpt_task_id,
            conversion_id=conv_id_2,
            user_id=user_id,
            db_task_id=stable_task_id,
            conversion_type=conversion_type,
            fallback_conversion_types=poll_fallback_types,
        )

    logger.info(
        "Celery: single-track done — operation=%s stable_task_id=%s",
        operation, stable_task_id,
    )
    _cleanup_temp_image(image_file_path)


@celery_app.task(
    name="tasks.music_tasks.process_album_track_task",
    queue="musicgpt_album",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def process_album_track_task(
    self,
    album_id: str,
    track_id: str,
    project_id: str,
    user_id: str,
    user_name: str,
    user_email: str,
    music_type: str,
    prompt: str,
    music_style: str | None = None,
    lyrics: str | None = None,
    make_instrumental: bool = False,
    gender: str | None = None,
    output_length: int | None = None,
):
    """
    Submit one album track to MusicGPT then poll until done.

    Runs in the musicgpt_album queue. Worker --concurrency controls how many
    tracks are processed in parallel (MUSICGPT_MAX_PARALLEL, default 1).
    """
    # ── Step 1: Submit to MusicGPT ────────────────────────────────────────────
    payload: dict = {"prompt": prompt}
    if music_style:
        payload["music_style"] = music_style
    if lyrics:
        payload["lyrics"] = lyrics
    if make_instrumental:
        payload["make_instrumental"] = True
    if gender:
        payload["gender"] = gender
    if output_length:
        payload["output_length"] = output_length

    headers = {
        "Authorization": MUSICGPT_API_KEY,
        "Content-Type": "application/json",
    }

    logger.info(
        "Celery: submitting album track — album_id=%s track_id=%s type=%s",
        album_id, track_id, music_type,
    )

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
            response = client.post(
                f"{MUSICGPT_BASE_URL}/MusicAI",
                json=payload,
                headers=headers,
            )
        if not response.is_success:
            logger.error(
                "MusicGPT /MusicAI error %s: %s", response.status_code, response.text
            )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Catches HTTPStatusError (4xx/5xx), ConnectError, TimeoutException, etc.
        logger.error("process_album_track_task submit error: %s", exc)
        supabase.table("album_tracks").update({"status": "FAILED"}).eq("id", track_id).execute()
        raise self.retry(exc=exc)

    result = response.json()
    logger.info(
        "MusicGPT job queued: track_id=%s task_id=%s eta=%ss",
        track_id, result["task_id"], result.get("eta"),
    )

    # ── Step 2: Insert music_metadata rows ────────────────────────────────────
    base_record = {
        "project_id": project_id,
        "user_id": user_id,
        "user_name": user_name,
        "user_email": user_email,
        "type": music_type,
        "task_id": result["task_id"],
        "musicgpt_task_id": result["task_id"],
        "status": "IN_QUEUE",
        "prompt": prompt,
        "music_style": music_style,
    }
    conv_id_2 = result.get("conversion_id_2", "")
    records_to_insert = [{**base_record, "conversion_id": result["conversion_id_1"]}]
    if conv_id_2 and conv_id_2 != "single_song_generation_request":
        records_to_insert.append({**base_record, "conversion_id": conv_id_2})
    db_response = supabase.table("music_metadata").insert(records_to_insert).execute()
    inserted = db_response.data

    # Link album_tracks to both generated music_metadata rows
    track_update: dict = {
        "music_metadata_id": inserted[0]["id"],
        "task_id": inserted[0]["task_id"],
        "status": "IN_QUEUE",
    }
    if len(inserted) > 1:
        track_update["music_metadata_id_2"] = inserted[1]["id"]
    supabase.table("album_tracks").update(track_update).eq("id", track_id).execute()

    # ── Step 3: Poll both conversions until done ──────────────────────────────
    for rec in inserted:
        _poll_and_store(
            musicgpt_task_id=rec["task_id"],
            conversion_id=rec["conversion_id"],
            user_id=user_id,
        )

    logger.info("Celery: album track done — track_id=%s task_id=%s", track_id, result["task_id"])


def _poll_and_store(
    musicgpt_task_id: str,
    conversion_id: str,
    user_id: str,
    db_task_id: str | None = None,
    conversion_type: str = "MUSIC_AI",
    fallback_conversion_types: list[str] | None = None,
) -> None:
    """
    Synchronous poll loop. Called inside Celery tasks.

    musicgpt_task_id : real task_id from MusicGPT (used for GET /byId API call)
    conversion_id    : real conversion_id from MusicGPT (used for both API and DB queries)
    user_id          : used for building the storage file path
    db_task_id       : task_id stored in music_metadata (our stable UUID for single-track ops;
                       defaults to musicgpt_task_id for album tracks which store the real ID)
    conversion_type  : primary MusicGPT conversionType parameter
    fallback_conversion_types : optional fallback conversionType values if /byId returns 422
    """
    db_task_id = db_task_id or musicgpt_task_id
    headers = {"Authorization": MUSICGPT_API_KEY}
    candidate_types = [conversion_type]
    if fallback_conversion_types:
        for item in fallback_conversion_types:
            if item and item not in candidate_types:
                candidate_types.append(item)
    candidate_idx = 0
    active_conversion_type = candidate_types[candidate_idx]

    elapsed = 0

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            while elapsed < MAX_POLL_DURATION_SECONDS:
                params = {
                    "conversionType": active_conversion_type,
                    "task_id": musicgpt_task_id,
                    "conversion_id": conversion_id,
                }
                try:
                    response = client.get(
                        f"{MUSICGPT_BASE_URL}/byId",
                        headers=headers,
                        params=params,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code == 422 and candidate_idx < len(candidate_types) - 1:
                        candidate_idx += 1
                        active_conversion_type = candidate_types[candidate_idx]
                        logger.warning(
                            "Poll received 422 with conversionType=%s; retrying with fallback conversionType=%s",
                            candidate_types[candidate_idx - 1],
                            active_conversion_type,
                        )
                        continue
                    raise

                conversion = response.json()["conversion"]
                status = conversion["status"]

                logger.info(
                    "Poll [%ds]: musicgpt_task_id=%s conversion_id=%s conversionType=%s status=%s",
                    elapsed, musicgpt_task_id, conversion_id, active_conversion_type, status,
                )

                if status not in TERMINAL_STATUSES:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    elapsed += POLL_INTERVAL_SECONDS
                    continue

                update_payload: dict = {"status": status}

                if status == "COMPLETED":
                    if conversion_id == conversion.get("conversion_id_1"):
                        audio_url = conversion.get("conversion_path_1")
                        title = conversion.get("title_1")
                        duration = conversion.get("conversion_duration_1")
                        generated_lyrics = conversion.get("lyrics_1")
                    else:
                        audio_url = conversion.get("conversion_path_2")
                        title = conversion.get("title_2")
                        duration = conversion.get("conversion_duration_2")
                        generated_lyrics = conversion.get("lyrics_2")

                    audio_response = client.get(audio_url)
                    audio_response.raise_for_status()

                    file_path = f"{user_id}/{db_task_id}/{conversion_id}.mp3"
                    supabase.storage.from_(BUCKET_NAME).upload(
                        file_path,
                        audio_response.content,
                        {"content-type": "audio/mpeg"},
                    )
                    storage_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)

                    update_payload.update({
                        "audio_url": storage_url,
                        "title": title,
                        "duration": duration,
                        "album_cover_path": conversion.get("album_cover_path"),
                        "generated_lyrics": generated_lyrics,
                        "error_message": None,
                    })
                else:
                    update_payload["error_message"] = conversion.get("message") or f"MusicGPT returned status {status}"

                supabase.table("music_metadata").update(update_payload).eq(
                    "task_id", db_task_id
                ).eq("conversion_id", conversion_id).execute()

                logger.info(
                    "Poll done: db_task_id=%s conversion_id=%s status=%s",
                    db_task_id, conversion_id, status,
                )
                return

        # Timed out
        logger.warning(
            "Poll timed out after %ds: musicgpt_task_id=%s conversion_id=%s",
            MAX_POLL_DURATION_SECONDS, musicgpt_task_id, conversion_id,
        )
        _mark_music_failed(
            db_task_id,
            f"Polling timed out after {MAX_POLL_DURATION_SECONDS} seconds",
            conversion_id=conversion_id,
        )

    except Exception as exc:
        logger.error(
            "_poll_and_store error: musicgpt_task_id=%s conversion_id=%s error=%s",
            musicgpt_task_id, conversion_id, exc,
        )
        _mark_music_failed(db_task_id, str(exc), conversion_id=conversion_id)
