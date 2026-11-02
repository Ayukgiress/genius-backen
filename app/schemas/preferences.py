from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional

class CareerPreferences(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    preferred_job_titles: List[str] = Field(default_factory=list, max_length=50)
    preferred_locations: List[str] = Field(default_factory=list, max_length=50)
    preferred_skills: List[str] = Field(default_factory=list, max_length=100)
    remote_only: bool = False
    job_types: List[str] = Field(default_factory=list, max_length=20)
    min_salary: Optional[int] = Field(default=None, ge=0)
    keywords: List[str] = Field(default_factory=list, max_length=100)

    @field_validator(
        "preferred_job_titles",
        "preferred_locations",
        "preferred_skills",
        "job_types",
        "keywords",
    )
    @classmethod
    def validate_list_values(cls, values: List[str]) -> List[str]:
        if any(not value or len(value) > 200 for value in values):
            raise ValueError("Preference entries must contain 1 to 200 characters")
        return values

