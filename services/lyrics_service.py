import os
import logging
import httpx
from fastapi.concurrency import run_in_threadpool
from models.lyrics_model import LyricsCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)

MUSICGPT_BASE_URL = "https://api.musicgpt.com/api/public/v1"
MUSICGPT_API_KEY = os.environ.get("MUSICGPT_API_KEY")

LYRICS_TABLE = "user_prompts"   # update if your table has a different name


class LyricsService:
    @staticmethod
    async def generate_lyrics(data: LyricsCreate, user_id: str, user_name: str) -> dict:
        # Build enriched prompt from all context fields
        parts = [data.prompt]
        if data.mood:
            parts.append(data.mood)
        if data.style:
            parts.append(data.style)
        if data.theme:
            parts.append(data.theme)
        if data.tone:
            parts.append(data.tone)
        combined_prompt = " ".join(parts)

        headers = {"Authorization": MUSICGPT_API_KEY}
        params = {"prompt": combined_prompt}

        logger.info(
            "Calling MusicGPT /prompt_to_lyrics: user_id=%s combined_prompt=%.120s",
            user_id, combined_prompt,
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(
                f"{MUSICGPT_BASE_URL}/prompt_to_lyrics",
                headers=headers,
                params=params,
            )
        response.raise_for_status()
        result = response.json()
        logger.info(
            "MusicGPT lyrics received: task_id=%s credit_estimate=%s",
            result.get("task_id"), result.get("credit_estimate"),
        )

        # Store generated lyrics in prompt column; is_lyrics always True for this flow
        record = {
            "user_id": user_id,
            "user_name": user_name,
            "prompt": result.get("lyrics"),
            "is_lyrics": True,
            "style": data.style,
            "mood": data.mood,
            "theme": data.theme,
            "tone": data.tone,
        }

        db_response = await run_in_threadpool(lambda: supabase.table(LYRICS_TABLE).insert(record).execute())
        logger.info("Inserted %s row for user_id=%s", LYRICS_TABLE, user_id)
        return db_response.data[0]
