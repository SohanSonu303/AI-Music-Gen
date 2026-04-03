from pydantic import BaseModel
from uuid import UUID


class ExtendCreate(BaseModel):
    id: UUID  # source music_metadata row ID
