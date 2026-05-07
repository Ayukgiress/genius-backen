from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any

class InterviewMessageBase(BaseModel):
    role: str  # system, assistant, user
    content: str

class InterviewMessageCreate(InterviewMessageBase):
    pass

class InterviewMessageResponse(InterviewMessageBase):
    id: int
    interview_id: int
    created_at: datetime
    audio_content: Optional[str] = None  # Base64 encoded audio (legacy)
    transcript: Optional[str] = None  # Visual/STT transcript
    visual_analysis: Optional[Dict[str, Any]] = None  # Face/posture data
    audio_data: Optional[str] = None  # Base64 encoded AI audio response

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True  # For dict

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
