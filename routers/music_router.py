import logging
from fastapi import APIRouter, HTTPException
from typing import List
from models.music_model import MusicCreate, MusicResponse
from models.remix_model import RemixCreate
from services.music_service import MusicService
from tasks.music_tasks import submit_and_poll_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/music", tags=["Music"])


@router.post("/generateMusic", response_model=List[MusicResponse])
async def create_music(music: MusicCreate):
    if len(music.prompt) > 280:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be 280 characters or fewer (got {len(music.prompt)}). Keep it concise and descriptive.",
        )
    logger.info(
        "Music generation request: project_id=%s type=%s prompt=%.80s",
        music.project_id, music.type, music.prompt,
    )
    try:
        records, celery_params = await MusicService.create_music(music)
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]
        submit_and_poll_task.apply_async(
            args=["music", stable_task_id, record_ids, celery_params],
            queue="musicgpt_album",
        )
        logger.info(
            "Music job queued to Celery: stable_task_id=%s records=%d",
            stable_task_id, len(records),
        )
        return records
    except Exception as e:
        logger.error("Failed to create music: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/remix", response_model=List[MusicResponse])
async def remix_music(remix: RemixCreate):
    logger.info(
        "Remix request: source_id=%s lyrics_provided=%s gender=%s",
        remix.id, remix.lyrics is not None, remix.gender,
    )
    try:
        records, celery_params = await MusicService.remix_music(remix)
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]
        submit_and_poll_task.apply_async(
            args=["remix", stable_task_id, record_ids, celery_params],
            queue="musicgpt_album",
        )
        logger.info(
            "Remix job queued to Celery: stable_task_id=%s source_id=%s",
            stable_task_id, remix.id,
        )
        return records
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create remix job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
