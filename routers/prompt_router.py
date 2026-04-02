import logging
from fastapi import APIRouter, HTTPException
from models.prompt_model import QuickIdeaCreate, PromptEnhanceCreate, PromptResponse
from services.prompt_service import PromptService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompt", tags=["Prompt"])


@router.post("/quick-idea", response_model=PromptResponse)
async def generate_quick_idea(data: QuickIdeaCreate):
    if len(data.prompt) > 280:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be 280 characters or fewer (got {len(data.prompt)}). Keep it concise and descriptive.",
        )
    logger.info("Quick idea request: user_id=%s", data.user_id)
    try:
        record = await PromptService.generate_quick_idea(data)
        return record
    except Exception as e:
        logger.error("Failed to generate quick idea: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@router.post("/enhance", response_model=PromptResponse)
async def enhance_prompt(data: PromptEnhanceCreate):
    if len(data.prompt) > 280:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be 280 characters or fewer (got {len(data.prompt)}). Keep it concise and descriptive.",
        )
    logger.info("Prompt enhance request: user_id=%s", data.user_id)
    try:
        record = await PromptService.enhance_prompt(data)
        return record
    except Exception as e:
        logger.error("Failed to enhance prompt: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
