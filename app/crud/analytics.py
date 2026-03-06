from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.analytics import Analytics
from app.schemas.analytics import AnalyticsCreate
from typing import List

async def create_analytics_event(db: AsyncSession, event: AnalyticsCreate):
    db_event = Analytics(**event.model_dump())
    db.add(db_event)
    await db.commit()
    await db.refresh(db_event)
    return db_event

async def get_analytics_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(select(Analytics).where(Analytics.user_id == user_id))
    return result.scalars().all()
