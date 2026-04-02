import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List
from models.music_model import InpaintCreate, MusicResponse
from services.music_service import MusicService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inpaint", tags=["Inpaint"])


@router.post("/inpaint", response_model=List[MusicResponse])
async def inpaint_music(inpaint: InpaintCreate, background_tasks: BackgroundTasks):
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
        records = await MusicService.inpaint_music(inpaint)
        for record in records:
            logger.info(
                "Queuing inpaint poll task: task_id=%s conversion_id=%s",
                record["task_id"], record["conversion_id"],
            )
            background_tasks.add_task(
                MusicService.poll_and_store,
                record["task_id"],
                record["conversion_id"],
                inpaint.user_id,
                "INPAINT",
            )
        logger.info("Inpaint job submitted: task_id=%s source_id=%s", records[0]["task_id"], inpaint.id)
        return records
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create inpaint job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
