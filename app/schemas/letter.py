from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional

class LetterBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    recipient: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=50_000)
    letter_type: str = Field(min_length=1, max_length=50)

class LetterCreate(LetterBase):
    pass

class LetterUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    recipient: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: Optional[str] = Field(default=None, min_length=1, max_length=50_000)
    letter_type: Optional[str] = Field(default=None, min_length=1, max_length=50)

class Letter(LetterBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class LetterGenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    job_title: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    recipient_name: Optional[str] = Field(default=None, max_length=255)
    resume_id: Optional[int] = Field(default=None, gt=0)
    letter_type: str = Field(default="cover_letter", min_length=1, max_length=50)
    custom_instructions: Optional[str] = Field(default=None, max_length=10_000)