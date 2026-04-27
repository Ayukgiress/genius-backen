from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class LetterBase(BaseModel):
    title: str
    recipient: str
    content: str
    letter_type: str

class LetterCreate(LetterBase):
    pass

class LetterUpdate(BaseModel):
    title: Optional[str] = None
    recipient: Optional[str] = None
    content: Optional[str] = None
    letter_type: Optional[str] = None

class Letter(LetterBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class LetterGenerateRequest(BaseModel):
    job_title: str
    company_name: str
    recipient_name: Optional[str] = None
    resume_id: Optional[int] = None
    letter_type: str = "cover_letter"  # cover_letter, thank_you, networking
    custom_instructions: Optional[str] = None