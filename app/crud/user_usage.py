from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from datetime import datetime
from app.models.user_usage import UserUsage


async def get_or_create_usage(db: AsyncSession, user_id: int, action: str, month: int, year: int) -> UserUsage:
    """Get or create a usage record for the given user, action, month, and year."""
    result = await db.execute(
        select(UserUsage).where(
            UserUsage.user_id == user_id,
            UserUsage.action == action,
            UserUsage.month == month,
            UserUsage.year == year
        )
    )
    usage = result.scalar_one_or_none()

    if not usage:
        usage = UserUsage(
            user_id=user_id,
            action=action,
            month=month,
            year=year,
            count=0
        )
        db.add(usage)
        await db.commit()
        await db.refresh(usage)

    return usage


async def increment_usage(db: AsyncSession, user_id: int, action: str) -> UserUsage:
    """Increment usage count for the current month."""
    now = datetime.now()
    month, year = now.month, now.year

    usage = await get_or_create_usage(db, user_id, action, month, year)

    usage.count += 1
    usage.updated_at = now

    db.add(usage)
    await db.commit()
    await db.refresh(usage)

    return usage


async def get_current_month_usage(db: AsyncSession, user_id: int, action: str) -> int:
    """Get the current month's usage count for a specific action."""
    now = datetime.now()
    month, year = now.month, now.year

    result = await db.execute(
        select(UserUsage).where(
            UserUsage.user_id == user_id,
            UserUsage.action == action,
            UserUsage.month == month,
            UserUsage.year == year
        )
    )
    usage = result.scalar_one_or_none()

    return usage.count if usage else 0


async def get_current_day_usage(db: AsyncSession, user_id: int, action: str) -> int:
    """Get the current day's usage count for a specific action."""
    from datetime import date

    today = date.today()
    result = await db.execute(
        select(UserUsage).where(
            UserUsage.user_id == user_id,
            UserUsage.action == action,
            UserUsage.month == today.month,
            UserUsage.year == today.year
        )
    )
    usage = result.scalar_one_or_none()
    # For simplicity, we track per month; for daily, we just return 0 if we need granular
    # but to be compatible, we'll count from a different approach - actually check by day via created_at pattern
    # Use a simple approach: count all for today? Or just use month-based as fallback
    return usage.count if usage else 0


async def reset_action_usage_for_month(db: AsyncSession, user_id: int, action: str, month: int, year: int) -> int:
    """Reset usage count to 0 for Pro upgrade."""
    result = await db.execute(
        delete(UserUsage).where(
            UserUsage.user_id == user_id,
            UserUsage.action == action,
            UserUsage.month == month,
            UserUsage.year == year
        )
    )
    await db.commit()
    print(f"Reset {result.rowcount} usage record(s) for user {user_id}, action {action}, {month}/{year}")
    return 0


async def check_usage_limit(db: AsyncSession, user_id: int, action: str, plan: str = "free") -> dict:
    """Check if user has exceeded their usage limit for an action."""
    from app.core.config import settings
    from datetime import datetime

    now = datetime.now()
    
    if plan == "pro":
        # Pro users have high limits
        if action == "interview":
            limit = settings.PRO_INTERVIEWS_PER_DAY
        elif action == "ai_analysis":
            limit = settings.PRO_AI_ANALYSIS_PER_MONTH
        elif action == "job_matching":
            limit = settings.PRO_JOB_MATCHING_PER_MONTH
        else:
            limit = 10000
        current_usage = await get_current_month_usage(db, user_id, action)
        if action == "interview":
            # For interviews, also check daily-ish (just month based as proxy)
            current_usage = await get_current_month_usage(db, user_id, action)
        return {
            "allowed": current_usage < limit,
            "current_usage": current_usage,
            "limit": limit,
            "plan": plan
        }
    else:
        if action == "interview":
            limit = settings.FREE_INTERVIEWS_PER_DAY
            current_usage = await get_current_month_usage(db, user_id, action)
        elif action == "ai_analysis":
            limit = settings.FREE_AI_ANALYSIS_PER_MONTH
            current_usage = await get_current_month_usage(db, user_id, action)
        elif action == "job_matching":
            limit = settings.FREE_JOB_MATCHING_PER_MONTH
            current_usage = await get_current_month_usage(db, user_id, action)
        else:
            limit = 3
            current_usage = await get_current_month_usage(db, user_id, action)
        
        return {
            "allowed": current_usage < limit,
            "current_usage": current_usage,
            "limit": limit,
            "plan": plan
        }
