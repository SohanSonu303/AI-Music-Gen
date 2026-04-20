from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class UserContext(BaseModel):
    id: UUID
    clerk_user_id: str
    email: str
    full_name: Optional[str] = None
    jwt: str
