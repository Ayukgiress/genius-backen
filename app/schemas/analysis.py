from enum import Enum

from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Any


class FocusArea(str, Enum):
    """Valid focus areas for resume suggestions"""
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    SKILLS = "skills"
    EDUCATION = "education"


class AnalysisBase(BaseModel):
    resume_id: int
    status: str = "pending"
    result: Optional[dict[str, Any]] = None
    feedback: Optional[str] = None

class AnalysisCreate(AnalysisBase):
    pass

class AnalysisUpdate(BaseModel):
    status: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    feedback: Optional[str] = None

class AnalysisAIGenerate(BaseModel):
    """Schema for triggering AI analysis"""
    resume_id: int

class Analysis(AnalysisBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
