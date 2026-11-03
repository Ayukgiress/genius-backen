from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.models.event import Event
from app.schemas.event import EventCreate


async def create_event(
    db: AsyncSession, user_id: int, event_type: str, payload: Optional[dict] = None
) -> Event:
    event = Event(user_id=user_id, event_type=event_type, payload=payload)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def create_event_from_schema(
    db: AsyncSession, event_in: EventCreate
) -> Event:
    return await create_event(
        db, user_id=event_in.user_id, event_type=event_in.event_type, payload=event_in.payload
    )


async def get_events_for_user(
    db: AsyncSession,
    user_id: int,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> List[Event]:
    query = select(Event).where(Event.user_id == user_id)
    if event_type:
        query = query.where(Event.event_type == event_type)
    query = query.order_by(desc(Event.created_at)).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())
