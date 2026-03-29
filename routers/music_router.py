import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List
from models.music_model import MusicCreate, MusicResponse
from services.music_service import MusicService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/music", tags=["Music"])


@router.post("/generateMusic", response_model=List[MusicResponse])
async def create_music(music: MusicCreate, background_tasks: BackgroundTasks):
    logger.info(
        "Music generation request: project_id=%s type=%s prompt=%.80s",
        music.project_id, music.type, music.prompt,
    )
    try:
        records = await MusicService.create_music(music)
        for record in records:
            logger.info(
                "Queuing poll task: task_id=%s conversion_id=%s",
                record["task_id"], record["conversion_id"],
            )
            background_tasks.add_task(
                MusicService.poll_and_store,
                record["task_id"],
                record["conversion_id"],
                music.user_id,
            )
        logger.info("Music job submitted: task_id=%s", records[0]["task_id"])
        return records
    except Exception as e:
        logger.error("Failed to create music: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
