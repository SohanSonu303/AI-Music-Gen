import json
import logging
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from auth.clerk_auth import get_current_user
from models.auth_model import UserContext
from models.download_model import DownloadResponse
from services.download_service import DownloadService
from mock_data.mock_state import is_mock_completed

logger = logging.getLogger(__name__)

IS_MOCK = os.getenv("IS_MOCK", "false").lower() == "true"

_MOCK_DATA_DIR = Path(__file__).parent.parent / "mock_data"


def _load_mock_download_response(task_id: str, user_id: str) -> DownloadResponse:
    if is_mock_completed(task_id):
        filename = "download_completed_response.json"
    else:
        filename = "download_inprogress_response.json"
    data = json.loads((_MOCK_DATA_DIR / filename).read_text())
    data["task_id"] = task_id
    data["user_id"] = user_id
    return DownloadResponse(**data)


router = APIRouter(prefix="/download", tags=["Download"])


@router.get("/", response_model=DownloadResponse)
def get_download(
    task_id: str = Query(..., description="Task ID returned at music generation time"),
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)
    logger.info("Download request: user_id=%s task_id=%s", user_id, task_id)

    if IS_MOCK:
        logger.info("IS_MOCK=true — returning mock download response for task_id=%s", task_id)
        return _load_mock_download_response(task_id, user_id)

    try:
        return DownloadService.get_tracks(user_id, task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Download failed: user_id=%s task_id=%s error=%s", user_id, task_id, e)
        raise HTTPException(status_code=500, detail=str(e))
