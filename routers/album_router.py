from fastapi import APIRouter, BackgroundTasks, Body
from models.album_model import (
    AlbumApprove,
    AlbumCreate,
    AlbumProgressResponse,
    AlbumResponse,
    AlbumTrackResponse,
    TrackReplanRequest,
)
from services.album_service import AlbumService

router = APIRouter(prefix="/album", tags=["album"])


@router.post("/create", response_model=AlbumResponse)
async def create_album(data: AlbumCreate, background_tasks: BackgroundTasks):
    """
    Create a new album. Kicks off the LangGraph planning agent in the background.
    Poll GET /album/{id} until status == PLANNED to see track suggestions.
    """
    result = await AlbumService.create_album(data, background_tasks)
    return result


@router.get("/user/{user_id}", response_model=list[AlbumResponse])
async def get_user_albums(user_id: str):
    """List all albums for a user."""
    return await AlbumService.get_user_albums(user_id)


@router.get("/{album_id}", response_model=AlbumResponse)
async def get_album(album_id: str):
    """
    Get album with all track suggestions.
    Poll this until status == PLANNED, then show the user the suggestions.
    """
    return await AlbumService.get_album(album_id)


@router.put("/{album_id}/approve", response_model=AlbumResponse)
async def approve_album(album_id: str, data: AlbumApprove, background_tasks: BackgroundTasks):
    """
    User approves the AI-planned tracks (optionally submitting edits).
    Kicks off MusicGPT generation for each track in the background.
    """
    return await AlbumService.approve_and_generate(album_id, data, background_tasks)


@router.get("/{album_id}/progress", response_model=AlbumProgressResponse)
async def get_album_progress(album_id: str):
    """Lightweight progress endpoint. Poll during GENERATING status."""
    return await AlbumService.get_album_progress(album_id)


# ── Enhancement 3: Per-track replan & regenerate ──────────────────────────────

@router.put("/{album_id}/tracks/{track_id}/replan", response_model=AlbumTrackResponse)
async def replan_track(
    album_id: str,
    track_id: str,
    data: TrackReplanRequest = Body(default=TrackReplanRequest()),
):
    """
    Re-run AI prompt + lyrics generation for a single track while album is PLANNED.

    Optionally pass `custom_script_excerpt` (≤500 chars, verbatim from your script) to use a
    different part of the script for this track instead of what the AI originally assigned.
    The AI will re-derive scene context, mood, tempo, prompt, and lyrics from the new text.

    If no body is provided the endpoint regenerates suggestions using the same stored section.
    """
    return await AlbumService.replan_track(album_id, track_id, data.custom_script_excerpt)


@router.put("/{album_id}/tracks/{track_id}/regenerate", response_model=AlbumTrackResponse)
async def regenerate_track(album_id: str, track_id: str, background_tasks: BackgroundTasks):
    """
    Re-run MusicGPT generation for a single track after the album is GENERATING or COMPLETED.
    Old music_metadata rows are kept (history); album_tracks points to the new one.
    """
    return await AlbumService.regenerate_track(album_id, track_id, background_tasks)
