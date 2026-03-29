import logging
from fastapi import APIRouter, HTTPException
from models.lyrics_model import LyricsCreate, LyricsResponse
from services.lyrics_service import LyricsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lyrics", tags=["Lyrics"])


@router.post("/generate", response_model=LyricsResponse)
async def generate_lyrics(lyrics: LyricsCreate):
    logger.info(
        "Lyrics generation request: user_id=%s prompt=%.80s",
        lyrics.user_id, lyrics.prompt,
    )
    try:
        record = await LyricsService.generate_lyrics(lyrics)
        logger.info("Lyrics generated for user_id=%s", lyrics.user_id)
        return record
    except Exception as e:
        logger.error("Failed to generate lyrics: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
