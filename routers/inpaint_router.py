import logging
from fastapi import APIRouter, HTTPException
from typing import List
from models.music_model import InpaintCreate, MusicResponse
from services.music_service import MusicService
from tasks.music_tasks import submit_and_poll_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inpaint", tags=["Inpaint"])


@router.post("/inpaint", response_model=List[MusicResponse])
async def inpaint_music(inpaint: InpaintCreate):
    if len(inpaint.prompt) > 280:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be 280 characters or fewer (got {len(inpaint.prompt)}). Keep it concise and descriptive.",
        )
    logger.info(
        "Inpaint request: source_id=%s replace=%.1f-%.1fs",
        inpaint.id, inpaint.replace_start_at, inpaint.replace_end_at,
    )
    try:
        records, celery_params = await MusicService.inpaint_music(inpaint)
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]
        submit_and_poll_task.apply_async(
            args=["inpaint", stable_task_id, record_ids, celery_params],
            queue="musicgpt_album",
        )
        logger.info(
            "Inpaint job queued to Celery: stable_task_id=%s source_id=%s",
            stable_task_id, inpaint.id,
        )
        return records
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create inpaint job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
