import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from typing import List
from auth.clerk_auth import get_current_user
from models.auth_model import UserContext
from models.project_model import projectCreate
from services.project_service import ProjectService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("/", response_model=List[projectCreate])
async def create_project(
    project: projectCreate,
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)
    logger.info("Creating project: name=%s user_id=%s", project.project_name, user_id)
    try:
        result = await run_in_threadpool(lambda: ProjectService.create_project(project, user_id))
        logger.info("Project created successfully: name=%s", project.project_name)
        return result
    except Exception as e:
        logger.error("Failed to create project: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[projectCreate])
async def fetch_projects(user: UserContext = Depends(get_current_user)):
    logger.info("Fetching all projects")
    return await run_in_threadpool(ProjectService.get_all_projects, str(user.id))
