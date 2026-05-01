import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from typing import List, Optional

from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
from models.extraction_model import DEFAULT_STEMS, VALID_STEMS, ExtractionResponse
from services.extraction_service import get_extraction_job
from services.token_service import require_tokens
from supabase_client import supabase
from tasks.extraction_task import process_extraction_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extraction", tags=["Stem Extraction"])

UPLOAD_DIR = "inputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("/{job_id}", response_model=ExtractionResponse)
def get_extraction(
    job_id: str,
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)
    logger.info("Extraction fetch request: user_id=%s job_id=%s", user_id, job_id)
    try:
        return get_extraction_job(user_id, job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Extraction fetch failed: user_id=%s job_id=%s error=%s", user_id, job_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=ExtractionResponse)
async def extract_stems(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    stems: Optional[str] = Form(
        None,
        description='JSON array of stems to extract, e.g. ["vocals","drums"]. Defaults to all five.',
    ),
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)

    # Parse and validate stems — accepts JSON array OR comma-separated string
    if stems:
        try:
            stems_list: List[str] = json.loads(stems)
        except json.JSONDecodeError:
            # Fallback: treat as comma-separated e.g. "vocals,drums,bass"
            stems_list = [s.strip() for s in stems.split(",") if s.strip()]
        invalid = set(stems_list) - VALID_STEMS
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid stem(s): {sorted(invalid)}. Valid values: {sorted(VALID_STEMS)}",
            )
        if not stems_list:
            raise HTTPException(status_code=422, detail="'stems' must not be empty")
    else:
        stems_list = DEFAULT_STEMS

    logger.info(
        "Extraction request: user_id=%s project_id=%s filename=%s stems=%s",
        user_id, project_id, file.filename, stems_list,
    )
    require_tokens(user_id, token_costs.EXTRACTION, "extraction")

    job_id = str(uuid.uuid4())
    temp_file_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")

    try:
        # Save upload to temp file for the Celery task to read
        file_bytes = await file.read()
        with open(temp_file_path, "wb") as f:
            f.write(file_bytes)

        # Pre-insert QUEUED record — client can start polling immediately
        record = await run_in_threadpool(
            lambda: supabase.table("audio_extractions").insert({
                "id": job_id,
                "user_id": user_id,
                "project_id": project_id,
                "original_filename": file.filename,
                "stems": json.dumps(stems_list),
                "status": "QUEUED",
            }).execute()
        )

        # Enqueue Celery task — worker submits to MusicGPT, polls, uploads stems
        try:
            process_extraction_task.apply_async(
                args=[job_id, temp_file_path, file.filename, stems_list, user_id, project_id],
                queue="musicgpt_album",
            )
        except Exception as queue_exc:
            logger.error("Extraction queueing failed: job_id=%s error=%s", job_id, queue_exc)
            await run_in_threadpool(
                lambda: supabase.table("audio_extractions").update({
                    "status": "FAILED",
                    "error_message": f"Queueing failed: {queue_exc}",
                }).eq("id", job_id).execute()
            )
            raise HTTPException(
                status_code=503,
                detail="Queue unavailable (Redis/Celery). Try again after restarting Redis and Celery worker.",
            )

        logger.info("Extraction job queued: job_id=%s", job_id)
        return record.data[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to start extraction job: job_id=%s error=%s", job_id, e)
        # Clean up temp file if Celery was never reached
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        raise HTTPException(status_code=400, detail=str(e))
