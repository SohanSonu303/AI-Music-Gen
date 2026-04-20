import logging
from models.download_model import DownloadResponse, DownloadTrack
from supabase_client import supabase

logger = logging.getLogger(__name__)


class DownloadService:
    @staticmethod
    def get_tracks(user_id: str, task_id: str) -> DownloadResponse:
        logger.info("Fetching tracks: user_id=%s task_id=%s", user_id, task_id)

        response = (
            supabase.table("music_metadata")
            .select("conversion_id, status, title, audio_url, duration, album_cover_path, generated_lyrics, error_message")
            .eq("user_id", user_id)
            .eq("task_id", task_id)
            .execute()
        )

        rows = response.data
        if not rows:
            raise ValueError(f"No tracks found for user_id={user_id} task_id={task_id}")

        logger.info("Found %d track(s) for task_id=%s", len(rows), task_id)
        tracks = [DownloadTrack(**row) for row in rows]
        return DownloadResponse(task_id=task_id, user_id=user_id, tracks=tracks)
