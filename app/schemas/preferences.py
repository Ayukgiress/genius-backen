from pydantic import BaseModel
from typing import List, Optional

class CareerPreferences(BaseModel):
    preferred_job_titles: List[str] = []
    preferred_locations: List[str] = []
    preferred_skills: List[str] = []
    remote_only: bool = False
    job_types: List[str] = []
    min_salary: Optional[int] = None
    keywords: List[str] = []

