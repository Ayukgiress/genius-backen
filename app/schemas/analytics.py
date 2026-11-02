import json

from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from typing import Optional, Any

class AnalyticsBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: int = Field(gt=0)
    event_type: str = Field(min_length=1, max_length=100)
    interview_id: Optional[int] = Field(default=None, gt=0)
    job_id: Optional[str] = Field(default=None, min_length=1, max_length=50)
    payload: Optional[dict[str, Any]] = None

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, payload: Optional[dict[str, Any]]):
        if payload is not None and len(json.dumps(payload, default=str)) > 64_000:
            raise ValueError("Analytics payload must not exceed 64 KB")
        return payload

class AnalyticsCreate(AnalyticsBase):
    # The server always assigns the authenticated user's ID; accepting this
    # field preserves internal event construction while making it optional for clients.
    user_id: Optional[int] = Field(default=None, gt=0)

class Analytics(AnalyticsBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
