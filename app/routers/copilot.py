from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.models.user import User
from app.schemas.copilot import NextActionsResponse, CopilotChatRequest, CopilotChatResponse, WeeklySummary
from app.services.copilot import copilot_service

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.get("/next-actions", response_model=NextActionsResponse)
async def get_next_actions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    actions = await copilot_service.get_next_actions(db, current_user.id)
    return NextActionsResponse(
        actions=actions,
        generated_at=datetime.now(timezone.utc)
    )


@router.post("/chat", response_model=CopilotChatResponse)
async def copilot_chat(
    request: CopilotChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await copilot_service.chat(db, current_user.id, request.message, [h.model_dump() for h in request.history])
    return CopilotChatResponse(**result)


@router.get("/weekly-summary", response_model=WeeklySummary)
async def get_weekly_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    summary = await copilot_service.generate_weekly_summary(db, current_user.id)
    return WeeklySummary(**summary)
