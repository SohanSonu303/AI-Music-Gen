from pydantic import BaseModel
from typing import List, Optional


class DownloadTrack(BaseModel):
    conversion_id: str
    status: str
    title: Optional[str] = None
    audio_url: Optional[str] = None
    duration: Optional[float] = None
    album_cover_path: Optional[str] = None
    generated_lyrics: Optional[str] = None


class DownloadResponse(BaseModel):
    task_id: str
    user_id: str
    tracks: List[DownloadTrack]
