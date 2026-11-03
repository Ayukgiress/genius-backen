import asyncio
import logging
import time
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
    InterviewWebSocketConfig, InterviewWebSocketUserText, InterviewWebSocketEnd,
    InterviewWebSocketPing, InterviewConfig, TranscriptSegment,
    InterviewReportResponse, InterviewReportCreate, InterviewTrendsResponse,
)
from app.crud.interview import (
    get_interview, list_interviews_by_user, get_interview_status_counts,
    get_interview_messages_for_interviews, get_or_create_interview,
    update_interview_status, delete_interview,
    create_interview_message, create_interview_turn_messages, get_interview_messages,
    update_interview_config, save_question_plan, get_question_plan,
    update_covered_competencies, get_covered_competencies,
    append_transcript_segment, get_transcript_segments, set_interview_completed,
    get_interview_report, upsert_interview_report,
)
from app.crud.resume import get_resume
from app.services.interview import interview_service
from app.services.job_scraper import job_service
from app.services.analytics import track_interview_event
from app.crud.kanban import get_cards_by_board, get_boards_by_user

from app.crud.user_usage import get_current_month_usage, increment_usage, check_usage_limit
from app.core.config import settings
import logging

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
    # Check usage limits for free users
    if current_user.subscription_plan == "free":
        from app.core.config import settings
        current_usage = await get_current_month_usage(db, current_user.id, "interview")
        if current_usage >= settings.FREE_INTERVIEWS_PER_DAY:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Free users are limited to {settings.FREE_INTERVIEWS_PER_DAY} interviews per day. Please upgrade to Pro for unlimited access.",
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

    if session_created and current_user.subscription_plan == "free":
        await increment_usage(db, current_user.id, "interview")
    elif session_created and current_user.subscription_plan == "pro":
        await increment_usage(db, current_user.id, "interview")

    if not session_created:

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

async def _generate_and_store_report(
    db: AsyncSession,
    interview: Any,
    resume_content: Optional[str] = None,
    kanban_card_id: Optional[int] = None,
) -> None:
    try:
        job = await job_service.match_with_resume(interview.job_id, resume_content or "")
        job_dict = {
            "title": getattr(job, "title", "Unknown"),
            "company": getattr(job, "company", "Unknown"),
            "description": getattr(job, "description", "") or "",
            "requirements": getattr(job, "requirements", "") or "",
        } if job else {"title": "Unknown", "company": "Unknown", "description": "", "requirements": ""}
        
        messages = await get_interview_messages(db, interview.id)
        conversation_history = [{"role": msg.role, "content": msg.content} for msg in messages if msg.role in ["user", "assistant"]]
        
        report_data = await interview_service.generate_interview_feedback(job_dict, conversation_history, resume_content)
        
        report_create = InterviewReportCreate(
            interview_id=interview.id,
            user_id=interview.user_id,
            job_id=interview.job_id,
            resume_id=getattr(interview, "resume_id", None),
            kanban_card_id=kanban_card_id,
            overall_score=report_data.get("overall_score"),
            per_question_scores=report_data.get("per_question_scores"),
            strengths=report_data.get("strengths"),
            gaps=report_data.get("gaps"),
            sample_answer=report_data.get("sample_answer"),
            rubric=report_data.get("rubric"),
            feedback=report_data.get("feedback"),
            report_data=report_data,
        )
        await upsert_interview_report(db, report_create)
        logger.info("Generated interview report for interview_id=%s", interview.id)
    except Exception:
        logger.exception("Failed to generate interview report for interview_id=%s", interview.id)
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
        kanban_card_id = None
        try:
            boards = await get_boards_by_user(db, current_user.id)
            for board in boards:
                cards = await get_cards_by_board(db, board.id)
                for card in cards:
                    if interview.job_id in (card.title or "") or (card.description and interview.job_id in card.description):
                        kanban_card_id = card.id
                        break
                if kanban_card_id:
                    break
        except Exception:
            pass
        resume_content = None
        resume_id = getattr(interview, "resume_id", None)
        if resume_id:
            try:
                resume = await get_resume(db, resume_id)
                if resume and resume.user_id == current_user.id:
                    resume_content = resume.content
            except Exception:
                pass
        await _generate_and_store_report(db, interview, resume_content, kanban_card_id)
    return {
        "message": "Interview completed",
        "session_state": InterviewSessionState.COMPLETED.value,
        "interview": updated_interview,
    }


