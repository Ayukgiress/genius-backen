from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional

class ResumeBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_name: str = Field(min_length=1, max_length=255)
    file_path: Optional[str] = Field(default=None, max_length=2_048)
    content: Optional[str] = Field(default=None, max_length=1_000_000)

class ResumeCreate(ResumeBase):
    pass

class ResumeUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    file_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    file_path: Optional[str] = Field(default=None, min_length=1, max_length=2_048)
    content: Optional[str] = Field(default=None, max_length=1_000_000)

class Resume(ResumeBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
