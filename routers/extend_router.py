import logging
from fastapi import APIRouter, HTTPException
from typing import List
from models.extend_model import ExtendCreate
from models.music_model import MusicResponse
from services.music_service import MusicService
from tasks.music_tasks import submit_and_poll_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extend", tags=["Extend"])


@router.post("/extend", response_model=List[MusicResponse])
async def extend_music(extend: ExtendCreate):
    logger.info("Extend request: source_id=%s", extend.id)
    try:
        records, celery_params = await MusicService.extend_music(extend)
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]
        submit_and_poll_task.apply_async(
            args=["extend", stable_task_id, record_ids, celery_params],
            queue="musicgpt_album",
        )
        logger.info(
            "Extend job queued to Celery: stable_task_id=%s source_id=%s",
            stable_task_id, extend.id,
        )
        return records
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create extend job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
