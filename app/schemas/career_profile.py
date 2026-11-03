from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CareerProfileBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_roles: List[str] = Field(default_factory=list, max_length=50)
    skills: List[str] = Field(default_factory=list, max_length=100)
    locations: List[str] = Field(default_factory=list, max_length=50)
    remote_preference: Optional[bool] = None
    salary_min: Optional[int] = Field(default=None, ge=0)
    salary_max: Optional[int] = Field(default=None, ge=0)
    experience_level: Optional[str] = Field(default=None, max_length=50)
    weekly_goals: Optional[int] = Field(default=0, ge=0)

    @field_validator(
        "target_roles", "skills", "locations",
    )
    @classmethod
    def validate_list_values(cls, values: List[str]) -> List[str]:
        if any(not value or len(value) > 200 for value in values):
            raise ValueError("Profile entries must contain 1 to 200 characters")
        return values

    @field_validator("experience_level")
    @classmethod
    def validate_experience_level(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        allowed = {"entry", "mid", "senior", "lead", "executive"}
        if value.lower() not in allowed:
            raise ValueError(f"experience_level must be one of {sorted(allowed)}")
        return value.lower()

    @field_validator("salary_max")
    @classmethod
    def validate_salary_range(cls, value: Optional[int], info) -> Optional[int]:
        if value is None:
            return value
        min_salary = getattr(info, "data", {}).get("salary_min") if hasattr(info, "data") else None
        if min_salary is not None and value < min_salary:
            raise ValueError("salary_max must be >= salary_min")
        return value


class CareerProfileCreate(CareerProfileBase):
    pass


class CareerProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_roles: Optional[List[str]] = Field(default=None, max_length=50)
    skills: Optional[List[str]] = Field(default=None, max_length=100)
    locations: Optional[List[str]] = Field(default=None, max_length=50)
    remote_preference: Optional[bool] = None
    salary_min: Optional[int] = Field(default=None, ge=0)
    salary_max: Optional[int] = Field(default=None, ge=0)
    experience_level: Optional[str] = Field(default=None, max_length=50)
    weekly_goals: Optional[int] = Field(default=None, ge=0)


class CareerProfileResponse(CareerProfileBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
