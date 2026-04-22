from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.analytics import Analytics, AnalyticsCreate
from app.crud.analytics import create_analytics_event, get_analytics_by_user

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("", response_model=List[Analytics])
async def list_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_analytics_by_user(db, user_id=current_user.id)

@router.post("", response_model=Analytics, status_code=status.HTTP_201_CREATED)
async def create_analytics(
    event_in: AnalyticsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    event_data = event_in.model_dump()
    event_data["user_id"] = current_user.id
    event = AnalyticsCreate(**event_data)
    return await create_analytics_event(db, event)

@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    events = await get_analytics_by_user(db, user_id=current_user.id)
    
    # Calculate summary statistics
    total_events = len(events)
    event_types = {}
    
    for event in events:
        event_type = event.event_type
        event_types[event_type] = event_types.get(event_type, 0) + 1
    
    return {
        "total_events": total_events,
        "event_types": event_types
    }
