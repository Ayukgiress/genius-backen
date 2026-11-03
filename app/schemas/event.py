from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class EventBase(BaseModel):
    user_id: int = Field(gt=0)
    event_type: str = Field(min_length=1, max_length=50)
    payload: Optional[Dict[str, Any]] = Field(default=None)


class EventCreate(EventBase):
    pass


class EventResponse(EventBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
