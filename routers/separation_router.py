import uuid
import logging

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from models.separation_model import SeparationResponse
from services.separation_service import UPLOAD_DIR, process_audio_background
from supabase_client import supabase

import os
import shutil

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/separate", tags=["Stem Separation"])


@router.post("/", response_model=SeparationResponse)
async def separate_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form(...),
    project_id: str = Form(...),
):
    logger.info(
        "Stem separation request: user_id=%s project_id=%s filename=%s",
        user_id, project_id, file.filename,
    )
    try:
        job_id = str(uuid.uuid4())
        input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        record = await run_in_threadpool(
            lambda: supabase.table("audio_separations").insert({
                "id": job_id,
                "user_id": user_id,
                "project_id": project_id,
                "original_filename": file.filename,
                "status": "PENDING",
            }).execute()
        )

        background_tasks.add_task(
            process_audio_background,
            job_id=job_id,
            input_path=input_path,
            user_id=user_id,
            project_id=project_id,
        )

        logger.info("Stem separation job queued: job_id=%s", job_id)
        return record.data[0]

    except Exception as e:
        logger.error("Failed to start separation job: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
