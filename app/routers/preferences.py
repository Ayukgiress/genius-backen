from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from app.schemas.user import CareerPreferences
from app.routers.deps import get_db, get_current_user
from app.models.user import User
from app.crud import user as crud_user

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("/career", response_model=CareerPreferences)
async def get_career_preferences(
    current_user: User = Depends(get_current_user),
):
    """Get user's career preferences."""
    if current_user.career_preferences:
        return CareerPreferences(**current_user.career_preferences)
    return CareerPreferences()


@router.put("/career")
async def update_career_preferences(
    preferences: CareerPreferences,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update user's career preferences."""
    await crud_user.update_career_preferences(
        db, current_user.id, preferences.model_dump(exclude_none=True)
    )
    return {"message": "Career preferences updated successfully"}


@router.delete("/career")
async def delete_career_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete user's career preferences."""
    await crud_user.update_career_preferences(db, current_user.id, None)
    return {"message": "Career preferences deleted successfully"}
