import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from typing import List
from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
from models.music_model import InpaintCreate, MusicResponse
from services.music_service import MusicService
from services.token_service import require_tokens
from tasks.music_tasks import submit_and_poll_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inpaint", tags=["Inpaint"])


@router.post("/inpaint", response_model=List[MusicResponse])
async def inpaint_music(
    inpaint: InpaintCreate,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    if len(inpaint.prompt) > 280:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be 280 characters or fewer (got {len(inpaint.prompt)}). Keep it concise and descriptive.",
        )
    logger.info(
        "Inpaint request: user=%s source_id=%s replace=%.1f-%.1fs",
        user.id, inpaint.id, inpaint.replace_start_at, inpaint.replace_end_at,
    )
    try:
        user_id = str(user.id)
        records, celery_params = await MusicService.inpaint_music(inpaint, user_id=user_id)
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]

        require_tokens(user_id, token_costs.INPAINT, "inpaint", stable_task_id)

        try:
            submit_and_poll_task.apply_async(
                args=["inpaint", stable_task_id, record_ids, celery_params],
                queue="musicgpt_album",
            )
        except Exception as queue_exc:
            logger.error("Inpaint queueing failed: stable_task_id=%s error=%s", stable_task_id, queue_exc)
            MusicService.mark_task_failed(stable_task_id, f"Queueing failed: {queue_exc}")
            raise HTTPException(
                status_code=503,
                detail="Queue unavailable (Redis/Celery). Try again after restarting Redis and Celery worker.",
            )
        background_tasks.add_task(MusicService.fail_if_stale_queued, stable_task_id)
        logger.info("Inpaint job queued: stable_task_id=%s source_id=%s", stable_task_id, inpaint.id)
        return records
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create inpaint job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
