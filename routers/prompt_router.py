import logging
from fastapi import APIRouter, Depends, HTTPException
from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
from models.prompt_model import QuickIdeaCreate, PromptEnhanceCreate, PromptResponse
from services.prompt_service import PromptService
from services.token_service import require_tokens

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompt", tags=["Prompt"])


@router.post("/quick-idea", response_model=PromptResponse)
async def generate_quick_idea(
    data: QuickIdeaCreate,
    user: UserContext = Depends(get_current_user),
):
    if len(data.prompt) > 280:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be 280 characters or fewer (got {len(data.prompt)}). Keep it concise and descriptive.",
        )
    user_id = str(user.id)
    logger.info("Quick idea request: user_id=%s", user_id)
    require_tokens(user_id, token_costs.QUICK_IDEA, "quick_idea")
    try:
        record = await PromptService.generate_quick_idea(data, user_id=user_id, user_name=user.full_name or "")
        return record
    except Exception as e:
        logger.error("Failed to generate quick idea: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")


@router.post("/enhance", response_model=PromptResponse)
async def enhance_prompt(
    data: PromptEnhanceCreate,
    user: UserContext = Depends(get_current_user),
):
    if len(data.prompt) > 280:
        raise HTTPException(
            status_code=422,
            detail=f"Prompt must be 280 characters or fewer (got {len(data.prompt)}). Keep it concise and descriptive.",
        )
    user_id = str(user.id)
    logger.info("Prompt enhance request: user_id=%s", user_id)
    require_tokens(user_id, token_costs.PROMPT_ENHANCE, "prompt_enhance")
    try:
        record = await PromptService.enhance_prompt(data, user_id=user_id, user_name=user.full_name or "")
        return record
    except Exception as e:
        logger.error("Failed to enhance prompt: %s: %s", type(e).__name__, e)
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
