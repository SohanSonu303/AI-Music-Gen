import logging
import os
import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from models.music_model import MusicCreate, InpaintCreate
from models.image_to_song_model import ImageToSongCreate
from models.extend_model import ExtendCreate
from models.remix_model import RemixCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)
STALE_QUEUE_TIMEOUT_SECONDS = int(os.environ.get("MUSIC_QUEUE_STALE_SECONDS", "600"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MusicService:
    """
    All methods pre-insert music_metadata rows with status=QUEUED and a stable UUID as task_id,
    then return (records, celery_params) so the router can enqueue submit_and_poll_task.

    The stable task_id is what the client receives and uses to poll via GET /download/.
    The Celery task later updates each row with the real MusicGPT conversion_id and
    musicgpt_task_id once the submission succeeds.
    """

    @staticmethod
    async def create_music(data: MusicCreate) -> tuple[list[dict], dict]:
        stable_task_id = str(uuid4())
        base_record = {
            "project_id": data.project_id,
            "user_id": data.user_id,
            "user_name": data.user_name,
            "user_email": data.user_email,
            "type": data.type.value,
            "task_id": stable_task_id,
            "status": "QUEUED",
            "prompt": data.prompt,
            "music_style": data.music_style,
        }
        records = [
            {**base_record, "conversion_id": f"{stable_task_id}_1"},
            {**base_record, "conversion_id": f"{stable_task_id}_2"},
        ]
        db_response = supabase.table("music_metadata").insert(records).execute()
        inserted = db_response.data
        logger.info(
            "Pre-inserted 2 QUEUED music_metadata rows: stable_task_id=%s type=%s",
            stable_task_id, data.type.value,
        )
        celery_params = {
            "user_id": data.user_id,
            "prompt": data.prompt,
            "music_style": data.music_style,
            "lyrics": data.lyrics,
            "make_instrumental": data.make_instrumental,
            "vocal_only": data.vocal_only,
            "gender": data.gender,
            "voice_id": data.voice_id,
            "output_length": data.output_length,
        }
        return inserted, celery_params

    @staticmethod
    async def inpaint_music(data: InpaintCreate) -> tuple[list[dict], dict]:
        source_resp = supabase.table("music_metadata").select("*").eq("id", data.id).single().execute()
        source = source_resp.data
        if not source:
            raise ValueError(f"music_metadata row not found: id={data.id}")

        stable_task_id = str(uuid4())
        base_record = {
            "project_id": source["project_id"],
            "user_id": source["user_id"],
            "user_name": source["user_name"],
            "user_email": source["user_email"],
            "type": source["type"],
            "task_id": stable_task_id,
            "status": "QUEUED",
            "prompt": data.prompt,
            "music_style": source.get("music_style"),
            "is_cloned": data.id,
        }
        # Pre-insert 1 or 2 records matching num_outputs
        records = [{**base_record, "conversion_id": f"{stable_task_id}_1"}]
        if data.num_outputs > 1:
            records.append({**base_record, "conversion_id": f"{stable_task_id}_2"})

        db_response = supabase.table("music_metadata").insert(records).execute()
        inserted = db_response.data
        logger.info(
            "Pre-inserted %d QUEUED inpaint music_metadata rows: stable_task_id=%s source_id=%s",
            len(inserted), stable_task_id, data.id,
        )
        celery_params = {
            "user_id": source["user_id"],
            "audio_url": data.audio_url,
            "prompt": data.prompt,
            "replace_start_at": data.replace_start_at,
            "replace_end_at": data.replace_end_at,
            "lyrics": data.lyrics,
            "lyrics_section_to_replace": data.lyrics_section_to_replace,
            "gender": data.gender,
            "num_outputs": data.num_outputs,
        }
        return inserted, celery_params

    @staticmethod
    async def extend_music(data: ExtendCreate) -> tuple[list[dict], dict]:
        source_resp = supabase.table("music_metadata").select("*").eq("id", str(data.id)).single().execute()
        source = source_resp.data
        if not source:
            raise ValueError(f"music_metadata row not found: id={data.id}")

        if not source.get("audio_url"):
            raise ValueError(f"Source row has no audio_url yet (still processing?): id={data.id}")

        extend_after = source.get("duration")
        if extend_after is None:
            raise ValueError(f"Source row has no duration stored: id={data.id}")

        combined_prompt = " ".join(filter(None, [source.get("prompt"), source.get("music_style")]))[:280]

        stable_task_id = str(uuid4())
        base_record = {
            "project_id": source["project_id"],
            "user_id": source["user_id"],
            "user_name": source["user_name"],
            "user_email": source["user_email"],
            "type": source["type"],
            "task_id": stable_task_id,
            "status": "QUEUED",
            "prompt": combined_prompt,
            "music_style": source.get("music_style"),
            "is_cloned": str(data.id),
        }
        records = [
            {**base_record, "conversion_id": f"{stable_task_id}_1"},
            {**base_record, "conversion_id": f"{stable_task_id}_2"},
        ]
        db_response = supabase.table("music_metadata").insert(records).execute()
        inserted = db_response.data
        logger.info(
            "Pre-inserted 2 QUEUED extend music_metadata rows: stable_task_id=%s source_id=%s",
            stable_task_id, data.id,
        )
        celery_params = {
            "user_id": source["user_id"],
            "source_audio_url": source["audio_url"],
            "combined_prompt": combined_prompt,
            "extend_after": extend_after,
        }
        return inserted, celery_params

    @staticmethod
    async def remix_music(data: RemixCreate) -> tuple[list[dict], dict]:
        source_resp = supabase.table("music_metadata").select("*").eq("id", str(data.id)).single().execute()
        source = source_resp.data
        if not source:
            raise ValueError(f"music_metadata row not found: id={data.id}")

        if not source.get("audio_url"):
            raise ValueError(f"Source row has no audio_url yet (still processing?): id={data.id}")

        remix_prompt = data.prompt if data.prompt else source.get("prompt")

        stable_task_id = str(uuid4())
        base_record = {
            "project_id": source["project_id"],
            "user_id": source["user_id"],
            "user_name": source["user_name"],
            "user_email": source["user_email"],
            "type": source["type"],
            "task_id": stable_task_id,
            "status": "QUEUED",
            "prompt": remix_prompt,
            "music_style": source.get("music_style"),
            "is_cloned": str(data.id),
        }
        records = [
            {**base_record, "conversion_id": f"{stable_task_id}_1"},
            {**base_record, "conversion_id": f"{stable_task_id}_2"},
        ]
        db_response = supabase.table("music_metadata").insert(records).execute()
        inserted = db_response.data
        logger.info(
            "Pre-inserted 2 QUEUED remix music_metadata rows: stable_task_id=%s source_id=%s",
            stable_task_id, data.id,
        )
        celery_params = {
            "user_id": source["user_id"],
            "source_audio_url": source["audio_url"],
            "prompt": remix_prompt,
            "lyrics": data.lyrics,
            "gender": data.gender,
        }
        return inserted, celery_params

    @staticmethod
    async def create_image_to_song(data: ImageToSongCreate) -> tuple[list[dict], dict]:
        stable_task_id = str(uuid4())
        music_type = "vocal" if data.vocal_only else "music"

        base_record = {
            "project_id": data.project_id,
            "user_id": data.user_id,
            "user_name": data.user_name,
            "user_email": data.user_email,
            "type": music_type,
            "task_id": stable_task_id,
            "status": "QUEUED",
            "prompt": data.prompt,
            "music_style": None,
        }
        records = [{**base_record, "conversion_id": f"{stable_task_id}_1"}]
        db_response = supabase.table("music_metadata").insert(records).execute()
        inserted = db_response.data
        logger.info(
            "Pre-inserted 1 QUEUED image_to_song music_metadata row: stable_task_id=%s",
            stable_task_id,
        )

        celery_params = {
            "user_id": data.user_id,
            "image_url": data.image_url,
            "image_file_path": data.image_file_path,
            "prompt": data.prompt,
            "lyrics": data.lyrics,
            "make_instrumental": data.make_instrumental,
            "vocal_only": data.vocal_only,
            "key": data.key,
            "bpm": data.bpm,
            "voice_id": data.voice_id,
            "webhook_url": data.webhook_url,
        }
        return inserted, celery_params

    @staticmethod
    def mark_task_failed(task_id: str, error_message: str) -> None:
        supabase.table("music_metadata").update(
            {
                "status": "FAILED",
                "error_message": error_message,
                "updated_at": _now_iso(),
            }
        ).eq("task_id", task_id).execute()

    @staticmethod
    async def fail_if_stale_queued(task_id: str, timeout_seconds: int = STALE_QUEUE_TIMEOUT_SECONDS) -> None:
        """
        Watchdog for queue starvation:
        if a task is still QUEUED after timeout, mark it FAILED with a clear message.
        """
        await asyncio.sleep(timeout_seconds)
        resp = (
            supabase.table("music_metadata")
            .select("status")
            .eq("task_id", task_id)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return

        if all(row.get("status") == "QUEUED" for row in rows):
            logger.warning(
                "Watchdog marked task as FAILED due to stale QUEUED status: task_id=%s timeout=%ss",
                task_id,
                timeout_seconds,
            )
            MusicService.mark_task_failed(
                task_id,
                f"Task stuck in QUEUED for more than {timeout_seconds} seconds. "
                "Worker may be offline or queue unavailable.",
            )
