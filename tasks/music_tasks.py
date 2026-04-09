"""
Celery tasks for music generation.

submit_and_poll_task  → queue: musicgpt_album
    Handles all single-track MusicGPT submissions (generateMusic / inpaint / extend / remix).
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

from celery_app import celery_app
from supabase_client import supabase

logger = logging.getLogger(__name__)

MUSICGPT_BASE_URL = "https://api.musicgpt.com/api/public/v1"
MUSICGPT_API_KEY = os.environ.get("MUSICGPT_API_KEY")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "music-generated")

POLL_INTERVAL_SECONDS = 5
MAX_POLL_DURATION_SECONDS = 300
TERMINAL_STATUSES = {"COMPLETED", "ERROR", "FAILED"}


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

    operation     : "music" | "inpaint" | "extend" | "remix"
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

            else:
                raise ValueError(f"Unknown operation: {operation}")

        if not response.is_success:
            logger.error(
                "MusicGPT error %s for operation=%s: %s",
                response.status_code, operation, response.text,
            )
        response.raise_for_status()

    except httpx.HTTPError as exc:
        # Catches HTTPStatusError (4xx/5xx), ConnectError, TimeoutException, etc.
        logger.error("submit_and_poll_task submit error: operation=%s error=%s", operation, exc)
        supabase.table("music_metadata").update({"status": "FAILED"}).eq(
            "task_id", stable_task_id
        ).execute()
        raise self.retry(exc=exc)

    result = response.json()
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
    }).eq("id", record_ids[0]).execute()

    if use_conv_2:
        supabase.table("music_metadata").update({
            "musicgpt_task_id": musicgpt_task_id,
            "conversion_id": conv_id_2,
            "status": "IN_QUEUE",
        }).eq("id", record_ids[1]).execute()
    elif len(record_ids) > 1:
        # MusicGPT returned only one conversion (e.g. inpaint with num_outputs=1)
        supabase.table("music_metadata").update({"status": "FAILED"}).eq(
            "id", record_ids[1]
        ).execute()

    # ── Step 3: Poll each conversion until done ───────────────────────────────
    conversion_type_map = {
        "music": "MUSIC_AI",
        "inpaint": "INPAINT",
        "extend": "EXTEND",
        "remix": "REMIX",
    }
    conversion_type = conversion_type_map[operation]
    user_id = params["user_id"]

    _poll_and_store(
        musicgpt_task_id=musicgpt_task_id,
        conversion_id=conv_id_1,
        user_id=user_id,
        db_task_id=stable_task_id,
        conversion_type=conversion_type,
    )
    if use_conv_2:
        _poll_and_store(
            musicgpt_task_id=musicgpt_task_id,
            conversion_id=conv_id_2,
            user_id=user_id,
            db_task_id=stable_task_id,
            conversion_type=conversion_type,
        )

    logger.info(
        "Celery: single-track done — operation=%s stable_task_id=%s",
        operation, stable_task_id,
    )


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
) -> None:
    """
    Synchronous poll loop. Called inside Celery tasks.

    musicgpt_task_id : real task_id from MusicGPT (used for GET /byId API call)
    conversion_id    : real conversion_id from MusicGPT (used for both API and DB queries)
    user_id          : used for building the storage file path
    db_task_id       : task_id stored in music_metadata (our stable UUID for single-track ops;
                       defaults to musicgpt_task_id for album tracks which store the real ID)
    conversion_type  : MusicGPT conversionType parameter
    """
    db_task_id = db_task_id or musicgpt_task_id
    headers = {"Authorization": MUSICGPT_API_KEY}
    params = {
        "conversionType": conversion_type,
        "task_id": musicgpt_task_id,
        "conversion_id": conversion_id,
    }
    elapsed = 0

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            while elapsed < MAX_POLL_DURATION_SECONDS:
                response = client.get(
                    f"{MUSICGPT_BASE_URL}/byId",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                conversion = response.json()["conversion"]
                status = conversion["status"]

                logger.info(
                    "Poll [%ds]: musicgpt_task_id=%s conversion_id=%s status=%s",
                    elapsed, musicgpt_task_id, conversion_id, status,
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
                    })

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
        supabase.table("music_metadata").update({"status": "FAILED"}).eq(
            "task_id", db_task_id
        ).eq("conversion_id", conversion_id).execute()

    except Exception as exc:
        logger.error(
            "_poll_and_store error: musicgpt_task_id=%s conversion_id=%s error=%s",
            musicgpt_task_id, conversion_id, exc,
        )
        supabase.table("music_metadata").update({"status": "FAILED"}).eq(
            "task_id", db_task_id
        ).eq("conversion_id", conversion_id).execute()
