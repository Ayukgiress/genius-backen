import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError
from app.db.session import get_db
from app.routers.deps import get_current_user, get_user_from_token
from app.schemas.user import User
from app.schemas.interview import (
    InterviewResponse, InterviewCreate, InterviewMessageResponse,
    InterviewMessageCreate, InterviewAudioMessageCreate,
    InterviewSessionState, InterviewWebSocketAuth,
    InterviewWebSocketAudioMessage, InterviewWebSocketVideoFrame,
)
from app.crud.interview import (
    get_interview, list_interviews_by_user, get_interview_status_counts,
    get_interview_messages_for_interviews, get_or_create_interview,
    update_interview_status, delete_interview,
    create_interview_message, create_interview_turn_messages, get_interview_messages
)
from app.crud.resume import get_resume
from app.services.interview import interview_service
from app.services.analytics import track_interview_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interviews", tags=["interviews"])


def _message_payload(
    interview_id: int,
    *,
    message_id: int = -1,
    role: str = "assistant",
    content: str = "",
    transcript: Optional[str] = None,
    audio_data: Optional[str] = None,
    visual_data: Optional[Dict[str, Any]] = None,
    ai_avatar_video_url: Optional[str] = None,
    video_url: Optional[str] = None,
    avatar_type: Optional[str] = None,
    avatar_style: Optional[str] = None,
    avatar_id: Optional[str] = None,
    response_mode: Optional[str] = None,
    speaking_state: Optional[str] = None,
    persona: Optional[Any] = None,
    video_status: Optional[str] = None,
    playback_metadata: Optional[Dict[str, Any]] = None,
    message_status: str = "success",
    session_state: Optional[str] = None,
    error: Optional[str] = None,
    error_type: Optional[str] = None,
    created_at: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build the shared HTTP/WebSocket message shape plus legacy aliases."""
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    return {
        "id": message_id,
        "interview_id": interview_id,
        "role": role,
        "content": content,
        "transcript": transcript,
        "audio_data": audio_data,
        "visual_data": visual_data,
        "ai_audio_data": audio_data,
        "ai_avatar_video_url": ai_avatar_video_url,
        "video_url": video_url or ai_avatar_video_url,
        "avatar_type": avatar_type,
        "avatar_style": avatar_style,
        "avatar_id": avatar_id,
        "response_mode": response_mode,
        "speaking_state": speaking_state,
        "persona": persona,
        "video_status": video_status,
        "playback_metadata": playback_metadata,
        "status": message_status,
        "response_status": message_status,
        "session_state": session_state,
        "error": error,
        "error_type": error_type,
        "created_at": created_at,
        # Backward-compatible aliases used by earlier clients.
        "audio_content": audio_data,
        "visual_analysis": visual_data,
        "ai_text": content if role == "assistant" else None,
        "ai_audio_base64": audio_data,
        "ai_message_id": message_id if message_id > 0 else None,
    }


def _saved_message_payload(message: Any, **overrides: Any) -> Dict[str, Any]:
    payload = _message_payload(
        message.interview_id,
        message_id=message.id,
        role=message.role,
        content=message.content,
        transcript=message.transcript,
        audio_data=message.audio_data,
        visual_data=message.visual_data,
        ai_avatar_video_url=getattr(message, "ai_avatar_video_url", None),
        video_url=getattr(message, "video_url", None),
        avatar_type=getattr(message, "avatar_type", None),
        avatar_style=getattr(message, "avatar_style", None),
        avatar_id=getattr(message, "avatar_id", None),
        response_mode=getattr(message, "response_mode", None),
        speaking_state=getattr(message, "speaking_state", None),
        persona=getattr(message, "persona", None),
        video_status=getattr(message, "video_status", None),
        playback_metadata=getattr(message, "playback_metadata", None),
        created_at=message.created_at,
    )
    payload.update(overrides)
    payload["response_status"] = payload.get("status", "success")
    return payload


async def _set_session_state(
    db: AsyncSession,
    interview_id: int,
    state: InterviewSessionState,
) -> None:
    await update_interview_status(db, interview_id, state)


def _playback_state(*, audio_data: Optional[str] = None, video_url: Optional[str] = None) -> InterviewSessionState:
    if audio_data or video_url:
        return InterviewSessionState.AI_SPEAKING
    return InterviewSessionState.WAITING_FOR_USER


def _ensure_interview_open(interview: Any) -> None:
    if interview.status == InterviewSessionState.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Interview is already completed")


async def _get_owned_interview(db: AsyncSession, interview_id: int, user_id: int):
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != user_id:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview


async def _process_audio_conversation_turn(
    db: AsyncSession,
    interview: Any,
    base64_audio: str,
) -> tuple[Dict[str, Any], int]:
    """Process, persist, and package one audio turn for either transport."""
    interview_id = interview.id
    await _set_session_state(db, interview_id, InterviewSessionState.LISTENING)
    interview.status = InterviewSessionState.LISTENING.value

    try:
        messages = await get_interview_messages(db, interview_id)
        history = [{"role": msg.role, "content": msg.content} for msg in messages]
        result = await interview_service.handle_audio_turn(
            base64_audio,
            interview.job_id,
            history,
        )
        processed_transcript = result.get("transcript") or ""
        await track_interview_event(
            db,
            user_id=interview.user_id,
            event_type="interview_audio_processed",
            interview_id=interview_id,
            job_id=interview.job_id,
            payload={
                "status": result.get("status", "success"),
                "transcript_characters": len(processed_transcript),
                "error_type": result.get("error_type"),
                "ai_audio_generated": bool(result.get("ai_audio_data") or result.get("ai_audio_base64")),
            },
        )

        if result.get("status") == "error" or result.get("error"):
            error_type = result.get("error_type")
            input_error = error_type in {"format", "decode"}
            next_state = (
                InterviewSessionState.WAITING_FOR_USER
                if input_error
                else InterviewSessionState.FAILED
            )
            await _set_session_state(db, interview_id, next_state)
            interview.status = next_state.value
            return _message_payload(
                interview_id,
                message_status="error",
                session_state=next_state.value,
                error=result.get("error") or "Audio could not be processed.",
                error_type=error_type,
            ), 400 if input_error else 502

        transcript = result.get("transcript") or ""
        if result.get("status") == "no_speech" or not transcript.strip():
            await track_interview_event(
                db,
                user_id=interview.user_id,
                event_type="interview_no_speech",
                interview_id=interview_id,
                job_id=interview.job_id,
                payload={"session_state": InterviewSessionState.NO_SPEECH.value},
            )
            await _set_session_state(db, interview_id, InterviewSessionState.NO_SPEECH)
            interview.status = InterviewSessionState.NO_SPEECH.value
            return _message_payload(
                interview_id,
                transcript="",
                message_status="no_speech",
                session_state=interview.status,
            ), 200

        ai_text = result.get("content") or result.get("ai_text")
        if not ai_text:
            logger.warning("Audio turn returned no AI text for interview %s", interview_id)
            ai_text = "I'm listening, please continue."

        ai_audio = result.get("ai_audio_data") or result.get("ai_audio_base64")
        _, saved_ai_message = await create_interview_turn_messages(
            db,
            interview_id,
            InterviewMessageCreate(role="user", content=transcript),
            InterviewMessageCreate(role="assistant", content=ai_text),
            transcript=transcript,
            visual_data=result.get("visual_data"),
            audio_data=ai_audio,
            ai_avatar_video_url=result.get("ai_avatar_video_url"),
            video_url=result.get("video_url"),
            avatar_type=result.get("avatar_type"),
            avatar_style=result.get("avatar_style"),
            avatar_id=result.get("avatar_id"),
            response_mode=result.get("response_mode"),
            speaking_state=result.get("speaking_state"),
            persona=result.get("persona"),
            video_status=result.get("video_status"),
            playback_metadata=result.get("playback_metadata"),
        )
        await track_interview_event(
            db,
            user_id=interview.user_id,
            event_type="question_generated",
            interview_id=interview_id,
            job_id=interview.job_id,
            payload={"source": "audio_turn", "message_id": saved_ai_message.id},
        )
        final_state = _playback_state(
            audio_data=ai_audio,
            video_url=result.get("ai_avatar_video_url"),
        )
        await _set_session_state(db, interview_id, final_state)
        interview.status = final_state.value
        return _saved_message_payload(
            saved_ai_message,
            session_state=final_state.value,
        ), 200
    except Exception:
        logger.exception("Failed to process interview audio for %s", interview_id)
        await track_interview_event(
            db,
            user_id=interview.user_id,
            event_type="interview_audio_processed",
            interview_id=interview_id,
            job_id=interview.job_id,
            payload={"status": "error", "error_type": "processing"},
        )
        await _set_session_state(db, interview_id, InterviewSessionState.FAILED)
        interview.status = InterviewSessionState.FAILED.value
        return _message_payload(
            interview_id,
            message_status="error",
            session_state=interview.status,
            error="Failed to process audio.",
        ), 502

@router.get("", response_model=List[InterviewResponse])
async def list_interviews(
    job_id: Optional[str] = None,
    session_state: Optional[InterviewSessionState] = None,
    include_messages: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    interviews = await list_interviews_by_user(
        db,
        user_id=current_user.id,
        job_id=job_id,
        session_state=session_state.value if session_state else None,
        offset=offset,
        limit=limit,
    )
    if include_messages and interviews:
        messages_by_interview = await get_interview_messages_for_interviews(
            db, [interview.id for interview in interviews]
        )
        for interview in interviews:
            interview.__dict__["messages"] = messages_by_interview.get(interview.id, [])
    elif not include_messages:
        for interview in interviews:
            interview.__dict__["messages"] = []
    return interviews


@router.get("/dashboard")
async def get_interview_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return lightweight session counts and actionable prep-session alerts."""
    raw_counts = await get_interview_status_counts(db, current_user.id)
    status_counts = {state.value: raw_counts.get(state.value, 0) for state in InterviewSessionState}
    recent = await list_interviews_by_user(
        db,
        user_id=current_user.id,
        offset=0,
        limit=20,
    )
    alerts = []
    for interview in recent:
        if interview.status == InterviewSessionState.FAILED.value:
            alerts.append({
                "type": "interview_failed",
                "interview_id": interview.id,
                "job_id": interview.job_id,
                "session_state": interview.status,
                "updated_at": interview.updated_at,
            })
        elif interview.status == InterviewSessionState.NO_SPEECH.value:
            alerts.append({
                "type": "interview_no_speech",
                "interview_id": interview.id,
                "job_id": interview.job_id,
                "session_state": interview.status,
                "updated_at": interview.updated_at,
            })
    return {
        "total_sessions": sum(status_counts.values()),
        "status_counts": status_counts,
        "recent_sessions": [
            {
                "id": interview.id,
                "job_id": interview.job_id,
                "session_state": interview.session_state,
                "created_at": interview.created_at,
                "updated_at": interview.updated_at,
            }
            for interview in recent
        ],
        "prep_alerts": alerts,
    }

@router.get("/{interview_id}", response_model=InterviewResponse)
async def get_interview_by_id(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    interview = await _get_owned_interview(db, interview_id, current_user.id)
    interview.__dict__['messages'] = await get_interview_messages(db, interview.id)
    return interview

@router.post("", response_model=InterviewResponse, status_code=status.HTTP_201_CREATED)
async def create_new_interview(
    interview_in: InterviewCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    logger.info(
        "Interview creation requested: user_id=%s job_id=%s",
        current_user.id,
        interview_in.job_id,
    )
    try:
        interview, session_created = await get_or_create_interview(
            db, interview_in, user_id=current_user.id
        )
    except Exception as exc:
        logger.exception(
            "Interview session creation failed: user_id=%s job_id=%s",
            current_user.id,
            interview_in.job_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create interview session.",
        ) from exc

    if not session_created:
        logger.info("Reusing interview session: user_id=%s interview_id=%s", current_user.id, interview.id)
        existing_messages = await get_interview_messages(db, interview.id)
        interview.__dict__["messages"] = existing_messages
        interview.__dict__["session_created"] = False
        interview.__dict__["initial_message_status"] = (
            "success" if any(message.role == "assistant" for message in existing_messages) else "pending"
        )
        response.status_code = status.HTTP_200_OK
        return interview

    # Get resume content only when this request actually creates a session.
    resume_content = None
    if interview_in.resume_id:
        resume = await get_resume(db, interview_in.resume_id)
        if resume and resume.user_id == current_user.id:
            resume_content = resume.content

    await track_interview_event(
        db,
        user_id=current_user.id,
        event_type="interview_started",
        interview_id=interview.id,
        job_id=interview.job_id,
        payload={"session_state": InterviewSessionState.STARTED.value, "source": "interviews.create"},
    )

    # Start the AI interview by generating initial message
    try:
        await _set_session_state(db, interview.id, InterviewSessionState.ACTIVE)
        logger.info("Generating initial interview prompt: interview_id=%s job_id=%s", interview.id, interview.job_id)
        start_result = await interview_service.start_interview(interview_in.job_id, resume_content)
        initial_message_content = start_result.get("content") or start_result["initial_message"]
        initial_audio = start_result.get("ai_audio_data") or start_result.get("initial_audio_base64")

        # Save the initial AI message
        ai_message_data = InterviewMessageCreate(
            role="assistant",
            content=initial_message_content
        )
        initial_message = await create_interview_message(
            db, 
            interview.id, 
            ai_message_data,
            audio_data=initial_audio,
            ai_avatar_video_url=start_result.get("ai_avatar_video_url"),
            video_url=start_result.get("video_url"),
            avatar_type=start_result.get("avatar_type"),
            avatar_style=start_result.get("avatar_style"),
            avatar_id=start_result.get("avatar_id"),
            response_mode=start_result.get("response_mode"),
            speaking_state=start_result.get("speaking_state"),
            persona=start_result.get("persona"),
            video_status=start_result.get("video_status"),
            playback_metadata=start_result.get("playback_metadata"),
        )
        interview.__dict__['messages'] = [initial_message]
        final_state = _playback_state(
            audio_data=initial_audio,
            video_url=start_result.get("ai_avatar_video_url"),
        )
        await _set_session_state(db, interview.id, final_state)
        interview.status = final_state.value
        interview.__dict__['initial_message_status'] = "success"
        interview.__dict__['initial_message_error'] = None
        interview.__dict__["session_created"] = True
        await track_interview_event(
            db,
            user_id=current_user.id,
            event_type="question_generated",
            interview_id=interview.id,
            job_id=interview.job_id,
            payload={"source": "interview_initial_prompt", "message_id": initial_message.id},
        )
    except Exception:
        logger.exception("Interview initial prompt failed: user_id=%s interview_id=%s", current_user.id, interview.id)
        await _set_session_state(db, interview.id, InterviewSessionState.FAILED)
        interview.status = InterviewSessionState.FAILED.value
        interview.__dict__['messages'] = []
        interview.__dict__['initial_message_status'] = "error"
        interview.__dict__['initial_message_error'] = "Unable to generate the initial interview prompt."
        interview.__dict__["session_created"] = True

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
    _ensure_interview_open(interview)
    if message_in.role != "user":
        raise HTTPException(status_code=422, detail="Interview messages must use the user role.")

    logger.info("Saving interview user message: user_id=%s interview_id=%s", current_user.id, interview_id)
    try:
        await _set_session_state(db, interview_id, InterviewSessionState.ACTIVE)
        await create_interview_message(db, interview_id, message_in)

        # Get conversation history for AI context
        messages = await get_interview_messages(db, interview_id)
        conversation_history = [
            {"role": msg.role, "content": msg.content} for msg in messages
        ]

        logger.info("Generating interview response: interview_id=%s job_id=%s", interview_id, interview.job_id)
        result = await interview_service.generate_text_turn(
            conversation_history,
            interview.job_id,
            generate_audio=message_in.generate_audio,
        )
    except Exception:
        logger.exception("Interview text turn failed: interview_id=%s", interview_id)
        await _set_session_state(db, interview_id, InterviewSessionState.FAILED)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=_message_payload(
                interview_id,
                message_status="error",
                session_state=InterviewSessionState.FAILED.value,
                error="Failed to generate AI response.",
                error_type="ai_generation",
            ),
        )
    if result.get("response_status") == "error":
        logger.error("Interview AI returned an error: interview_id=%s", interview_id)
        await _set_session_state(db, interview_id, InterviewSessionState.FAILED)
        return JSONResponse(
            status_code=502,
            content=_message_payload(
                interview_id,
                message_status="error",
                session_state=InterviewSessionState.FAILED.value,
                error="Failed to generate AI response.",
            ),
        )

    ai_response_content = result["content"]
    ai_audio = result.get("ai_audio_data")
    ai_message = await create_interview_message(
        db,
        interview_id,
        InterviewMessageCreate(role="assistant", content=ai_response_content),
        audio_data=ai_audio,
        response_mode=result.get("response_mode"),
        ai_avatar_video_url=result.get("ai_avatar_video_url"),
        video_url=result.get("video_url"),
        avatar_type=result.get("avatar_type"),
        avatar_style=result.get("avatar_style"),
        avatar_id=result.get("avatar_id"),
        persona=result.get("persona"),
        speaking_state=result.get("speaking_state"),
        video_status=result.get("video_status"),
        playback_metadata=result.get("playback_metadata"),
    )
    await track_interview_event(
        db,
        user_id=current_user.id,
        event_type="question_generated",
        interview_id=interview_id,
        job_id=interview.job_id,
        payload={"source": "text_turn", "message_id": ai_message.id},
    )
    final_state = _playback_state(audio_data=ai_audio)
    await _set_session_state(db, interview_id, final_state)
    return _saved_message_payload(ai_message, session_state=final_state.value)

@router.post("/{interview_id}/audio", response_model=InterviewMessageResponse)
async def send_audio_message(
    interview_id: int,
    audio_in: InterviewAudioMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    interview = await _get_owned_interview(db, interview_id, current_user.id)
    if interview.status == InterviewSessionState.COMPLETED.value:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_message_payload(
                interview_id,
                message_status="error",
                session_state=InterviewSessionState.COMPLETED.value,
                error="Interview is already completed.",
            ),
        )
    payload, http_status = await _process_audio_conversation_turn(
        db,
        interview,
        audio_in.base64_audio,
    )
    if http_status != status.HTTP_200_OK:
        return JSONResponse(status_code=http_status, content=payload)
    return payload

@router.get("/{interview_id}/messages", response_model=List[InterviewMessageResponse])
async def get_messages(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    interview = await _get_owned_interview(db, interview_id, current_user.id)
    try:
        return await get_interview_messages(db, interview.id)
    except Exception as exc:
        logger.exception("Interview messages query failed: interview_id=%s", interview_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load interview messages.",
        ) from exc

@router.post("/{interview_id}/complete")
async def complete_interview(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    interview = await get_interview(db, interview_id)
    if not interview or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")

    was_completed = interview.status == InterviewSessionState.COMPLETED.value
    updated_interview = await update_interview_status(db, interview_id, InterviewSessionState.COMPLETED)
    if not was_completed:
        await track_interview_event(
            db,
            user_id=current_user.id,
            event_type="interview_completed",
            interview_id=interview_id,
            job_id=interview.job_id,
            payload={"session_state": InterviewSessionState.COMPLETED.value},
        )
    return {
        "message": "Interview completed",
        "session_state": InterviewSessionState.COMPLETED.value,
        "interview": updated_interview,
    }

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

    # Wait for and validate the authentication message without ever logging its token.
    try:
        auth_message = InterviewWebSocketAuth.model_validate(await websocket.receive_json())
        auth_token = auth_message.token
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected before authentication: interview_id=%s", interview_id)
        return
    except (ValidationError, ValueError, TypeError):
        logger.warning("WebSocket authentication payload rejected: interview_id=%s", interview_id)
        await websocket.send_json({
            "error": "Authentication required.",
            "status": "error",
            "error_type": "authentication",
        })
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = None
    db_gen = None
    try:
        db_gen = get_db()
        db = await anext(db_gen)
        try:
            user = await get_user_from_token(db, auth_token)
        except HTTPException:
            logger.warning("WebSocket authentication failed: interview_id=%s reason=invalid_token", interview_id)
            await websocket.send_json({
                "error": "Invalid authentication token.",
                "status": "error",
                "error_type": "authentication",
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            interview = await _get_owned_interview(db, interview_id, user.id)
        except HTTPException:
            logger.warning(
                "WebSocket interview authorization failed: user_id=%s interview_id=%s",
                user.id,
                interview_id,
            )
            await websocket.send_json({"error": "Interview not found.", "status": "error", "error_type": "not_found"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if interview.status == InterviewSessionState.COMPLETED.value:
            await websocket.send_json(_message_payload(
                interview_id,
                message_status="error",
                session_state=InterviewSessionState.COMPLETED.value,
                error="Interview is already completed.",
            ))
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        logger.info("WebSocket authenticated: user_id=%s interview_id=%s", user.id, interview_id)

        # Send authentication success
        await websocket.send_json({
            "status": "authenticated",
            "session_state": interview.status,
            "message": "Ready to receive audio chunks",
        })

        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except (ValueError, TypeError):
                logger.warning("Malformed WebSocket JSON: interview_id=%s", interview_id)
                await websocket.send_json(_message_payload(
                    interview_id,
                    message_status="error",
                    session_state=interview.status,
                    error="Malformed message payload.",
                    error_type="format",
                ))
                continue

            if not isinstance(data, dict):
                logger.warning("Malformed WebSocket message type: interview_id=%s", interview_id)
                await websocket.send_json(_message_payload(
                    interview_id,
                    message_status="error",
                    session_state=interview.status,
                    error="Message payload must be a JSON object.",
                    error_type="format",
                ))
                continue

            if data.get("type") == "audio_chunk":
                try:
                    audio_message = InterviewWebSocketAudioMessage.model_validate(data)
                except ValidationError:
                    logger.warning("Malformed WebSocket audio payload: interview_id=%s", interview_id)
                    await websocket.send_json(_message_payload(
                        interview_id,
                        message_status="error",
                        session_state=interview.status,
                        error="Audio data is required or exceeds the supported size limit.",
                        error_type="format",
                    ))
                    continue
                payload, _ = await _process_audio_conversation_turn(
                    db,
                    interview,
                    audio_message.data,
                )
                await websocket.send_json(payload)

            elif data.get("type") == "video_frame":
                try:
                    video_message = InterviewWebSocketVideoFrame.model_validate(data)
                except ValidationError:
                    logger.warning("Malformed WebSocket video frame: interview_id=%s", interview_id)
                    await websocket.send_json(_message_payload(
                        interview_id,
                        message_status="error",
                        session_state=interview.status,
                        error="Video frame payload is invalid.",
                        error_type="format",
                    ))
                    continue

                frame_data = video_message.data

                await _set_session_state(db, interview_id, InterviewSessionState.ACTIVE)
                interview.status = InterviewSessionState.ACTIVE.value

                messages = await get_interview_messages(db, interview_id)
                conversation_history = [
                    {"role": msg.role, "content": msg.content} for msg in messages
                ]
                result = await interview_service.analyze_video_person(
                    frame_data,
                    timestamp=video_message.timestamp,
                    job_id=interview.job_id,
                    conversation_history=conversation_history,
                    generate_ai=video_message.generate_ai,
                )
                if result.get("status") == "error" or result.get("error"):
                    await _set_session_state(db, interview_id, InterviewSessionState.FAILED)
                    interview.status = InterviewSessionState.FAILED.value
                    await websocket.send_json(_message_payload(
                        interview_id,
                        message_status="error",
                        session_state=interview.status,
                        error="Video frame could not be processed.",
                    ))
                    continue

                ai_text = result.get("content") or result.get("ai_text")
                visual_data = result.get("visual_data") or result.get("visual")
                if ai_text:
                    saved_message = await create_interview_message(
                        db,
                        interview_id,
                        InterviewMessageCreate(role="assistant", content=ai_text),
                        transcript=result.get("transcript"),
                        visual_data=visual_data,
                        ai_avatar_video_url=result.get("ai_avatar_video_url"),
                        video_url=result.get("video_url"),
                        avatar_type=result.get("avatar_type"),
                        avatar_style=result.get("avatar_style"),
                        avatar_id=result.get("avatar_id"),
                        response_mode=result.get("response_mode"),
                        speaking_state=result.get("speaking_state"),
                        persona=result.get("persona"),
                        video_status=result.get("video_status"),
                        playback_metadata=result.get("playback_metadata"),
                    )
                    await track_interview_event(
                        db,
                        user_id=user.id,
                        event_type="question_generated",
                        interview_id=interview_id,
                        job_id=interview.job_id,
                        payload={"source": "video_turn", "message_id": saved_message.id},
                    )
                    final_state = _playback_state(
                        audio_data=result.get("ai_audio_data") or result.get("ai_audio_base64"),
                        video_url=result.get("ai_avatar_video_url"),
                    )
                    await _set_session_state(db, interview_id, final_state)
                    interview.status = final_state.value
                    await websocket.send_json(_saved_message_payload(
                        saved_message,
                        status=result.get("status", "responding"),
                        session_state=interview.status,
                    ))
                else:
                    await websocket.send_json(_message_payload(
                        interview_id,
                        transcript=result.get("transcript"),
                        visual_data=visual_data,
                        message_status=result.get("status", "analyzing"),
                        session_state=interview.status,
                    ))

            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json(_message_payload(
                    interview_id,
                    message_status="error",
                    session_state=interview.status,
                    error="Unknown message type.",
                ))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for interview {interview_id}")
    except Exception:
        logger.exception("WebSocket communication failed: interview_id=%s", interview_id)
        try:
            if db is not None and "interview" in locals() and interview is not None:
                await _set_session_state(db, interview_id, InterviewSessionState.FAILED)
            await websocket.send_json(_message_payload(
                interview_id,
                message_status="error",
                session_state=InterviewSessionState.FAILED.value,
                error="Interview communication failed.",
            ))
        except:
            pass
    finally:
        if db_gen is not None:
            await db_gen.aclose()
