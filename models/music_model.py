from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from enum import Enum


class MusicType(str, Enum):
    music = "music"
    vocal = "vocal"
    sfx = "sfx"
    stem = "stem"


# Required to create a music generation job
class MusicCreate(BaseModel):
    project_id: str
    user_name: str
    user_email: str
    type: MusicType
    prompt: str
    music_style: Optional[str] = None
    lyrics: Optional[str] = None
    make_instrumental: bool = False
    vocal_only: bool = False
    gender: Optional[str] = None
    voice_id: Optional[str] = None
    output_length: Optional[int] = None

    # Treat empty strings as None for all optional string fields
    @field_validator("music_style", "lyrics", "gender", "voice_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


# API response
class MusicResponse(BaseModel):
    id: str  # UUID primary key
    project_id: str
    user_name: str
    user_email: str
    type: str
    task_id: str
    conversion_id: str
    status: str
    prompt: Optional[str] = None
    music_style: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[float] = None
    audio_url: Optional[str] = None
    album_cover_path: Optional[str] = None
    generated_lyrics: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
