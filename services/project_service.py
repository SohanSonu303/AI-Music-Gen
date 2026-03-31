import logging
from models.project_model import projectCreate
from supabase_client import supabase

logger = logging.getLogger(__name__)

class ProjectService:
    @staticmethod
    def create_project(data: projectCreate):
        logger.info("Inserting project into DB: name=%s", data.project_name)
        record = {
            "project_name": data.project_name,
            "created_by": data.created_by,
            "user_id": data.user_id,
        }
        response = supabase.table("projects").insert(record).execute()
        logger.info("Project inserted: name=%s", data.project_name)
        return response.data

    @staticmethod
    def get_all_projects():
        logger.info("Fetching all projects from DB")
        response = supabase.table("projects").select("*").execute()
        logger.info("Fetched %d projects", len(response.data))
        return response.data
