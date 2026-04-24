from pydantic import BaseModel, EmailStr, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, List

class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    bio: Optional[str] = None

class UserCreate(UserBase):
    password: str

    @field_validator('password')
    @classmethod
    def validate_password_length(cls, v):
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Password must be 72 bytes or less when encoded as UTF-8')
        return v

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    bio: Optional[str] = None

class CareerPreferences(BaseModel):
    preferred_job_titles: List[str] = []
    preferred_locations: List[str] = []
    preferred_skills: List[str] = []
    remote_only: bool = False
    job_types: List[str] = []
    min_salary: Optional[int] = None
    keywords: List[str] = []

class User(UserBase):
    id: int
    name: Optional[str] = None
    bio: Optional[str] = None
    is_active: bool
    is_verified: bool
    career_preferences: Optional[CareerPreferences] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class UserCreateResponse(BaseModel):
    message: str
    user: User

class VerificationResponse(BaseModel):
    message: str
