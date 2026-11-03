"""Event tracking helpers used to power suggestions later."""

from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud.event import create_event


async def track_event(
    db: AsyncSession,
    user_id: int,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
):
    """Record a user-facing event (analysis_done, applied, interview_completed, card_moved)."""
    return await create_event(db, user_id=user_id, event_type=event_type, payload=payload)
