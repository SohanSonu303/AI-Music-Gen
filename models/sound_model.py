from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SoundCreate(BaseModel):
    project_id: str
    prompt: str
    webhook_url: Optional[str] = None
    audio_length: Optional[int] = Field(default=None, ge=1)

    @field_validator("webhook_url", mode="before")
    @classmethod
    def empty_str_to_none(cls, value):
        if value == "":
            return None
        return value


class SoundResponse(BaseModel):
    id: Optional[int] = None
    project_id: str
    user_id: str
    user_name: str
    type: str
    task_id: str
    conversion_id: str
    status: str
    audio_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
