import logging

from supabase_client import supabase

logger = logging.getLogger(__name__)

EXTRACTION_TABLE = "audio_extractions"
EXTRACTION_SELECT = (
    "id, user_id, project_id, original_filename, stems, task_id, conversion_id, "
    "status, vocals_url, drums_url, bass_url, piano_url, guitar_url, error_message, created_at"
)


def get_extraction_job(user_id: str, job_id: str) -> dict:
    logger.info("Fetching extraction job: user_id=%s job_id=%s", user_id, job_id)
    response = (
        supabase.table(EXTRACTION_TABLE)
        .select(EXTRACTION_SELECT)
        .eq("user_id", user_id)
        .eq("id", job_id)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise ValueError(f"No extraction found for user_id={user_id} job_id={job_id}")
    return rows[0]
