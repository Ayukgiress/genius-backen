from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.analytics import Analytics
from app.schemas.analytics import AnalyticsCreate
from datetime import datetime
from typing import Optional

async def create_analytics_event(db: AsyncSession, event: AnalyticsCreate):
    db_event = Analytics(**event.model_dump())
    db.add(db_event)
    await db.commit()
    await db.refresh(db_event)
    return db_event

async def get_analytics_by_user(
    db: AsyncSession,
    user_id: int,
    *,
    event_type: Optional[str] = None,
    interview_id: Optional[int] = None,
    job_id: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 100,
):
    query = select(Analytics).where(Analytics.user_id == user_id)
    if event_type is not None:
        query = query.where(Analytics.event_type == event_type)
    if interview_id is not None:
        query = query.where(Analytics.interview_id == interview_id)
    if job_id is not None:
        query = query.where(Analytics.job_id == job_id)
    if since is not None:
        query = query.where(Analytics.created_at >= since)
    if until is not None:
        query = query.where(Analytics.created_at <= until)
    result = await db.execute(
        query.order_by(Analytics.created_at.desc(), Analytics.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()

async def count_analytics_by_type(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(Analytics.event_type, func.count(Analytics.id))
        .where(Analytics.user_id == user_id)
        .group_by(Analytics.event_type)
    )
    return {event_type: count for event_type, count in result.all()}
