import os
import tempfile
import logging
import asyncio
import httpx
from models.music_model import MusicCreate, InpaintCreate
from models.extend_model import ExtendCreate
from models.remix_model import RemixCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)

MUSICGPT_BASE_URL = "https://api.musicgpt.com/api/public/v1"
MUSICGPT_API_KEY = os.environ.get("MUSICGPT_API_KEY")
BUCKET_NAME = os.environ.get("BUCKET_NAME", "music-generated")

POLL_INTERVAL_SECONDS = 5
MAX_POLL_DURATION_SECONDS = 300
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
        if not response.is_success:
            logger.error("MusicGPT /MusicAI error %s: %s", response.status_code, response.text)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "MusicGPT job queued: task_id=%s conversion_id_1=%s conversion_id_2=%s eta=%ss",
            result["task_id"], result["conversion_id_1"], result["conversion_id_2"], result.get("eta"),
        )

        base_record = {
            "project_id": data.project_id,
            "user_id": data.user_id,
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
    async def inpaint_music(data: InpaintCreate) -> list[dict]:
        # Fetch the source record to copy project/user metadata
        source_resp = supabase.table("music_metadata").select("*").eq("id", data.id).single().execute()
        source = source_resp.data
        if not source:
            raise ValueError(f"music_metadata row not found: id={data.id}")

        form_data = {
            "audio_url": data.audio_url,
            "prompt": data.prompt,
            "replace_start_at": data.replace_start_at,
            "replace_end_at": data.replace_end_at,
            "num_outputs": data.num_outputs,
        }
        if data.lyrics:
            form_data["lyrics"] = data.lyrics
        if data.lyrics_section_to_replace:
            form_data["lyrics_section_to_replace"] = data.lyrics_section_to_replace
        if data.gender:
            form_data["gender"] = data.gender

        headers = {"Authorization": MUSICGPT_API_KEY}

        logger.info(
            "Calling MusicGPT /inpaint: source_id=%s replace=%.1f-%.1fs",
            data.id, data.replace_start_at, data.replace_end_at,
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            response = await client.post(
                f"{MUSICGPT_BASE_URL}/inpaint",
                headers=headers,
                data=form_data,
            )

        response.raise_for_status()
        result = response.json()
        logger.info(
            "MusicGPT inpaint job queued: task_id=%s conversion_id_1=%s conversion_id_2=%s eta=%ss",
            result["task_id"], result["conversion_id_1"], result["conversion_id_2"], result.get("eta"),
        )

        base_record = {
            "project_id": source["project_id"],
            "user_id": source["user_id"],
            "user_name": source["user_name"],
            "user_email": source["user_email"],
            "type": source["type"],
            "task_id": result["task_id"],
            "status": "IN_QUEUE",
            "prompt": data.prompt,
            "music_style": source.get("music_style"),
            "is_cloned": data.id,  # reference back to the source row
        }

        records = [{**base_record, "conversion_id": result["conversion_id_1"]}]
        conv_id_2 = result.get("conversion_id_2", "")
        if data.num_outputs > 1 and conv_id_2 and conv_id_2 != "single_song_generation_request":
            records.append({**base_record, "conversion_id": conv_id_2})

        db_response = supabase.table("music_metadata").insert(records).execute()
        logger.info(
            "Inserted %d inpaint music_metadata rows for task_id=%s (num_outputs=%d)",
            len(db_response.data), result["task_id"], data.num_outputs,
        )
        return db_response.data

    @staticmethod
    async def extend_music(data: ExtendCreate) -> list[dict]:
        # Fetch the source record to copy project/user metadata and audio details
        source_resp = supabase.table("music_metadata").select("*").eq("id", str(data.id)).single().execute()
        source = source_resp.data
        if not source:
            raise ValueError(f"music_metadata row not found: id={data.id}")

        combined_prompt = " ".join(filter(None, [source.get("prompt"), source.get("music_style")]))[:280]
        extend_after = source.get("duration")
        if extend_after is None:
            raise ValueError(f"Source row has no duration stored: id={data.id}")

        form_data = {
            "audio_url": source["audio_url"],
            "prompt": combined_prompt,
            "extend_after": extend_after,
            "num_outputs": 2,
        }

        headers = {"Authorization": MUSICGPT_API_KEY}

        logger.info(
            "Calling MusicGPT /extend: source_id=%s extend_after=%.1fs",
            data.id, extend_after,
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            response = await client.post(
                f"{MUSICGPT_BASE_URL}/extend",
                headers=headers,
                data=form_data,
            )

        if not response.is_success:
            logger.error("MusicGPT /extend error %s: %s", response.status_code, response.text)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "MusicGPT extend job queued: task_id=%s conversion_id_1=%s conversion_id_2=%s eta=%ss",
            result["task_id"], result["conversion_id_1"], result["conversion_id_2"], result.get("eta"),
        )

        base_record = {
            "project_id": source["project_id"],
            "user_id": source["user_id"],
            "user_name": source["user_name"],
            "user_email": source["user_email"],
            "type": source["type"],
            "task_id": result["task_id"],
            "status": "IN_QUEUE",
            "prompt": combined_prompt,
            "music_style": source.get("music_style"),
            "is_cloned": str(data.id),  # reference back to the source row
        }

        records = [{**base_record, "conversion_id": result["conversion_id_1"]}]
        conv_id_2 = result.get("conversion_id_2", "")
        if conv_id_2 and conv_id_2 != "single_song_generation_request":
            records.append({**base_record, "conversion_id": conv_id_2})

        db_response = supabase.table("music_metadata").insert(records).execute()
        logger.info(
            "Inserted %d extend music_metadata rows for task_id=%s",
            len(db_response.data), result["task_id"],
        )
        return db_response.data

    @staticmethod
    async def remix_music(data: RemixCreate) -> list[dict]:
        # Fetch the source record to copy project/user metadata, audio_url, and prompt
        source_resp = supabase.table("music_metadata").select("*").eq("id", str(data.id)).single().execute()
        source = source_resp.data
        if not source:
            raise ValueError(f"music_metadata row not found: id={data.id}")

        if not source.get("audio_url"):
            raise ValueError(f"Source row has no audio_url yet (still processing?): id={data.id}")

        remix_prompt = data.prompt if data.prompt else source.get("prompt")

        form_data = {"prompt": remix_prompt}
        if data.lyrics:
            form_data["lyrics"] = data.lyrics
        if data.gender:
            form_data["gender"] = data.gender

        headers = {"Authorization": MUSICGPT_API_KEY}

        # Download the source audio file to a temp file
        logger.info(
            "Downloading source audio for remix: source_id=%s url=%s",
            data.id, source["audio_url"],
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as client:
            audio_resp = await client.get(source["audio_url"])
            audio_resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_resp.content)
            tmp_path = tmp.name
        logger.info("Audio downloaded to temp file: path=%s size=%d bytes", tmp_path, len(audio_resp.content))

        try:
            logger.info(
                "Calling MusicGPT /Remix (file upload): source_id=%s prompt=%.80s prompt_source=%s lyrics_provided=%s gender=%s",
                data.id, remix_prompt,
                "user" if data.prompt else "source_row",
                data.lyrics is not None, data.gender,
            )
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                with open(tmp_path, "rb") as f:
                    response = await client.post(
                        f"{MUSICGPT_BASE_URL}/Remix",
                        headers=headers,
                        data=form_data,
                        files={"audio_file": ("audio.mp3", f, "audio/mpeg")},
                    )
        finally:
            os.remove(tmp_path)
            logger.info("Removed temp audio file: path=%s", tmp_path)

        if not response.is_success:
            logger.error("MusicGPT /Remix error %s: %s", response.status_code, response.text)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "MusicGPT remix job queued: task_id=%s conversion_id_1=%s conversion_id_2=%s eta=%ss",
            result["task_id"], result["conversion_id_1"], result["conversion_id_2"], result.get("eta"),
        )

        base_record = {
            "project_id": source["project_id"],
            "user_id": source["user_id"],
            "user_name": source["user_name"],
            "user_email": source["user_email"],
            "type": source["type"],
            "task_id": result["task_id"],
            "status": "IN_QUEUE",
            "prompt": remix_prompt,
            "music_style": source.get("music_style"),
            "is_cloned": str(data.id),  # reference back to the source row
        }

        records = [
            {**base_record, "conversion_id": result["conversion_id_1"]},
            {**base_record, "conversion_id": result["conversion_id_2"]},
        ]

        db_response = supabase.table("music_metadata").insert(records).execute()
        logger.info(
            "Inserted %d remix music_metadata rows for task_id=%s",
            len(db_response.data), result["task_id"],
        )
        return db_response.data

    @staticmethod
    async def poll_and_store(task_id: str, conversion_id: str, user_id: str, conversion_type: str = "MUSIC_AI"):
        logger.info(
            "Polling started: task_id=%s conversion_id=%s user_id=%s conversion_type=%s",
            task_id, conversion_id, user_id, conversion_type,
        )
        headers = {"Authorization": MUSICGPT_API_KEY}
        params = {
            "conversionType": conversion_type,
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

                        file_path = f"{user_id}/{task_id}/{conversion_id}.mp3"
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
