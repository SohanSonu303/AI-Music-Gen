import logging
from fastapi import APIRouter, HTTPException, Query
from models.download_model import DownloadResponse
from services.download_service import DownloadService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/download", tags=["Download"])


@router.get("/", response_model=DownloadResponse)
def get_download(
    user_id: str = Query(..., description="User ID"),
    task_id: str = Query(..., description="Task ID returned at music generation time"),
):
    logger.info("Download request: user_id=%s task_id=%s", user_id, task_id)
    try:
        return DownloadService.get_tracks(user_id, task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Download failed: user_id=%s task_id=%s error=%s", user_id, task_id, e)
        raise HTTPException(status_code=500, detail=str(e))
