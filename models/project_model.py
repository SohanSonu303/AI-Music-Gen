from pydantic import BaseModel
from datetime import datetime
from typing import Optional

#reuqired to create project
class projectCreate(BaseModel) :
    project_name : str
    created_by : str


#Api response
class projectResponse(BaseModel):
    id: int
    project_name: str
    created_by: str
    created_at: datetime
    updated_at: Optional[datetime] = None