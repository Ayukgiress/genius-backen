from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from datetime import datetime
from typing import Optional, List

class UserBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    name: Optional[str] = Field(default=None, max_length=120)
    bio: Optional[str] = Field(default=None, max_length=2_000)
    profile_picture: Optional[str] = Field(default=None, max_length=2_048)
    subscription_plan: Optional[str] = Field(default="free", max_length=50)
    subscription_status: Optional[str] = Field(default="inactive", max_length=50)

class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=72)

    @field_validator('password')
    @classmethod
    def validate_password_length(cls, v):
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Password must be 72 bytes or less when encoded as UTF-8')
        return v

class UserUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    bio: Optional[str] = Field(default=None, max_length=2_000)
    profile_picture: Optional[str] = Field(default=None, max_length=2_048)
    subscription_plan: Optional[str] = Field(default=None, max_length=50)
    subscription_status: Optional[str] = Field(default=None, max_length=50)

class User(UserBase):
    id: int
    is_verified: bool
    career_preferences: Optional[dict] = None
    stripe_customer_id: Optional[str] = None
    subscription_id: Optional[str] = None
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

