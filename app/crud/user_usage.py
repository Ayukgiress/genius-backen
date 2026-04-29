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

async def reset_action_usage_for_month(db: AsyncSession, user_id: int, action: str, month: int, year: int) -> int:
    """Reset usage count to 0 for Pro upgrade - automated fix."""
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
