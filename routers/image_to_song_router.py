import logging
import os
import tempfile
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
from models.image_to_song_model import ImageToSongCreate
from models.music_model import MusicResponse
from services.music_service import MusicService
from services.token_service import require_tokens
from tasks.music_tasks import submit_and_poll_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/image-to-song", tags=["Image To Song"])


def _safe_validation_errors(exc: ValidationError) -> list[dict]:
    cleaned: list[dict] = []
    for raw in exc.errors():
        item = dict(raw)
        ctx = item.get("ctx")
        if isinstance(ctx, dict):
            safe_ctx: dict = {}
            for key, value in ctx.items():
                safe_ctx[key] = str(value) if isinstance(value, Exception) else value
            item["ctx"] = safe_ctx
        cleaned.append(item)
    return cleaned


@router.post("/generate", response_model=List[MusicResponse])
async def generate_from_image(
    background_tasks: BackgroundTasks,
    project_id: str = Form(...),
    image_url: Optional[str] = Form(""),
    image_file: Optional[UploadFile] = File(None),
    prompt: Optional[str] = Form(""),
    lyrics: Optional[str] = Form(""),
    make_instrumental: bool = Form(False),
    vocal_only: bool = Form(False),
    key: Optional[str] = Form(""),
    bpm: Optional[int] = Form(None),
    voice_id: Optional[str] = Form(""),
    webhook_url: Optional[str] = Form(""),
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)
    temp_image_path: Optional[str] = None
    queued = False

    try:
        if image_file is not None:
            extension = os.path.splitext(image_file.filename or "")[1] or ".img"
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
                content = await image_file.read()
                tmp.write(content)
                temp_image_path = tmp.name

        payload = ImageToSongCreate(
            project_id=project_id,
            image_url=image_url,
            image_file_path=temp_image_path,
            prompt=prompt,
            lyrics=lyrics,
            make_instrumental=make_instrumental,
            vocal_only=vocal_only,
            key=key,
            bpm=bpm,
            voice_id=voice_id,
            webhook_url=webhook_url,
        )

        logger.info(
            "Image-to-song request: project_id=%s user_id=%s image_source=%s",
            project_id,
            user_id,
            "file" if temp_image_path else "url",
        )

        require_tokens(user_id, token_costs.IMAGE_TO_SONG, "image_to_song")

        records, celery_params = await MusicService.create_image_to_song(
            payload, user_id=user_id, user_name=user.full_name or "", user_email=user.email
        )
        stable_task_id = records[0]["task_id"]
        record_ids = [r["id"] for r in records]
        try:
            submit_and_poll_task.apply_async(
                args=["image_to_song", stable_task_id, record_ids, celery_params],
                queue="musicgpt_album",
            )
        except Exception as queue_exc:
            logger.error(
                "Image-to-song queueing failed: stable_task_id=%s error=%s",
                stable_task_id,
                queue_exc,
            )
            MusicService.mark_task_failed(stable_task_id, f"Queueing failed: {queue_exc}")
            raise HTTPException(
                status_code=503,
                detail="Queue unavailable (Redis/Celery). Try again after restarting Redis and Celery worker.",
            )
        background_tasks.add_task(MusicService.fail_if_stale_queued, stable_task_id)
        queued = True
        logger.info("Image-to-song job queued to Celery: stable_task_id=%s", stable_task_id)
        return records
    except HTTPException:
        raise
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_safe_validation_errors(e))
    except Exception as e:
        logger.error("Failed to create image-to-song job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if image_file is not None:
            await image_file.close()
        if temp_image_path and not queued and os.path.exists(temp_image_path):
            os.remove(temp_image_path)
