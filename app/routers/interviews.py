import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.interview import (
    InterviewResponse, InterviewCreate, InterviewMessageResponse,
    InterviewMessageCreate, InterviewStartRequest
)
from app.crud.interview import (
    get_interview, get_interviews_by_user, get_interviews_by_job,
    create_interview, update_interview_status, delete_interview,
    create_interview_message, get_interview_messages
)
from app.crud.resume import get_resume
from app.services.interview import interview_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interviews", tags=["interviews"])

@router.get("/", response_model=List[InterviewResponse])
async def list_interviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all interviews for the current user."""
    interviews = await get_interviews_by_user(db, user_id=current_user.id)
    # Load messages for each interview
    for interview in interviews:
        interview.__dict__['messages'] = await get_interview_messages(db, interview.id)
    return interviews

@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview_by_id(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific interview by ID."""
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")
    interview.__dict__['messages'] = await get_interview_messages(db, interview.id)
    return interview

@router.post("/", response_model=InterviewResponse, status_code=status.HTTP_201_CREATED)
async def create_new_interview(
    interview_in: InterviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new interview."""
    # Get resume content if provided
    resume_content = None
    if interview_in.resume_id:
        resume = await get_resume(db, interview_in.resume_id)
        if resume and resume.user_id == current_user.id:
            resume_content = resume.content

    # Create the interview
    interview = await create_interview(db, interview_in, user_id=current_user.id)

    # Start the AI interview by generating initial message
    try:
        start_result = await interview_service.start_interview(interview_in.job_id, resume_content)
        initial_message_content = start_result["initial_message"]

        # Save the initial AI message
        ai_message_data = InterviewMessageCreate(
            role="assistant",
            content=initial_message_content
        )
        initial_message = await create_interview_message(db, interview.id, ai_message_data)
        interview.__dict__['messages'] = [initial_message]
    except Exception as e:
        # If AI fails, start with empty messages
        logger.warning(f"Failed to start AI interview: {e}")
        interview.__dict__['messages'] = []

    return interview

@router.delete("/{interview_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview_by_id(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an interview."""
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")
    await delete_interview(db, interview_id)
    return None

@router.post("/{interview_id}/messages", response_model=InterviewMessageResponse)
async def send_message(
    interview_id: int,
    message_in: InterviewMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Send a message in an interview (user message) and get AI response."""
    # Verify interview ownership
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Save user message
    user_message = await create_interview_message(db, interview_id, message_in)

    # Get conversation history for AI context
    messages = await get_interview_messages(db, interview_id)
    conversation_history = [
        {"role": msg.role, "content": msg.content} for msg in messages
    ]

    try:
        # Get AI response
        ai_response_content = await interview_service.continue_interview(
            conversation_history,
            interview.job_id,
            resume_content=None  # Could be enhanced to include resume context
        )

        # Save AI response
        ai_message_data = InterviewMessageCreate(
            role="assistant",
            content=ai_response_content
        )
        ai_message = await create_interview_message(db, interview_id, ai_message_data)

        return ai_message

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate AI response: {str(e)}"
        )

@router.get("/{interview_id}/messages", response_model=List[InterviewMessageResponse])
async def get_messages(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all messages for an interview."""
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")
    return await get_interview_messages(db, interview.id)

@router.post("/{interview_id}/complete")
async def complete_interview(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark an interview as completed."""
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")

    updated_interview = await update_interview_status(db, interview_id, "completed")
    return {"message": "Interview completed", "interview": updated_interview}