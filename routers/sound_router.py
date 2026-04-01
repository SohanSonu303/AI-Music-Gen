import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from models.sound_model import SoundCreate, SoundResponse
from services.sound_service import SoundService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sound_generator", tags=["Sound Generator"])


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
    except Exception as e:
        logger.error("Failed to create sound job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
