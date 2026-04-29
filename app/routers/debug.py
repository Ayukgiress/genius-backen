from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.models.user import User
from app.crud.user_usage import get_current_month_usage, reset_action_usage_for_month
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/debug", tags=["debug"])

class UpdatePlanRequest(BaseModel):
    plan: str  # "free" or "pro"

@router.get("/user-status")
async def get_user_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get current user's subscription status and job_matching usage (temporary debug endpoint)."""
    now = datetime.now()

    job_usage = await get_current_month_usage(db, current_user.id, "job_matching")

    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "subscription_plan": current_user.subscription_plan,
        "subscription_status": current_user.subscription_status,
        "stripe_customer_id": current_user.stripe_customer_id,
        "subscription_id": current_user.subscription_id,
        "current_job_matching_usage": job_usage,
        "monthly_limit_free": 5,
        "is_pro": current_user.subscription_plan == "pro",
        "can_access_recommendations": current_user.subscription_plan != "free" or job_usage < 5
    }

@router.post("/update-plan")
async def update_user_plan(
    request: UpdatePlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update current user's subscription plan (temporary debug endpoint)."""
    if request.plan not in ["free", "pro"]:
        raise HTTPException(status_code=400, detail="Invalid plan. Must be 'free' or 'pro'")

    current_user.subscription_plan = request.plan
    if request.plan == "pro":
        current_user.subscription_status = "active"
        # Reset usage
        now = datetime.now()
        await reset_action_usage_for_month(db, current_user.id, "job_matching", now.month, now.year)
    else:
        current_user.subscription_status = "inactive"

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    return {"message": f"Plan updated to {request.plan}", "user": await get_user_status(db, current_user)}

