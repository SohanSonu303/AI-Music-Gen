from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional


class LyricsCreate(BaseModel):
    prompt: str            # base prompt describing the song
    style: Optional[str] = None
    mood: Optional[str] = None
    theme: Optional[str] = None
    tone: Optional[str] = None

    @field_validator("style", "mood", "theme", "tone", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


class LyricsResponse(BaseModel):
    id: int
    created_at: datetime
    user_id: str
    user_name: str
    prompt: str            # contains the generated lyrics (stored in prompt column)
    is_lyrics: bool
    style: Optional[str] = None
    mood: Optional[str] = None
    theme: Optional[str] = None
    tone: Optional[str] = None
