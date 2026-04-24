from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class JobBase(BaseModel):
    title: str
    company: str
    location: str
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_range: Optional[str] = None
    job_type: Optional[str] = None
    source: str
    source_url: Optional[str] = None
    posted_at: Optional[datetime] = None
    is_remote: bool = False

class JobCreate(JobBase):
    pass

class JobUpdate(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_range: Optional[str] = None
    job_type: Optional[str] = None
    source_url: Optional[str] = None
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

class JobSearchParams(BaseModel):
    query: Optional[str] = None
    location: Optional[str] = None
    remote: Optional[bool] = None
    job_type: Optional[str] = None
    min_salary: Optional[int] = None
    page: int = 1
    limit: int = 10