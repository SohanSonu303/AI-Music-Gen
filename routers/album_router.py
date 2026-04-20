import logging
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from auth.clerk_auth import get_current_user
from config import token_costs
from models.auth_model import UserContext
from models.album_model import (
    AlbumApprove,
    AlbumCreate,
    AlbumProgressResponse,
    AlbumResponse,
    AlbumTrackResponse,
    TrackReplanRequest,
)
from services.album_service import AlbumService
from services.token_service import require_tokens
from supabase_client import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/album", tags=["album"])


@router.post("/create", response_model=AlbumResponse)
async def create_album(
    data: AlbumCreate,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)
    result = await AlbumService.create_album(
        data, background_tasks,
        user_id=user_id,
        user_name=user.full_name or "",
        user_email=user.email,
    )
    return result


@router.get("/user", response_model=list[AlbumResponse])
async def get_user_albums(user: UserContext = Depends(get_current_user)):
    """List all albums for the authenticated user."""
    return await AlbumService.get_user_albums(str(user.id))


@router.get("/{album_id}", response_model=AlbumResponse)
async def get_album(
    album_id: str,
    user: UserContext = Depends(get_current_user),
):
    return await AlbumService.get_album(album_id, user_id=str(user.id))


@router.put("/{album_id}/approve", response_model=AlbumResponse)
async def approve_album(
    album_id: str,
    data: AlbumApprove,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)
    # Validate ownership before querying tracks — prevents track-count info leak
    await AlbumService.get_album(album_id, user_id=user_id)
    tracks_resp = await run_in_threadpool(
        lambda: supabase.table("album_tracks")
        .select("id, status")
        .eq("album_id", album_id)
        .execute()
    )
    tracks = tracks_resp.data or []
    pending_count = len([t for t in tracks if t["status"] != "COMPLETED"])
    if pending_count > 0:
        require_tokens(user_id, pending_count * token_costs.ALBUM_PER_TRACK, "album_generate")
    return await AlbumService.approve_and_generate(album_id, data, background_tasks, user_id=user_id)


@router.get("/{album_id}/progress", response_model=AlbumProgressResponse)
async def get_album_progress(
    album_id: str,
    user: UserContext = Depends(get_current_user),
):
    return await AlbumService.get_album_progress(album_id, user_id=str(user.id))


@router.put("/{album_id}/tracks/{track_id}/replan", response_model=AlbumTrackResponse)
async def replan_track(
    album_id: str,
    track_id: str,
    data: TrackReplanRequest = Body(default=TrackReplanRequest()),
    user: UserContext = Depends(get_current_user),
):
    return await AlbumService.replan_track(album_id, track_id, data.custom_script_excerpt, user_id=str(user.id))


@router.put("/{album_id}/tracks/{track_id}/regenerate", response_model=AlbumTrackResponse)
async def regenerate_track(
    album_id: str,
    track_id: str,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    user_id = str(user.id)
    require_tokens(user_id, token_costs.ALBUM_PER_TRACK, "album_generate")
    return await AlbumService.regenerate_track(album_id, track_id, background_tasks, user_id=user_id)
