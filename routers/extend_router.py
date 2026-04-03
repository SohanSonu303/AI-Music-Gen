import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List
from models.extend_model import ExtendCreate
from models.music_model import MusicResponse
from services.music_service import MusicService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extend", tags=["Extend"])


@router.post("/extend", response_model=List[MusicResponse])
async def extend_music(extend: ExtendCreate, background_tasks: BackgroundTasks):
    logger.info("Extend request: source_id=%s", extend.id)
    try:
        records = await MusicService.extend_music(extend)
        for record in records:
            logger.info(
                "Queuing extend poll task: task_id=%s conversion_id=%s",
                record["task_id"], record["conversion_id"],
            )
            background_tasks.add_task(
                MusicService.poll_and_store,
                record["task_id"],
                record["conversion_id"],
                record["user_id"],
                "EXTEND",
            )
        logger.info("Extend job submitted: task_id=%s source_id=%s", records[0]["task_id"], extend.id)
        return records
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create extend job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
