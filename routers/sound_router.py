import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from models.sound_model import SoundCreate, SoundResponse
from services.sound_service import SoundService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sound_generator", tags=["Sound Generator"])


@router.get("/status")
def get_sound_generation_status(
    user_id: str = Query(..., description="User ID"),
    task_id: str = Query(..., description="Task ID returned at sound generation time"),
):
    logger.info("Sound status request: user_id=%s task_id=%s", user_id, task_id)
    try:
        row = SoundService.get_sound_generation(user_id, task_id)
        status = row.get("status")
        audio_url = row.get("audio_url")
        error_message = row.get("error_message")
        is_completed = status == "COMPLETED"
        has_audio = bool(audio_url)

        return {
            "success": True,
            "source_table": "sound_generations",
            "user_id": row.get("user_id"),
            "task_id": row.get("task_id"),
            "conversion_id": row.get("conversion_id"),
            "project_id": row.get("project_id"),
            "status": status,
            "audio_url": audio_url,
            "error_message": error_message,
            "is_completed": is_completed,
            "has_audio": has_audio,
            "ready_for_download": is_completed and has_audio,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Sound status failed: user_id=%s task_id=%s error=%s", user_id, task_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=SoundResponse)
def get_sound_generation(
    user_id: str = Query(..., description="User ID"),
    task_id: str = Query(..., description="Task ID returned at sound generation time"),
):
    logger.info("Sound fetch request: user_id=%s task_id=%s", user_id, task_id)
    try:
        return SoundService.get_sound_generation(user_id, task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Sound fetch failed: user_id=%s task_id=%s error=%s", user_id, task_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=SoundResponse)
async def create_sound(sound: SoundCreate, background_tasks: BackgroundTasks):
    logger.info(
        "Sound generation request: project_id=%s prompt=%.80s audio_length=%s",
        sound.project_id,
        sound.prompt,
        sound.audio_length,
    )
    try:
        record = await SoundService.create_sound(sound)
        logger.info(
            "Queuing sound poll task: task_id=%s conversion_id=%s",
            record["task_id"],
            record["conversion_id"],
        )
        background_tasks.add_task(
            SoundService.poll_and_store,
            record["task_id"],
            record["conversion_id"],
            sound.user_id,
        )
        logger.info(
            "Sound job submitted: task_id=%s conversion_id=%s",
            record["task_id"],
            record["conversion_id"],
        )
        return record
    except ValueError as e:
        logger.error("Sound validation failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to create sound job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
