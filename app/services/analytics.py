import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.analytics import create_analytics_event
from app.schemas.analytics import AnalyticsCreate

logger = logging.getLogger(__name__)


async def track_interview_event(
    db: AsyncSession,
    *,
    user_id: int,
    event_type: str,
    interview_id: int,
    job_id: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Best-effort persistence for a structured interview analytics event."""
    try:
        event = AnalyticsCreate(
            user_id=user_id,
            event_type=event_type,
            interview_id=interview_id,
            job_id=job_id,
            payload=payload or {},
        )
        await create_analytics_event(db, event)
    except Exception:
        logger.exception(
            "Unable to record interview analytics event %s for interview %s",
            event_type,
            interview_id,
        )
        try:
            await db.rollback()
        except Exception:
            logger.debug("Unable to rollback analytics write failure", exc_info=True)
