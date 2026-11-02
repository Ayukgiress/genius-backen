from datetime import datetime
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.analytics import Analytics, AnalyticsCreate
from app.crud.analytics import (
    create_analytics_event,
    get_analytics_by_user,
    count_analytics_by_type,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("", response_model=List[Analytics])
async def list_analytics(
    event_type: str | None = None,
    interview_id: int | None = None,
    job_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_analytics_by_user(
        db,
        user_id=current_user.id,
        event_type=event_type,
        interview_id=interview_id,
        job_id=job_id,
        since=since,
        until=until,
        offset=offset,
        limit=limit,
    )

@router.post("", response_model=Analytics, status_code=status.HTTP_201_CREATED)
async def create_analytics(
    event_in: AnalyticsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    event = event_in.model_copy(update={"user_id": current_user.id})
    return await create_analytics_event(db, event)

@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    event_types = await count_analytics_by_type(db, user_id=current_user.id)
    return {
        "total_events": sum(event_types.values()),
        "event_types": event_types
    }
