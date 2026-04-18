import logging
from fastapi import APIRouter, Depends, HTTPException
from auth.clerk_auth import get_current_user
from models.auth_model import UserContext
from services.user_library_service import UserLibraryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/library", tags=["User Library"])


@router.get("/")
def get_user_library(user: UserContext = Depends(get_current_user)):
    """
    Returns all music-related content owned by the authenticated user:
    tracks, sounds, stem separations, albums, saved edits, lyrics,
    quick ideas, and enhanced prompts — each as a separate list plus a summary.
    """
    user_id = str(user.id)
    logger.info("Library request: user_id=%s", user_id)
    try:
        return UserLibraryService.get_library(user_id)
    except Exception as e:
        logger.error("Library fetch failed: user_id=%s error=%s", user_id, e)
        raise HTTPException(status_code=500, detail=str(e))
