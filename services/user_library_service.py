import logging
import time
from httpcore import ConnectionNotAvailable
from httpx import RemoteProtocolError
from supabase_client import supabase

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 0.5


def _execute_with_retry(query):
    for attempt in range(_MAX_RETRIES):
        try:
            return query.execute()
        except (RemoteProtocolError, ConnectionNotAvailable) as e:
            if attempt < _MAX_RETRIES - 1:
                logger.warning("Supabase connection reset, retrying (%d/%d): %s", attempt + 1, _MAX_RETRIES, e)
                time.sleep(_RETRY_DELAY)
            else:
                raise


class UserLibraryService:

    @staticmethod
    def get_library(user_id: str) -> dict:
        str_user_id = str(user_id)

        tracks_resp = _execute_with_retry(
            supabase.table("music_metadata").select("*").eq("user_id", str_user_id).order("created_at", desc=True)
        )

        sounds_resp = _execute_with_retry(
            supabase.table("sound_generations").select("*").eq("user_id", str_user_id).order("created_at", desc=True)
        )

        separations_resp = _execute_with_retry(
            supabase.table("audio_separations").select("*").eq("user_id", str_user_id).order("created_at", desc=True)
        )

        albums_resp = _execute_with_retry(
            supabase.table("albums").select("*").eq("user_id", str_user_id).order("created_at", desc=True)
        )

        edits_resp = _execute_with_retry(
            supabase.table("editing_table").select("*").eq("user_id", str_user_id).order("created_at", desc=True)
        )

        prompts_resp = _execute_with_retry(
            supabase.table("user_prompts").select("*").eq("user_id", str_user_id).order("created_at", desc=True)
        )

        tracks = tracks_resp.data or []
        lyrics = [r for r in (prompts_resp.data or []) if r.get("is_lyrics")]
        quick_ideas = [r for r in (prompts_resp.data or []) if r.get("feature_type") == "quick_idea"]
        enhanced_prompts = [r for r in (prompts_resp.data or []) if r.get("feature_type") == "prompt_enhanced"]

        return {
            "user_id": str_user_id,
            "summary": {
                "total_tracks": len(tracks),
                "total_sounds": len(sounds_resp.data or []),
                "total_separations": len(separations_resp.data or []),
                "total_albums": len(albums_resp.data or []),
                "total_edits": len(edits_resp.data or []),
                "total_lyrics": len(lyrics),
                "total_quick_ideas": len(quick_ideas),
                "total_enhanced_prompts": len(enhanced_prompts),
            },
            "tracks": tracks,
            "sounds": sounds_resp.data or [],
            "separations": separations_resp.data or [],
            "albums": albums_resp.data or [],
            "edits": edits_resp.data or [],
            "lyrics": lyrics,
            "quick_ideas": quick_ideas,
            "enhanced_prompts": enhanced_prompts,
        }
