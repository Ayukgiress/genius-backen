from pydantic import BaseModel, EmailStr, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, List

class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    bio: Optional[str] = None
    subscription_plan: Optional[str] = "free"  # free, pro
    subscription_status: Optional[str] = "inactive"  # inactive, active, canceled, past_due

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
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None

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

