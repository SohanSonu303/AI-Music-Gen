import logging
from uuid import uuid4
from models.music_model import MusicCreate, InpaintCreate
from models.extend_model import ExtendCreate
from models.remix_model import RemixCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)


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
