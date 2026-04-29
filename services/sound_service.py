import asyncio
import logging
import os
from urllib.parse import urlparse

import httpx
from fastapi.concurrency import run_in_threadpool

from models.sound_model import SoundCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)

MUSICGPT_BASE_URL = "https://api.musicgpt.com/api/public/v1"
MUSICGPT_API_KEY = os.environ.get("MUSICGPT_API_KEY")
SFX_BUCKET_NAME = os.environ.get("SFX_BUCKET_NAME", "sfx")
SOUND_GENERATIONS_TABLE = "sound_generations"
SOUND_GENERATION_SELECT_FIELDS = (
    "project_id, user_id, user_name, type, task_id, conversion_id, "
    "status, audio_url, error_message, prompt, created_at, updated_at"
)

POLL_INTERVAL_SECONDS = 5
MAX_POLL_DURATION_SECONDS = 300
TERMINAL_STATUSES = {"COMPLETED", "ERROR", "FAILED"}
SOUND_GENERATOR_PATH = f"{MUSICGPT_BASE_URL}/sound_generator"
SOUND_CONVERSION_TYPE = "SOUND_GENERATOR"


class SoundService:
    @staticmethod
    def get_sound_generation(user_id: str, task_id: str) -> dict:
        logger.info("Fetching sound generation: user_id=%s task_id=%s", user_id, task_id)

        response = (
            supabase.table(SOUND_GENERATIONS_TABLE)
            .select(SOUND_GENERATION_SELECT_FIELDS)
            .eq("user_id", user_id)
            .eq("task_id", task_id)
            .single()
            .execute()
        )

        row = response.data
        if not row:
            raise ValueError(f"No sound generation found for user_id={user_id} task_id={task_id}")

        logger.info("Fetched sound generation for task_id=%s", task_id)
        return row

    @staticmethod
    async def create_sound(data: SoundCreate, user_id: str, user_name: str) -> dict:

        payload = {"prompt": data.prompt}
        if data.webhook_url:
            payload["webhook_url"] = data.webhook_url
        if data.audio_length is not None:
            payload["audio_length"] = data.audio_length

        headers = {"Authorization": MUSICGPT_API_KEY}

        logger.info("Calling MusicGPT /sound_generator: project_id=%s", data.project_id)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await SoundService._submit_sound_request(client, headers, payload)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "SoundGPT job queued: task_id=%s conversion_id=%s eta=%ss",
            result["task_id"],
            result["conversion_id"],
            result.get("eta"),
        )

        record = {
            "project_id": data.project_id,
            "user_id": user_id,
            "user_name": user_name,
            "type": "sfx",
            "task_id": result["task_id"],
            "conversion_id": result["conversion_id"],
            "status": "IN_QUEUE",
            "audio_url": None,
            "error_message": None,
            "prompt": data.prompt,
        }

        db_response = await run_in_threadpool(lambda: supabase.table(SOUND_GENERATIONS_TABLE).insert(record).execute())
        logger.info("Inserted sound_generations row for task_id=%s", result["task_id"])
        return db_response.data[0]

    @staticmethod
    async def poll_and_store(task_id: str, conversion_id: str, user_id: str):
        logger.info(
            "Sound polling started: task_id=%s conversion_id=%s user_id=%s",
            task_id,
            conversion_id,
            user_id,
        )
        headers = {"Authorization": MUSICGPT_API_KEY}
        params = {
            "conversionType": SOUND_CONVERSION_TYPE,
            "conversion_id": conversion_id,
        }
        elapsed = 0

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as client:
                while elapsed < MAX_POLL_DURATION_SECONDS:
                    response = await client.get(
                        f"{MUSICGPT_BASE_URL}/byId",
                        headers=headers,
                        params=params,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    conversion = payload.get("conversion", payload)
                    status = conversion.get("status")
                    if not status:
                        raise ValueError(
                            f"Missing status in SoundGenerator poll response for conversion_id={conversion_id}"
                        )

                    logger.info(
                        "Sound poll [%ds]: task_id=%s conversion_id=%s status=%s",
                        elapsed,
                        task_id,
                        conversion_id,
                        status,
                    )

                    if status not in TERMINAL_STATUSES:
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        elapsed += POLL_INTERVAL_SECONDS
                        continue

                    update_payload = {
                        "status": status,
                        "error_message": None,
                    }

                    if status == "COMPLETED":
                        audio_source_url = conversion.get("conversion_path")

                        if not audio_source_url:
                            raise ValueError(
                                f"Missing conversion_path for completed SoundGenerator job {conversion_id}"
                            )

                        logger.info(
                            "Downloading sound asset: conversion_id=%s",
                            conversion_id,
                        )
                        audio_response = await client.get(audio_source_url)
                        audio_response.raise_for_status()

                        file_extension = SoundService._get_file_extension(audio_source_url)
                        content_type = SoundService._get_content_type(file_extension)
                        file_path = f"{user_id}/{task_id}/{conversion_id}.{file_extension}"
                        audio_content = audio_response.content
                        await run_in_threadpool(
                            lambda: supabase.storage.from_(SFX_BUCKET_NAME).upload(
                                file_path,
                                audio_content,
                                {"content-type": content_type},
                            )
                        )
                        logger.info("Uploaded sound asset to storage: path=%s", file_path)

                        storage_url = await run_in_threadpool(
                            lambda: supabase.storage.from_(SFX_BUCKET_NAME).get_public_url(file_path)
                        )
                        update_payload["audio_url"] = storage_url
                    else:
                        update_payload["error_message"] = conversion.get("message") or "Sound generation failed"

                    await run_in_threadpool(
                        lambda: supabase.table(SOUND_GENERATIONS_TABLE).update(update_payload).eq(
                            "task_id",
                            task_id,
                        ).eq("conversion_id", conversion_id).execute()
                    )
                    logger.info(
                        "Sound DB updated: task_id=%s conversion_id=%s status=%s",
                        task_id,
                        conversion_id,
                        status,
                    )
                    return

                logger.warning(
                    "Sound polling timed out after %ds: task_id=%s conversion_id=%s",
                    MAX_POLL_DURATION_SECONDS,
                    task_id,
                    conversion_id,
                )
                await run_in_threadpool(
                    lambda: supabase.table(SOUND_GENERATIONS_TABLE).update(
                        {
                            "status": "FAILED",
                            "error_message": f"Polling timed out after {MAX_POLL_DURATION_SECONDS} seconds",
                        }
                    ).eq(
                        "task_id",
                        task_id,
                    ).eq("conversion_id", conversion_id).execute()
                )

        except Exception as e:
            logger.error(
                "Unexpected error during sound poll: task_id=%s conversion_id=%s error=%s",
                task_id,
                conversion_id,
                e,
            )
            await run_in_threadpool(
                lambda: supabase.table(SOUND_GENERATIONS_TABLE).update(
                    {
                        "status": "FAILED",
                        "error_message": str(e),
                    }
                ).eq(
                    "task_id",
                    task_id,
                ).eq("conversion_id", conversion_id).execute()
            )

    @staticmethod
    def _get_file_extension(audio_url: str) -> str:
        path = urlparse(audio_url).path.lower()
        if path.endswith(".wav"):
            return "wav"
        return "mp3"

    @staticmethod
    def _get_content_type(file_extension: str) -> str:
        if file_extension == "wav":
            return "audio/wav"
        return "audio/mpeg"

    @staticmethod
    async def _submit_sound_request(
        client: httpx.AsyncClient,
        headers: dict,
        payload: dict,
    ) -> httpx.Response:
        response = await client.post(
            SOUND_GENERATOR_PATH,
            headers=headers,
            data=payload,
        )
        if response.status_code not in {400, 415, 422}:
            return response

        logger.warning(
            "SoundGenerator form submission returned %s; retrying with JSON payload",
            response.status_code,
        )
        return await client.post(
            SOUND_GENERATOR_PATH,
            headers=headers,
            json=payload,
        )
