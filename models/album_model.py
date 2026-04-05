from __future__ import annotations
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, model_validator


# ── Request models ────────────────────────────────────────────────────────────

class AlbumCreate(BaseModel):
    project_id: str
    user_id: str
    user_name: str
    user_email: str
    script: str
    # Track composition — specify how many of each type you want.
    # At least one field must be > 0; total must be 1–20.
    songs: int = Field(0, ge=0, description="Vocal tracks with lyrics")
    background_scores: int = Field(0, ge=0, description="Cinematic/ambient instrumental background music")
    instrumentals: int = Field(0, ge=0, description="Pure instrumental songs (structured, no vocals)")

    @model_validator(mode="after")
    def check_total(self) -> "AlbumCreate":
        total = self.songs + self.background_scores + self.instrumentals
        if total < 1:
            raise ValueError("Provide at least one track (songs, background_scores, or instrumentals)")
        if total > 20:
            raise ValueError("Total tracks (songs + background_scores + instrumentals) cannot exceed 20")
        return self

    @property
    def total_tracks(self) -> int:
        return self.songs + self.background_scores + self.instrumentals


class TrackUpdate(BaseModel):
    """Optional per-track edits submitted alongside the approve action."""
    id: UUID
    script_excerpt: Optional[str] = None
    prompt: Optional[str] = None
    music_style: Optional[str] = None
    lyrics: Optional[str] = None
    make_instrumental: Optional[bool] = None
    gender: Optional[str] = None
    output_length: Optional[int] = None


class AlbumApprove(BaseModel):
    track_updates: Optional[list[TrackUpdate]] = None


class TrackReplanRequest(BaseModel):
    """Optional request body for the replan endpoint."""
    custom_script_excerpt: Optional[str] = Field(
        None,
        max_length=500,
        description="Verbatim script text to base this track's suggestions on instead of the AI-assigned section.",
    )


# ── Response models ───────────────────────────────────────────────────────────

class AlbumTrackResponse(BaseModel):
    id: str
    album_id: str
    track_number: int
    # track_type: "song" | "background_score" | "instrumental"
    track_type: str = "song"
    scene_description: Optional[str] = None
    script_excerpt: Optional[str] = None
    suggested_style: Optional[str] = None
    suggested_mood: Optional[str] = None
    suggested_tempo: Optional[str] = None
    prompt: Optional[str] = None
    music_style: Optional[str] = None
    lyrics: Optional[str] = None
    make_instrumental: bool = False
    gender: Optional[str] = None
    output_length: Optional[int] = None
    music_metadata_id: Optional[str] = None
    music_metadata_id_2: Optional[str] = None
    task_id: Optional[str] = None
    status: str
    energy_level: Optional[int] = None
    created_at: str


class AlbumResponse(BaseModel):
    id: str
    project_id: str
    user_id: str
    user_name: str
    user_email: str
    title: Optional[str] = None
    script: str
    num_songs: int          # total tracks stored in DB
    track_composition: Optional[str] = None  # JSON: {songs, background_scores, instrumentals}
    status: str
    style_palette: Optional[str] = None
    tracks: list[AlbumTrackResponse] = []
    created_at: str
    updated_at: Optional[str] = None


class AlbumProgressTrack(BaseModel):
    track_number: int
    status: str


class AlbumProgressResponse(BaseModel):
    album_id: str
    status: str
    tracks_completed: int
    tracks_total: int
    tracks: list[AlbumProgressTrack]
