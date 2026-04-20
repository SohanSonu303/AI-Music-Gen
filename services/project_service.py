import logging
from models.project_model import projectCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)

class ProjectService:
    @staticmethod
    def create_project(data: projectCreate, user_id: str):
        logger.info("Inserting project into DB: name=%s", data.project_name)
        record = {
            "project_name": data.project_name,
            "created_by": data.created_by,
            "user_id": user_id,
        }
        response = supabase.table("projects").insert(record).execute()
        logger.info("Project inserted: name=%s", data.project_name)
        return response.data

    @staticmethod
    def get_all_projects(user_id: str):
        logger.info("Fetching projects from DB: user_id=%s", user_id)
        response = supabase.table("projects").select("*").eq("user_id", user_id).execute()
        logger.info("Fetched %d projects", len(response.data))
        return response.data

    @staticmethod
    def assert_owns_project(project_id: str, user_id: str) -> None:
        """Raise ValueError if project_id is a known project not owned by user_id."""
        try:
            pid = int(project_id)
        except (ValueError, TypeError):
            return  # free-form label (e.g. "proj_001"), not a DB row — skip check
        resp = supabase.table("projects").select("id").eq("id", pid).eq("user_id", user_id).maybe_single().execute()
        if resp.data is None:
            raise ValueError("Project not found or access denied")
