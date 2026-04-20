from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ImageToSongCreate(BaseModel):
    project_id: str

    image_url: Optional[str] = None
    image_file_path: Optional[str] = None

    prompt: Optional[str] = None
    lyrics: Optional[str] = None
    make_instrumental: bool = False
    vocal_only: bool = False
    key: Optional[str] = None
    bpm: Optional[int] = Field(default=None, ge=0)
    voice_id: Optional[str] = None
    webhook_url: Optional[str] = None

    @field_validator(
        "image_url",
        "image_file_path",
        "prompt",
        "lyrics",
        "key",
        "voice_id",
        "webhook_url",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, value):
        if isinstance(value, str) and value.strip().lower() == "string":
            return None
        if value == "":
            return None
        return value

    @model_validator(mode="after")
    def validate_request(self) -> "ImageToSongCreate":
        if bool(self.image_url) == bool(self.image_file_path):
            raise ValueError("Provide exactly one of image_url or image_file")

        if self.make_instrumental and self.vocal_only:
            raise ValueError("make_instrumental and vocal_only cannot both be true")

        if self.prompt and len(self.prompt) > 300:
            raise ValueError(f"Prompt must be 300 characters or fewer (got {len(self.prompt)})")

        if self.lyrics and len(self.lyrics) > 3000:
            raise ValueError(f"Lyrics must be 3000 characters or fewer (got {len(self.lyrics)})")

        return self