@router.post("/{interview_id}/end")
async def end_interview(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an interview as completed and emit the interview_completed event."""
    interview = await _get_owned_interview(db, interview_id, current_user.id)
    was_completed = interview.status == InterviewSessionState.COMPLETED.value
    updated = await set_interview_completed(db, interview_id)
    if not was_completed:
        await track_interview_event(
            db,
            user_id=current_user.id,
            event_type="interview_completed",
            interview_id=interview_id,
            job_id=interview.job_id,
            payload={"session_state": InterviewSessionState.COMPLETED.value, "source": "interviews.end"},
        )
        kanban_card_id = None
        try:
            boards = await get_boards_by_user(db, current_user.id)
            for board in boards:
                cards = await get_cards_by_board(db, board.id)
                for card in cards:
                    if interview.job_id in (card.title or "") or (card.description and interview.job_id in card.description):
                        kanban_card_id = card.id
                        break
                if kanban_card_id:
                    break
        except Exception:
            pass
        resume_content = None
        resume_id = getattr(interview, "resume_id", None)
        if resume_id:
            try:
                resume = await get_resume(db, resume_id)
                if resume and resume.user_id == current_user.id:
                    resume_content = resume.content
            except Exception:
                pass
        await _generate_and_store_report(db, interview, resume_content, kanban_card_id)
    return {
        "message": "Interview ended",
        "session_state": InterviewSessionState.COMPLETED.value,
        "interview": updated,
    }


@router.get("/{interview_id}/report", response_model=InterviewReportResponse)
async def get_interview_report_by_id(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    interview = await _get_owned_interview(db, interview_id, current_user.id)
    report = await get_interview_report(db, interview_id)
    if not report:
        raise HTTPException(status_code=404, detail="Interview report not found")
    return report


@router.post("/{interview_id}/report/generate")
async def generate_interview_report_endpoint(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    interview = await _get_owned_interview(db, interview_id, current_user.id)
    kanban_card_id = None
    try:
        boards = await get_boards_by_user(db, current_user.id)
        for board in boards:
            cards = await get_cards_by_board(db, board.id)
            for card in cards:
                if interview.job_id in (card.title or "") or (card.description and interview.job_id in card.description):
                    kanban_card_id = card.id
                    break
            if kanban_card_id:
                break
    except Exception:
        pass
    resume_content = None
    resume_id = getattr(interview, "resume_id", None)
    if resume_id:
        try:
            resume = await get_resume(db, resume_id)
            if resume and resume.user_id == current_user.id:
                resume_content = resume.content
        except Exception:
            pass
    await _generate_and_store_report(db, interview, resume_content, kanban_card_id)
    report = await get_interview_report(db, interview_id)
    if not report:
        raise HTTPException(status_code=500, detail="Failed to generate report")
    return report


@router.get("/{interview_id}/transcript", response_model=Dict[str, Any])
async def get_interview_transcript(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the stored transcript segments for an interview."""
    interview = await _get_owned_interview(db, interview_id, current_user.id)
    segments = await get_transcript_segments(db, interview_id)
    return {
        "interview_id": interview_id,
        "segments": [
            TranscriptSegment(
                speaker=s.get("speaker", "assistant"),
                text=s.get("text", ""),
                start_ms=int(s.get("start_ms", 0)),
                end_ms=int(s.get("end_ms", 0)),
            ).model_dump()
            for s in segments
        ],
    }


@router.websocket("/{interview_id}/talk")
async def interview_talk_websocket(
    websocket: WebSocket,
    interview_id: int
):
    """
    Text-only WebSocket interview protocol.

    Client -> server:
        { "type": "auth", "token": "<jwt>" }          (required first)
        { "type": "config", "config": InterviewConfig }
        { "type": "user_text", "text": "<utterance>" }
        { "type": "end" }
        { "type": "ping" }
    Server -> client:
        { "type": "auth_ok", "session_state", "interview_id", "job_id" }
        { "type": "ai_token", "token", "index" }
        { "type": "ai_done", "text" }
        { "type": "end", "session_state", "reason" }
        { "type": "error", "error", "error_type" }
        { "type": "pong" }
    """
    logger.info("WebSocket connection attempt for interview %s", interview_id)
    await websocket.accept()

    db = None
    db_gen = None
    try:
        db_gen = get_db()
        db = await anext(db_gen)

        # ---- authentication ----
        try:
            raw_auth = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except (ValueError, TypeError):
            await websocket.send_json({"type": "error", "error": "Malformed auth payload.", "error_type": "format"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            auth_message = InterviewWebSocketAuth.model_validate(raw_auth)
        except ValidationError:
            await websocket.send_json({"type": "error", "error": "Authentication required.", "error_type": "authentication"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            user = await get_user_from_token(db, auth_message.token)
        except HTTPException:
            await websocket.send_json({"type": "error", "error": "Invalid authentication token.", "error_type": "authentication"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            interview = await _get_owned_interview(db, interview_id, user.id)
        except HTTPException:
            await websocket.send_json({"type": "error", "error": "Interview not found.", "error_type": "not_found"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if interview.status == InterviewSessionState.COMPLETED.value:
            await websocket.send_json({"type": "end", "session_state": InterviewSessionState.COMPLETED.value, "reason": "already_completed"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # ---- configuration ----
        try:
            raw_config = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "error", "error": "Interview config not received.", "error_type": "format"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except WebSocketDisconnect:
            return

        try:
            config_message = InterviewWebSocketConfig.model_validate(raw_config)
        except ValidationError:
            # Default config if client omits it.
            config_message = InterviewWebSocketConfig(type="config", config=InterviewConfig())

        config = config_message.config
        config_dict = config.model_dump()
        await update_interview_config(db, interview_id, config_dict)

        # ---- resume content (optional) ----
        resume_content = None
        if config_message.config and hasattr(config_message.config, "resume_id"):
            pass  # resume_id not on InterviewConfig; kept for future extension

        # ---- job context ----
        job = await job_service.match_with_resume(interview.job_id, resume_content or "")
        if not job:
            await websocket.send_json({"type": "error", "error": "Job not found.", "error_type": "not_found"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        job_dict = {
            "title": job.title,
            "company": job.company,
            "description": job.description or "",
            "requirements": job.requirements or "",
        }

        await track_interview_event(
            db,
            user_id=user.id,
            event_type="interview_started",
            interview_id=interview.id,
            job_id=interview.job_id,
            payload={"session_state": InterviewSessionState.STARTED.value, "source": "websocket.talk"},
        )

        await _set_session_state(db, interview.id, InterviewSessionState.ACTIVE)
        interview.status = InterviewSessionState.ACTIVE.value

        # ---- question plan ----
        plan = await get_question_plan(db, interview.id)
        if not plan:
            plan = await interview_service.generate_question_plan(job_dict, resume_content, config_dict)
            await save_question_plan(db, interview.id, plan)
        if isinstance(plan, dict):
            plan["cached"] = True

        covered = await get_covered_competencies(db, interview.id)
        duration_seconds = float(config.duration) * 60.0
        start_time = time.monotonic()
        idle_timeout_seconds = 90.0
        last_activity = time.monotonic()
        from app.core.config import settings
        max_duration_seconds = float(settings.MAX_SESSION_LENGTH_MINUTES) * 60.0
        if duration_seconds > max_duration_seconds:
            duration_seconds = max_duration_seconds
            config.duration = settings.MAX_SESSION_LENGTH_MINUTES

        def elapsed_min() -> float:
            return max(0.0, (duration_seconds - (time.monotonic() - start_time)) / 60.0)

        async def send_tokens(conversation_history: List[Dict[str, str]], turn_count: int) -> str:
            full = []
            index = 0
            async for token in interview_service.continue_interview_stream(
                conversation_history, interview.job_id, resume_content, config_dict, plan, covered,
                turn_count, elapsed_min(),
            ):
                full.append(token)
                await websocket.send_json({"type": "ai_token", "token": token, "index": index})
                index += 1
            return "".join(full)

        # ---- initial AI question ----
        initial_text = await send_tokens([], 1)
        await websocket.send_json({"type": "ai_done", "text": initial_text})
        now_ms = int(time.time() * 1000)
        await append_transcript_segment(
            db, interview.id,
            {"speaker": "assistant", "text": initial_text, "start_ms": now_ms, "end_ms": now_ms},
        )
        await websocket.send_json({
            "type": "auth_ok",
            "session_state": InterviewSessionState.ACTIVE.value,
            "interview_id": interview.id,
            "job_id": interview.job_id,
        })

        turn_count = 1
        while True:
            # duration cap
            if elapsed_min() <= 0:
                await websocket.send_json({"type": "end", "session_state": InterviewSessionState.COMPLETED.value, "reason": "duration_cap"})
                await set_interview_completed(db, interview.id)
                break

            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=idle_timeout_seconds)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "end", "session_state": InterviewSessionState.COMPLETED.value, "reason": "idle_timeout"})
                await set_interview_completed(db, interview.id)
                break
            except WebSocketDisconnect:
                break

            if not isinstance(data, dict):
                await websocket.send_json({"type": "error", "error": "Message payload must be a JSON object.", "error_type": "format"})
                continue

            mtype = data.get("type")

            if mtype == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if mtype == "end":
                await websocket.send_json({"type": "end", "session_state": InterviewSessionState.COMPLETED.value, "reason": "user_end"})
                await set_interview_completed(db, interview.id)
                break

            if mtype == "user_text":
                try:
                    msg = InterviewWebSocketUserText.model_validate(data)
                except ValidationError:
                    await websocket.send_json({"type": "error", "error": "Invalid user_text payload.", "error_type": "format"})
                    continue
                text = msg.text.strip()
                if not text:
                    continue

                # record user segment
                seg_start_ms = int(time.time() * 1000)
                await append_transcript_segment(
                    db, interview.id,
                    {"speaker": "user", "text": text, "start_ms": seg_start_ms, "end_ms": seg_start_ms},
                )
                last_activity = time.monotonic()
                turn_count += 1

                # build conversation history from persisted transcript segments
                segments = await get_transcript_segments(db, interview.id)
                history = [
                    {"role": "user" if s.get("speaker") == "user" else "assistant", "content": s.get("text", "")}
                    for s in segments
                ]

                # advance plan: mark current competency covered when we have a plan
                if isinstance(plan, dict):
                    questions = plan.get("questions", [])
                    idx = int(plan.get("current_index", 0))
                    if 0 <= idx < len(questions):
                        comp = questions[idx].get("competency")
                        if comp and comp not in covered:
                            covered.append(comp)
                        questions[idx]["covered"] = True
                        plan["current_index"] = idx + 1
                        await save_question_plan(db, interview.id, plan)
                        await update_covered_competencies(db, interview.id, covered)

                # stream AI response
                ai_text = await send_tokens(history, turn_count)
                await websocket.send_json({"type": "ai_done", "text": ai_text})

                seg_end_ms = int(time.time() * 1000)
                await append_transcript_segment(
                    db, interview.id,
                    {"speaker": "assistant", "text": ai_text, "start_ms": seg_start_ms, "end_ms": seg_end_ms},
                )

            else:
                await websocket.send_json({"type": "error", "error": "Unknown message type.", "error_type": "format"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for interview %s", interview_id)
    except Exception:
        logger.exception("WebSocket communication failed: interview_id=%s", interview_id)
        try:
            if db is not None and 'interview' in locals() and interview is not None:
                await _set_session_state(db, interview_id, InterviewSessionState.FAILED)
            await websocket.send_json({"type": "error", "error": "Interview communication failed.", "error_type": "ai_generation"})
        except Exception:
            pass
    finally:
        if db_gen is not None:
            await db_gen.aclose()




@router.post("/{interview_id}/negotiate/start")
async def start_negotiation_mode(
    interview_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    interview = await _get_owned_interview(db, interview_id, current_user.id)
    
    # Switch to salary negotiation mode with a second interviewer persona
    from app.schemas.interview import InterviewConfig
    negotiation_config = {
        "type": "mixed",
        "difficulty": "senior",
        "duration": 30,
        "persona": "You are a seasoned HR/recruiting manager in salary negotiation mode. You play a second interviewer persona - professional but firm. You will present a job offer with a specific salary range and benefits package, negotiate based on the candidate's responses, and work towards a final offer. Be realistic but advocate for the company's budget while remaining fair.",
        "language": "en",
        "negotiation_mode": True,
        "offer_made": True,
        "salary_range": {"min": 80000, "max": 95000}
    }
    
    await update_interview_config(db, interview_id, negotiation_config)
    
    return {
        "message": "Salary negotiation mode started",
        "interview_id": interview_id,
        "persona": "HR Negotiator (Second Interviewer)",
        "offer_details": {
            "base_salary_range": {"min": 80000, "max": 95000},
            "benefits": ["Health Insurance", "401k", "Remote Flexibility"],
            "message": "We'd like to extend you an offer. Let's discuss the details."
        }
    }
