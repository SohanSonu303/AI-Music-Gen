import asyncio
import os
import logging
import httpx
from pathlib import Path
from fastapi.concurrency import run_in_threadpool
from models.prompt_model import QuickIdeaCreate, PromptEnhanceCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = "deepseek/deepseek-v3.2"

PROMPTS_TABLE = "user_prompts"

MASTER_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "musicenhancerprompt.md"

QUICK_IDEA_SYSTEM_PROMPT = (
    "You are a creative music producer and songwriter. "
    "Given a short user input, generate an original and inspiring music concept or song idea. "
    "Include a suggested mood, genre, tempo feel, and a one-line hook or theme. "
    "Your response MUST be 280 characters or fewer. Respond with the idea only, no labels or preamble."
)


def _load_master_prompt() -> str:
    return MASTER_PROMPT_PATH.read_text(encoding="utf-8").strip()


async def _call_openrouter(system_prompt: str, user_prompt: str, retries: int = 3) -> str:
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is not set in environment variables")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    # Generous timeout for large script analysis — DeepSeek can be slow on long inputs.
    timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=5.0)

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(OPENROUTER_API_URL, headers=headers, json=payload)

            if response.status_code != 200:
                logger.error("OpenRouter error %s: %s", response.status_code, response.text)
                response.raise_for_status()

            return response.json()["choices"][0]["message"]["content"].strip()

        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_exc = exc
            wait = 5 * attempt   # 5s, 10s, 15s
            logger.warning(
                "OpenRouter timeout on attempt %d/%d — retrying in %ds: %s",
                attempt, retries, wait, type(exc).__name__,
            )
            if attempt < retries:
                await asyncio.sleep(wait)

    raise last_exc


class PromptService:
    @staticmethod
    async def generate_quick_idea(data: QuickIdeaCreate, user_id: str, user_name: str) -> dict:
        logger.info("Quick idea request: user_id=%s prompt=%.80s", user_id, data.prompt)

        generated = await _call_openrouter(QUICK_IDEA_SYSTEM_PROMPT, data.prompt)

        record = {
            "user_id": user_id,
            "user_name": user_name,
            "prompt": generated,
            "is_lyrics": False,
            "feature_type": "quick_idea",
        }
        db_response = await run_in_threadpool(lambda: supabase.table(PROMPTS_TABLE).insert(record).execute())
        logger.info("Inserted quick_idea row for user_id=%s", user_id)
        return db_response.data[0]

    @staticmethod
    async def enhance_prompt(data: PromptEnhanceCreate, user_id: str, user_name: str) -> dict:
        logger.info("Prompt enhance request: user_id=%s prompt=%.80s", user_id, data.prompt)

        system_prompt = data.master_prompt if data.master_prompt else _load_master_prompt()
        system_prompt = system_prompt + "\nYour response MUST be 280 characters or fewer."

        enhanced = await _call_openrouter(system_prompt, data.prompt)

        record = {
            "user_id": user_id,
            "user_name": user_name,
            "prompt": enhanced,
            "is_lyrics": False,
            "feature_type": "prompt_enhanced",
        }
        db_response = await run_in_threadpool(lambda: supabase.table(PROMPTS_TABLE).insert(record).execute())
        logger.info("Inserted prompt_enhanced row for user_id=%s", user_id)
        return db_response.data[0]
