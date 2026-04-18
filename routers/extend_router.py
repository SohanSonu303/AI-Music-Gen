import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from typing import List
from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
from models.extend_model import ExtendCreate
from models.music_model import MusicResponse
from services.music_service import MusicService
from services.token_service import require_tokens
from tasks.music_tasks import submit_and_poll_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extend", tags=["Extend"])


@router.post("/extend", response_model=List[MusicResponse])
async def extend_music(
    extend: ExtendCreate,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    logger.info("Extend request: user=%s source_id=%s", user.id, extend.id)
    try:
        user_id = str(user.id)
        records, celery_params = await MusicService.extend_music(extend, user_id=user_id)
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]

        require_tokens(user_id, token_costs.EXTEND, "extend", stable_task_id)

        try:
            submit_and_poll_task.apply_async(
                args=["extend", stable_task_id, record_ids, celery_params],
                queue="musicgpt_album",
            )
        except Exception as queue_exc:
            logger.error("Extend queueing failed: stable_task_id=%s error=%s", stable_task_id, queue_exc)
            MusicService.mark_task_failed(stable_task_id, f"Queueing failed: {queue_exc}")
            raise HTTPException(
                status_code=503,
                detail="Queue unavailable (Redis/Celery). Try again after restarting Redis and Celery worker.",
            )
        background_tasks.add_task(MusicService.fail_if_stale_queued, stable_task_id)
        logger.info("Extend job queued: stable_task_id=%s source_id=%s", stable_task_id, extend.id)
        return records
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create extend job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
