import logging
from fastapi import APIRouter, HTTPException
from models.project_model import projectCreate, projectResponse
from services.project_service import ProjectService
from typing import List

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])

@router.post("/", response_model=List[projectCreate])
async def create_project(project: projectCreate):
    logger.info("Creating project: name=%s created_by=%s", project.project_name, project.created_by)
    try:
        result = ProjectService.create_project(project)
        logger.info("Project created successfully: name=%s", project.project_name)
        return result
    except Exception as e:
        logger.error("Failed to create project: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/", response_model=List[projectCreate])
async def fetch_projects():
    logger.info("Fetching all projects")
    return ProjectService.get_all_projects()
