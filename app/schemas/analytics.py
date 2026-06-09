from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, Any

class AnalyticsBase(BaseModel):
    user_id: int
    event_type: str
    payload: Optional[dict[str, Any]] = None

class AnalyticsCreate(AnalyticsBase):
    pass

class Analytics(AnalyticsBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
