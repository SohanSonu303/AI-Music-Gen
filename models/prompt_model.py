from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class QuickIdeaCreate(BaseModel):
    prompt: str


class PromptEnhanceCreate(BaseModel):
    prompt: str
    master_prompt: Optional[str] = None  # if omitted, falls back to musicenhancerprompt.md


class PromptResponse(BaseModel):
    id: int
    created_at: datetime
    user_id: str
    user_name: str
    prompt: str          # stores the AI-generated output
    is_lyrics: bool
    feature_type: Optional[str] = None
