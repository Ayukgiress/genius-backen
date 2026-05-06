import logging
import base64
import io
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
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

@router.get("", response_model=List[InterviewResponse])
async def list_interviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")
    interview.__dict__['messages'] = await get_interview_messages(db, interview.id)
    return interview

@router.post("", response_model=InterviewResponse, status_code=status.HTTP_201_CREATED)
async def create_new_interview(
    interview_in: InterviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
            resume_content=None
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
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")

    updated_interview = await update_interview_status(db, interview_id, "completed")
    return {"message": "Interview completed", "interview": updated_interview}

@router.websocket("/{interview_id}/talk")
async def interview_talk_websocket(
    websocket: WebSocket,
    interview_id: int,
    token: Optional[str] = None
):
    """
    WebSocket endpoint for video-based interview.
    Expects: { "type": "video_chunk", "data": "base64_webp", "timestamp": 1234567890 }
    Responds: { "transcript": "visual_stt", "ai_text": "Next question...", "status": "responding", "visual": {...} }
    """
    await websocket.accept()
    
    db_gen = get_db()
    db = await anext(db_gen)
    
    try:
        interview = await get_interview(db, interview_id)
        if not interview:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        frame_count = 0
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "video_chunk":
                frame_count += 1
                base64_data = data["data"]
                timestamp = data["timestamp"]
                
                # Only generate AI response every 10 frames to avoid spamming LLM
                should_generate_ai = (frame_count % 10 == 0)
                
                # Get history
                messages = await get_interview_messages(db, interview_id)
                conversation_history = [
                    {"role": msg.role, "content": msg.content} for msg in messages
                ]
                
                # Process video frame
                result = await interview_service.process_video_frame(
                    base64_data, 
                    timestamp, 
                    interview.job_id, 
                    conversation_history,
                    generate_ai=should_generate_ai
                )
                
                if "error" in result:
                    await websocket.send_json(result)
                    continue
                
                # Save user video frame analysis as user message
                user_msg = InterviewMessageCreate(
                    role="user",
                    content=result["transcript"]
                )
                await create_interview_message(
                    db, 
                    interview_id, 
                    user_msg,
                    transcript=result["transcript"],
                    visual_data=result["visual"]
                )
                
                # Save AI response if generated
                if result.get("ai_text"):
                    ai_msg = InterviewMessageCreate(
                        role="assistant",
                        content=result["ai_text"]
                    )
                    await create_interview_message(db, interview_id, ai_msg)
                
                # Send result to frontend
                await websocket.send_json(result)
            
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            
            else:
                await websocket.send_json({"error": "Unknown message type", "status": "error"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for interview {interview_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"error": str(e), "status": "error"})
        except:
            pass
