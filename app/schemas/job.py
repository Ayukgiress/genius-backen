from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, List

class JobBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    company: str = Field(min_length=1, max_length=255)
    location: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=100_000)
    requirements: Optional[str] = Field(default=None, max_length=50_000)
    salary_range: Optional[str] = Field(default=None, max_length=100)
    job_type: Optional[str] = Field(default=None, max_length=80)
    source: str = Field(min_length=1, max_length=100)
    source_url: Optional[str] = Field(default=None, max_length=2_048)
    posted_at: Optional[datetime] = None
    is_remote: bool = False

class JobCreate(JobBase):
    pass

class JobUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    company: Optional[str] = Field(default=None, min_length=1, max_length=255)
    location: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=100_000)
    requirements: Optional[str] = Field(default=None, max_length=50_000)
    salary_range: Optional[str] = Field(default=None, max_length=100)
    job_type: Optional[str] = Field(default=None, max_length=80)
    source_url: Optional[str] = Field(default=None, max_length=2_048)
    posted_at: Optional[datetime] = None
    is_remote: Optional[bool] = None

class JobResponse(JobBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True

class JobMatchResponse(JobResponse):
    match_score: Optional[int] = None
    matched_skills: Optional[List[str]] = []
    missing_skills: Optional[List[str]] = []
    match_reason: Optional[str] = None

class JobSearchParams(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: Optional[str] = Field(default=None, max_length=200)
    location: Optional[str] = Field(default=None, max_length=200)
    remote: Optional[bool] = None
    job_type: Optional[str] = Field(default=None, max_length=80)
    min_salary: Optional[int] = Field(default=None, ge=0)
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=100)
