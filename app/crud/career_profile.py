from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.career_profile import CareerProfile
from app.schemas.career_profile import CareerProfileCreate, CareerProfileUpdate


async def get_career_profile_by_user(
    db: AsyncSession, user_id: int
) -> Optional[CareerProfile]:
    result = await db.execute(
        select(CareerProfile).where(CareerProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_or_update_career_profile(
    db: AsyncSession, user_id: int, profile_in: CareerProfileCreate
) -> CareerProfile:
    existing = await get_career_profile_by_user(db, user_id)
    if existing:
        for key, value in profile_in.model_dump(exclude_unset=True).items():
            setattr(existing, key, value)
        db.add(existing)
        await db.commit()
        await db.refresh(existing)
        return existing

    profile = CareerProfile(user_id=user_id, **profile_in.model_dump())
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def update_career_profile(
    db: AsyncSession, user_id: int, profile_in: CareerProfileUpdate
) -> Optional[CareerProfile]:
    existing = await get_career_profile_by_user(db, user_id)
    if not existing:
        return None
    update_data = profile_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(existing, key, value)
    db.add(existing)
    await db.commit()
    await db.refresh(existing)
    return existing


async def delete_career_profile(db: AsyncSession, user_id: int) -> bool:
    existing = await get_career_profile_by_user(db, user_id)
    if not existing:
        return False
    await db.delete(existing)
    await db.commit()
    return True
