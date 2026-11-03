from enum import Enum

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from typing import Optional, Any


class FocusArea(str, Enum):
    """Valid focus areas for resume suggestions"""
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    SKILLS = "skills"
    EDUCATION = "education"


class AnalysisBase(BaseModel):
    resume_id: int = Field(gt=0)
    status: str = Field(default="pending", min_length=1, max_length=50)
    result: Optional[dict[str, Any]] = None
    feedback: Optional[str] = None

    @field_validator("result")
    @classmethod
    def validate_result_size(cls, result: Optional[dict[str, Any]]):
        if result is not None and len(json.dumps(result, default=str)) > 1_000_000:
            raise ValueError("Analysis result must not exceed 1 MB")
        return result

class AnalysisCreate(AnalysisBase):
    pass

class AnalysisUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: Optional[str] = Field(default=None, min_length=1, max_length=50)
    result: Optional[dict[str, Any]] = None
    feedback: Optional[str] = None

    @field_validator("result")
    @classmethod
    def validate_result_size(cls, result: Optional[dict[str, Any]]):
        if result is not None and len(json.dumps(result, default=str)) > 1_000_000:
            raise ValueError("Analysis result must not exceed 1 MB")
        return result

class AnalysisAIGenerate(BaseModel):
    """Schema for triggering AI analysis"""
    resume_id: int = Field(gt=0)

class Analysis(AnalysisBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
