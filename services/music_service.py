import os
import logging
import asyncio
import httpx
from models.music_model import MusicCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)

MUSICGPT_BASE_URL = "https://api.musicgpt.com/api/public/v1"
MUSICGPT_API_KEY = os.environ.get("MUSICGPT_API_KEY")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "music-generated")

POLL_INTERVAL_SECONDS = 5
MAX_POLL_DURATION_SECONDS = 120
TERMINAL_STATUSES = {"COMPLETED", "ERROR", "FAILED"}


class MusicService:
    @staticmethod
    async def create_music(data: MusicCreate) -> list[dict]:
        payload: dict = {"prompt": data.prompt}
        if data.music_style:
            payload["music_style"] = data.music_style
        if data.lyrics:
            payload["lyrics"] = data.lyrics
        if data.make_instrumental:
            payload["make_instrumental"] = True
        if data.vocal_only:
            payload["vocal_only"] = True
        if data.gender:
            payload["gender"] = data.gender
        if data.voice_id:
            payload["voice_id"] = data.voice_id
        if data.output_length:
            payload["output_length"] = data.output_length

        headers = {
            "Authorization": MUSICGPT_API_KEY,
            "Content-Type": "application/json",
        }

        logger.info("Calling MusicGPT /MusicAI: project_id=%s type=%s", data.project_id, data.type)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                f"{MUSICGPT_BASE_URL}/MusicAI",
                json=payload,
                headers=headers,
            )
        response.raise_for_status()
        result = response.json()
        logger.info(
            "MusicGPT job queued: task_id=%s conversion_id_1=%s conversion_id_2=%s eta=%ss",
            result["task_id"], result["conversion_id_1"], result["conversion_id_2"], result.get("eta"),
        )

        base_record = {
            "project_id": data.project_id,
            "user_name": data.user_name,
            "user_email": data.user_email,
            "type": data.type.value,
            "task_id": result["task_id"],
            "status": "IN_QUEUE",
            "prompt": data.prompt,
            "music_style": data.music_style,
        }

        # Insert one row per conversion_id returned by MusicGPT
        records = [
            {**base_record, "conversion_id": result["conversion_id_1"]},
            {**base_record, "conversion_id": result["conversion_id_2"]},
        ]

        db_response = supabase.table("music_metadata").insert(records).execute()
        logger.info("Inserted %d music_metadata rows for task_id=%s", len(db_response.data), result["task_id"])
        return db_response.data

    @staticmethod
    async def poll_and_store(task_id: str, conversion_id: str, project_id: str):
        logger.info("Polling started: task_id=%s conversion_id=%s", task_id, conversion_id)
        headers = {"Authorization": MUSICGPT_API_KEY}
        params = {
            "conversionType": "MUSIC_AI",
            "task_id": task_id,
            "conversion_id": conversion_id,
        }
        elapsed = 0

        try:
            # Generous timeout: 30s connect, 120s read (audio download can be large)
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as client:
                while elapsed < MAX_POLL_DURATION_SECONDS:
                    response = await client.get(
                        f"{MUSICGPT_BASE_URL}/byId",
                        headers=headers,
                        params=params,
                    )
                    response.raise_for_status()
                    conversion = response.json()["conversion"]
                    status = conversion["status"]
                    logger.info(
                        "Poll [%ds]: task_id=%s conversion_id=%s status=%s",
                        elapsed, task_id, conversion_id, status,
                    )

                    if status not in TERMINAL_STATUSES:
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        elapsed += POLL_INTERVAL_SECONDS
                        continue

                    update_payload = {"status": status}

                    if status == "COMPLETED":
                        # Match conversion_id to the right path/title/duration/lyrics
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

                        logger.info(
                            "Downloading audio: conversion_id=%s title=%s duration=%.1fs",
                            conversion_id, title, duration or 0,
                        )
                        # Download audio and upload to Supabase Storage
                        audio_response = await client.get(audio_url)
                        audio_response.raise_for_status()

                        file_path = f"{project_id}/{task_id}/{conversion_id}.mp3"
                        supabase.storage.from_(BUCKET_NAME).upload(
                            file_path,
                            audio_response.content,
                            {"content-type": "audio/mpeg"},
                        )
                        logger.info("Uploaded to storage: path=%s", file_path)

                        # Store the Supabase Storage public URL, not the S3 source URL
                        storage_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)
                        update_payload["audio_url"] = storage_url
                        update_payload["title"] = title
                        update_payload["duration"] = duration
                        update_payload["album_cover_path"] = conversion.get("album_cover_path")
                        update_payload["generated_lyrics"] = generated_lyrics

                    supabase.table("music_metadata").update(update_payload).eq(
                        "task_id", task_id
                    ).eq("conversion_id", conversion_id).execute()
                    logger.info(
                        "DB updated: task_id=%s conversion_id=%s status=%s",
                        task_id, conversion_id, status,
                    )
                    return

                # Timed out after MAX_POLL_DURATION_SECONDS
                logger.warning(
                    "Polling timed out after %ds: task_id=%s conversion_id=%s",
                    MAX_POLL_DURATION_SECONDS, task_id, conversion_id,
                )
                supabase.table("music_metadata").update({"status": "FAILED"}).eq(
                    "task_id", task_id
                ).eq("conversion_id", conversion_id).execute()

        except Exception as e:
            logger.error(
                "Unexpected error during poll: task_id=%s conversion_id=%s error=%s",
                task_id, conversion_id, e,
            )
            # Mark as FAILED so the row is not left as IN_QUEUE
            supabase.table("music_metadata").update({"status": "FAILED"}).eq(
                "task_id", task_id
            ).eq("conversion_id", conversion_id).execute()
