from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.schemas.career_profile import (
    CareerProfileCreate,
    CareerProfileUpdate,
    CareerProfileResponse,
)
from app.routers.deps import get_db, get_current_user
from app.models.user import User
from app.crud import career_profile as crud_career_profile

router = APIRouter(prefix="/career-profile", tags=["career-profile"])


@router.get("", response_model=CareerProfileResponse)
async def get_career_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's career profile."""
    profile = await crud_career_profile.get_career_profile_by_user(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Career profile not found")
    return profile


@router.put("", response_model=CareerProfileResponse)
async def upsert_career_profile(
    profile_in: CareerProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create or update the current user's career profile."""
    return await crud_career_profile.create_or_update_career_profile(
        db, current_user.id, profile_in
    )


@router.patch("", response_model=CareerProfileResponse)
async def patch_career_profile(
    profile_in: CareerProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update the current user's career profile."""
    profile = await crud_career_profile.update_career_profile(
        db, current_user.id, profile_in
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Career profile not found")
    return profile


@router.delete("")
async def delete_career_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete the current user's career profile."""
    deleted = await crud_career_profile.delete_career_profile(db, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Career profile not found")
    return {"message": "Career profile deleted successfully"}
