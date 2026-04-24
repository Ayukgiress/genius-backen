from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class InterviewMessageBase(BaseModel):
    role: str  # system, assistant, user
    content: str

class InterviewMessageCreate(InterviewMessageBase):
    pass

class InterviewMessageResponse(InterviewMessageBase):
    id: int
    interview_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class InterviewBase(BaseModel):
    job_id: str
    status: str = "ongoing"  # ongoing, completed

class InterviewCreate(InterviewBase):
    resume_id: Optional[int] = None

class InterviewResponse(InterviewBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    messages: List[InterviewMessageResponse] = []

    class Config:
        from_attributes = True

class InterviewStartRequest(BaseModel):
    resume_id: Optional[int] = None  # Optional resume to provide context