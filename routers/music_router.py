import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from typing import List
from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
from models.music_model import MusicCreate, MusicResponse
from models.remix_model import RemixCreate
from services.music_service import MusicService
from services.token_service import require_tokens
from tasks.music_tasks import submit_and_poll_task
from mock_data.mock_state import register_mock_task

logger = logging.getLogger(__name__)

IS_MOCK = os.getenv("IS_MOCK", "false").lower() == "true"

_MOCK_DATA_DIR = Path(__file__).parent.parent / "mock_data"


def _load_mock_generate_response(
    music: MusicCreate,
    user_id: str,
    user_name: str,
    user_email: str,
) -> List[MusicResponse]:
    raw = json.loads((_MOCK_DATA_DIR / "generate_music_response.json").read_text())
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    for i, item in enumerate(raw):
        item["id"] = str(uuid.uuid4())
        item["task_id"] = task_id
        item["conversion_id"] = f"mock-conv-{i + 1}"
        item["project_id"] = music.project_id
        item["type"] = music.type
        item["prompt"] = music.prompt
        item["music_style"] = music.music_style
        item["user_id"] = user_id
        item["user_name"] = user_name
        item["user_email"] = user_email
        item["created_at"] = now
    register_mock_task(task_id)
    return [MusicResponse(**item) for item in raw]


router = APIRouter(prefix="/music", tags=["Music"])


@router.post("/generateMusic", response_model=List[MusicResponse])
async def create_music(
    music: MusicCreate,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    if len(music.prompt) > 280:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be 280 characters or fewer (got {len(music.prompt)}). Keep it concise and descriptive.",
        )
    logger.info(
        "Music generation request: user=%s project_id=%s type=%s prompt=%.80s",
        user.id, music.project_id, music.type, music.prompt,
    )

    if IS_MOCK:
        logger.info("IS_MOCK=true — returning mock generateMusic response")
        return _load_mock_generate_response(
            music,
            user_id=str(user.id),
            user_name=user.full_name or "",
            user_email=user.email,
        )

    try:
        user_id = str(user.id)
        require_tokens(user_id, token_costs.MUSIC_GENERATION, "music_generation")
        records, celery_params = await MusicService.create_music(
            music,
            user_id=user_id,
            user_name=user.full_name or "",
            user_email=user.email,
        )
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]

        try:
            submit_and_poll_task.apply_async(
                args=["music", stable_task_id, record_ids, celery_params],
                queue="musicgpt_album",
            )
        except Exception as queue_exc:
            logger.error("Music queueing failed: stable_task_id=%s error=%s", stable_task_id, queue_exc)
            MusicService.mark_task_failed(stable_task_id, f"Queueing failed: {queue_exc}")
            raise HTTPException(
                status_code=503,
                detail="Queue unavailable (Redis/Celery). Try again after restarting Redis and Celery worker.",
            )
        background_tasks.add_task(MusicService.fail_if_stale_queued, stable_task_id)
        logger.info("Music job queued: stable_task_id=%s records=%d", stable_task_id, len(records))
        return records
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create music: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/remix", response_model=List[MusicResponse])
async def remix_music(
    remix: RemixCreate,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    logger.info(
        "Remix request: user=%s source_id=%s lyrics_provided=%s gender=%s",
        user.id, remix.id, remix.lyrics is not None, remix.gender,
    )
    try:
        user_id = str(user.id)
        require_tokens(user_id, token_costs.REMIX, "remix")
        records, celery_params = await MusicService.remix_music(remix, user_id=user_id)
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]

        try:
            submit_and_poll_task.apply_async(
                args=["remix", stable_task_id, record_ids, celery_params],
                queue="musicgpt_album",
            )
        except Exception as queue_exc:
            logger.error("Remix queueing failed: stable_task_id=%s error=%s", stable_task_id, queue_exc)
            MusicService.mark_task_failed(stable_task_id, f"Queueing failed: {queue_exc}")
            raise HTTPException(
                status_code=503,
                detail="Queue unavailable (Redis/Celery). Try again after restarting Redis and Celery worker.",
            )
        background_tasks.add_task(MusicService.fail_if_stale_queued, stable_task_id)
        logger.info("Remix job queued: stable_task_id=%s source_id=%s", stable_task_id, remix.id)
        return records
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create remix job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
