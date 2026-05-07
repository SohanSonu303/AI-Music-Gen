from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


VALID_STEMS = {"vocals", "drums", "bass", "piano", "guitar"}
DEFAULT_STEMS = ["vocals", "drums", "bass", "piano", "guitar"]


class ExtractionResponse(BaseModel):
    id: str
    user_id: str
    project_id: str
    original_filename: str
    stems: str               # JSON-encoded list of requested stems
    task_id: Optional[str] = None
    conversion_id: Optional[str] = None
    status: str
    vocals_url: Optional[str] = None
    drums_url: Optional[str] = None
    bass_url: Optional[str] = None
    piano_url: Optional[str] = None
    guitar_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
