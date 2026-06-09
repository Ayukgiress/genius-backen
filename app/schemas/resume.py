from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional

class ResumeBase(BaseModel):
    file_name: str
    file_path: str
    content: Optional[str] = None

class ResumeCreate(ResumeBase):
    user_id: int

class ResumeUpdate(BaseModel):
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    content: Optional[str] = None

class Resume(ResumeBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
