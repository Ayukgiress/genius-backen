import logging
import base64
import io
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db, SessionLocal
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

@router.get("/test-websocket-auth")
async def test_websocket_auth(token: str):
    """Test endpoint to validate WebSocket authentication token"""
    try:
        from jose import jwt, JWTError
        from app.core.config import settings

        if not hasattr(settings, 'SECRET_KEY') or not settings.SECRET_KEY:
            return {"error": "Server configuration error"}

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")

        if email is None:
            return {"error": "Invalid token - missing email"}

        db_gen = get_db()
        db = await anext(db_gen)

        from app.crud.user import get_user_by_email
        user = await get_user_by_email(db, email=email)

        if not user:
            return {"error": "User not found"}

        return {"success": True, "user_id": user.id, "email": email}

    except JWTError as e:
        return {"error": f"JWT decode error: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

@router.websocket("/test-ws")
async def test_websocket(websocket: WebSocket):
    """Simple test WebSocket endpoint that accepts and echoes messages"""
    logger.info("Test WebSocket connection attempt")
    await websocket.accept()
    logger.info("Test WebSocket accepted")
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"Test WebSocket received: {data}")
            await websocket.send_text(f"Echo: {data}")
    except Exception as e:
        logger.error(f"Test WebSocket error: {e}")

@router.websocket("/{interview_id}/talk")
async def interview_talk_websocket(
    websocket: WebSocket,
    interview_id: int
):
    """
    WebSocket endpoint for audio-based interview.
    Requires authentication via first message: { "type": "auth", "token": "jwt_token" }
    Then expects: { "type": "audio_chunk", "data": "base64_webm_opus" }
    Responds: { "transcript": "stt_result", "ai_text": "Next question...", "ai_audio": "base64_webm_opus", "status": "success" }
    """
    logger.info(f"WebSocket connection attempt for interview {interview_id}")
    # Accept WebSocket connection first
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for interview {interview_id}")

    # Wait for authentication message
    try:
        auth_message = await websocket.receive_json()
        if auth_message.get("type") != "auth" or not auth_message.get("token"):
            logger.warning("First message is not authentication")
            await websocket.send_json({"error": "Authentication required. Send {type: 'auth', token: 'your_jwt_token'} as first message", "status": "error"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        auth_token = auth_message["token"]
        logger.info(f"Received authentication token from message for interview {interview_id}")
    except Exception as e:
        logger.error(f"Error receiving auth message: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = None
    try:
        # Decode and validate JWT token
        from jose import jwt, JWTError
        from app.core.config import settings

        try:
            if not hasattr(settings, 'SECRET_KEY') or not settings.SECRET_KEY:
                logger.error("SECRET_KEY not configured")
                await websocket.send_json({"error": "Server configuration error", "status": "error"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            payload = jwt.decode(auth_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError as e:
            logger.error(f"JWT decode error: {e}")
            await websocket.send_json({"error": "Invalid authentication token", "status": "error"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        email: str = payload.get("sub")
        if email is None:
            logger.error("JWT payload missing 'sub' field")
            await websocket.send_json({"error": "Invalid authentication token", "status": "error"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        logger.info(f"JWT decoded successfully for user: {email}")

        db_gen = get_db()
        db = await anext(db_gen)

        # Verify user exists
        from app.crud.user import get_user_by_email
        user = await get_user_by_email(db, email=email)
        if not user:
            logger.error(f"User not found for email: {email}")
            await websocket.send_json({"error": "User not found", "status": "error"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        logger.info(f"User authenticated: {user.id}")

        # Verify interview ownership
        interview = await get_interview(db, interview_id)
        if not interview or interview.user_id != user.id:
            logger.error(f"Interview {interview_id} not found or not owned by user {user.id}")
            await websocket.send_json({"error": "Interview not found or access denied", "status": "error"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        logger.info(f"Interview access verified for user {user.id}, interview {interview_id}")

        # Send authentication success
        await websocket.send_json({"status": "authenticated", "message": "Ready to receive audio chunks"})

        while True:
            data = await websocket.receive_json()

            if data.get("type") == "audio_chunk":
                base64_audio = data["data"]

                # Get conversation history
                messages = await get_interview_messages(db, interview_id)
                conversation_history = [
                    {"role": msg.role, "content": msg.content} for msg in messages
                ]

                # Process audio chunk
                result = await interview_service.process_audio_chunk(
                    base64_audio,
                    interview.job_id,
                    conversation_history
                )

                if "error" in result:
                    await websocket.send_json(result)
                    continue

                # Save user audio transcript as user message
                if result.get("transcript"):
                    user_msg = InterviewMessageCreate(
                        role="user",
                        content=result["transcript"]
                    )
                    await create_interview_message(
                        db,
                        interview_id,
                        user_msg,
                        transcript=result["transcript"]
                    )

                # Save AI response and audio
                if result.get("ai_text"):
                    ai_msg = InterviewMessageCreate(
                        role="assistant",
                        content=result["ai_text"]
                    )
                    # Store AI audio data in the message
                    saved_ai_msg = await create_interview_message(
                        db,
                        interview_id,
                        ai_msg,
                        audio_data=result.get("ai_audio_base64")
                    )

                    # Add audio data to result for frontend
                    result["ai_message_id"] = saved_ai_msg.id

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
