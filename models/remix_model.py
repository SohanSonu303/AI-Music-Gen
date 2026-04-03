from pydantic import BaseModel, field_validator
from uuid import UUID
from typing import Optional


class RemixCreate(BaseModel):
    id: UUID                          # source music_metadata row ID
    prompt: Optional[str] = None      # remix style prompt; falls back to source row's prompt if not provided
    lyrics: Optional[str] = None      # user-provided lyrics; omit if instrumental
    gender: Optional[str] = None      # optional vocalist gender

    @field_validator("prompt", "lyrics", "gender", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v
