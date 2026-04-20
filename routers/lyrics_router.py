import logging
from fastapi import APIRouter, Depends, HTTPException
from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
from models.lyrics_model import LyricsCreate, LyricsResponse
from services.lyrics_service import LyricsService
from services.token_service import require_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lyrics", tags=["Lyrics"])


@router.post("/generate", response_model=LyricsResponse)
async def generate_lyrics(
    lyrics: LyricsCreate,
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)
    logger.info("Lyrics generation request: user_id=%s prompt=%.80s", user_id, lyrics.prompt)
    require_tokens(user_id, token_costs.LYRICS_GENERATE, "lyrics_generate")
    try:
        record = await LyricsService.generate_lyrics(lyrics, user_id=user_id, user_name=user.full_name or "")
        logger.info("Lyrics generated for user_id=%s", user_id)
        return record
    except Exception as e:
        logger.error("Failed to generate lyrics: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
