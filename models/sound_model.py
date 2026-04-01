from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SoundCreate(BaseModel):
    project_id: str
    user_id: str
    user_name: str
    user_email: str
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
    id: str
    project_id: str
    user_id: str
    user_name: str
    user_email: str
    type: str
    task_id: str
    conversion_id: str
    status: str
    prompt: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[float] = None
    audio_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
