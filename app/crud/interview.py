import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.models.interview import Interview, InterviewMessage
from app.schemas.interview import InterviewCreate, InterviewMessageCreate, InterviewSessionState
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


_ALLOWED_STATE_TRANSITIONS = {
    InterviewSessionState.STARTED: {
        InterviewSessionState.ACTIVE,
        InterviewSessionState.LISTENING,
        InterviewSessionState.AI_SPEAKING,
        InterviewSessionState.WAITING_FOR_USER,
        InterviewSessionState.FAILED,
        InterviewSessionState.COMPLETED,
    },
    InterviewSessionState.ACTIVE: {
        InterviewSessionState.LISTENING,
        InterviewSessionState.AI_SPEAKING,
        InterviewSessionState.WAITING_FOR_USER,
        InterviewSessionState.NO_SPEECH,
        InterviewSessionState.FAILED,
        InterviewSessionState.COMPLETED,
    },
    InterviewSessionState.LISTENING: {
        InterviewSessionState.ACTIVE,
        InterviewSessionState.AI_SPEAKING,
        InterviewSessionState.WAITING_FOR_USER,
        InterviewSessionState.NO_SPEECH,
        InterviewSessionState.FAILED,
        InterviewSessionState.COMPLETED,
    },
    InterviewSessionState.AI_SPEAKING: {
        InterviewSessionState.ACTIVE,
        InterviewSessionState.LISTENING,
        InterviewSessionState.WAITING_FOR_USER,
        InterviewSessionState.FAILED,
        InterviewSessionState.COMPLETED,
    },
    InterviewSessionState.WAITING_FOR_USER: {
        InterviewSessionState.ACTIVE,
        InterviewSessionState.LISTENING,
        InterviewSessionState.AI_SPEAKING,
        InterviewSessionState.FAILED,
        InterviewSessionState.COMPLETED,
    },
    InterviewSessionState.NO_SPEECH: {
        InterviewSessionState.ACTIVE,
        InterviewSessionState.LISTENING,
        InterviewSessionState.FAILED,
        InterviewSessionState.COMPLETED,
    },
    InterviewSessionState.FAILED: {
        InterviewSessionState.ACTIVE,
        InterviewSessionState.LISTENING,
        InterviewSessionState.COMPLETED,
    },
    InterviewSessionState.COMPLETED: set(),
}


def _coerce_interview_state(value: str | InterviewSessionState) -> InterviewSessionState:
    # Accept legacy ongoing values during rolling deployments; new responses
    # and writes always use the explicit lifecycle vocabulary.
    if value == "ongoing":
        return InterviewSessionState.WAITING_FOR_USER
    return InterviewSessionState(value)

async def get_interview(db: AsyncSession, interview_id: int):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    return result.scalar_one_or_none()

async def get_interviews_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(Interview).where(Interview.user_id == user_id)
    )
    return result.scalars().all()

async def list_interviews_by_user(
    db: AsyncSession,
    user_id: int,
    *,
    job_id: Optional[str] = None,
    session_state: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
):
    query = select(Interview).where(Interview.user_id == user_id)
    if job_id is not None:
        query = query.where(Interview.job_id == job_id)
    if session_state is not None:
        query = query.where(Interview.status == session_state)
    result = await db.execute(
        query.order_by(Interview.updated_at.desc(), Interview.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()

async def get_interview_status_counts(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(Interview.status, func.count(Interview.id))
        .where(Interview.user_id == user_id)
        .group_by(Interview.status)
    )
    return {state: count for state, count in result.all()}

async def get_open_interview_for_job(db: AsyncSession, user_id: int, job_id: str):
    result = await db.execute(
        select(Interview)
        .where(
            Interview.user_id == user_id,
            Interview.job_id == job_id,
            Interview.status.notin_((InterviewSessionState.COMPLETED.value, InterviewSessionState.FAILED.value)),
        )
        .order_by(Interview.updated_at.desc(), Interview.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()

async def get_or_create_interview(
    db: AsyncSession,
    interview: InterviewCreate,
    user_id: int,
):
    """Return the active session for this user/job or atomically create one."""
    existing = await get_open_interview_for_job(db, user_id, interview.job_id)
    if existing is not None:
        return existing, False
    try:
        return await create_interview(db, interview, user_id), True
    except IntegrityError:
        # A concurrent request may have won the unique active-session index.
        await db.rollback()
        existing = await get_open_interview_for_job(db, user_id, interview.job_id)
        if existing is None:
            raise
        return existing, False

async def get_interviews_by_job(db: AsyncSession, user_id: int, job_id: str):
    result = await db.execute(
        select(Interview).where(
            Interview.user_id == user_id,
            Interview.job_id == job_id
        )
    )
    return result.scalars().all()

async def create_interview(db: AsyncSession, interview: InterviewCreate, user_id: int):
    initial_state = _coerce_interview_state(interview.status)
    if initial_state not in {InterviewSessionState.STARTED, InterviewSessionState.ACTIVE}:
        initial_state = InterviewSessionState.STARTED
    db_interview = Interview(
        user_id=user_id,
        job_id=interview.job_id,
        status=initial_state.value,
        persona_config=interview.persona_config,
        session_metadata=interview.session_metadata,
        interviewer_type=interview.interviewer_type,
        camera_settings=interview.camera_settings,
        audio_settings=interview.audio_settings,
    )
    db.add(db_interview)
    try:
        await db.commit()
        await db.refresh(db_interview)
    except Exception:
        await db.rollback()
        logger.exception("Interview insert failed: user_id=%s job_id=%s", user_id, interview.job_id)
        raise
    return db_interview

async def update_interview_status(
    db: AsyncSession,
    interview_id: int,
    status: str | InterviewSessionState,
):
    next_state = _coerce_interview_state(status)
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    db_interview = result.scalar_one_or_none()
    if db_interview:
        current_state = _coerce_interview_state(db_interview.status)
        if current_state != next_state and next_state not in _ALLOWED_STATE_TRANSITIONS[current_state]:
            raise ValueError(f"Invalid interview state transition: {current_state.value} -> {next_state.value}")
        db_interview.status = next_state.value
        db.add(db_interview)
        try:
            await db.commit()
            await db.refresh(db_interview)
        except Exception:
            await db.rollback()
            logger.exception(
                "Interview state update failed: interview_id=%s target_state=%s",
                interview_id,
                next_state.value,
            )
            raise
    return db_interview

async def delete_interview(db: AsyncSession, interview_id: int):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    db_interview = result.scalar_one_or_none()
    if db_interview:
        try:
            await db.delete(db_interview)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Interview delete failed: interview_id=%s", interview_id)
            raise
    return True

# Interview Message CRUD
async def create_interview_message(
    db: AsyncSession,
    interview_id: int,
    message: InterviewMessageCreate,
    transcript: Optional[str] = None,
    visual_data: Optional[Dict[str, Any]] = None,
    audio_data: Optional[str] = None,
    ai_avatar_video_url: Optional[str] = None,
    video_url: Optional[str] = None,
    avatar_id: Optional[str] = None,
    avatar_type: Optional[str] = None,
    avatar_style: Optional[str] = None,
    response_mode: Optional[str] = None,
    speaking_state: Optional[str] = None,
    persona: Optional[Any] = None,
    video_status: Optional[str] = None,
    playback_metadata: Optional[Dict[str, Any]] = None,
):
    db_message = InterviewMessage(
        interview_id=interview_id,
        role=message.role,
        content=message.content,
        transcript=transcript,
        visual_data=visual_data,
        audio_data=audio_data if audio_data else getattr(message, 'audio_data', None),
        ai_avatar_video_url=ai_avatar_video_url or video_url or message.video_url,
        video_url=video_url or ai_avatar_video_url or message.video_url,
        avatar_id=avatar_id if avatar_id is not None else message.avatar_id,
        avatar_type=avatar_type,
        avatar_style=avatar_style if avatar_style is not None else message.avatar_style,
        response_mode=response_mode if response_mode is not None else message.response_mode,
        speaking_state=speaking_state if speaking_state is not None else message.speaking_state,
        persona=persona if persona is not None else message.persona,
        video_status=video_status if video_status is not None else message.video_status,
        playback_metadata=(
            playback_metadata if playback_metadata is not None else message.playback_metadata
        ),
    )
    db.add(db_message)
    try:
        await db.commit()
        await db.refresh(db_message)
    except Exception:
        await db.rollback()
        logger.exception(
            "Interview message insert failed: interview_id=%s role=%s",
            interview_id,
            message.role,
        )
        raise
    return db_message


async def create_interview_turn_messages(
    db: AsyncSession,
    interview_id: int,
    user_message: InterviewMessageCreate,
    assistant_message: InterviewMessageCreate,
    *,
    transcript: Optional[str] = None,
    visual_data: Optional[Dict[str, Any]] = None,
    audio_data: Optional[str] = None,
    ai_avatar_video_url: Optional[str] = None,
    video_url: Optional[str] = None,
    avatar_id: Optional[str] = None,
    avatar_type: Optional[str] = None,
    avatar_style: Optional[str] = None,
    response_mode: Optional[str] = None,
    speaking_state: Optional[str] = None,
    persona: Optional[Any] = None,
    video_status: Optional[str] = None,
    playback_metadata: Optional[Dict[str, Any]] = None,
):
    """Persist both sides of an AI turn atomically, rolling back partial turns."""
    user_row = InterviewMessage(
        interview_id=interview_id,
        role=user_message.role,
        content=user_message.content,
        transcript=transcript,
    )
    assistant_row = InterviewMessage(
        interview_id=interview_id,
        role=assistant_message.role,
        content=assistant_message.content,
        transcript=transcript,
        visual_data=visual_data,
        audio_data=audio_data,
        ai_avatar_video_url=ai_avatar_video_url or video_url or assistant_message.video_url,
        video_url=video_url or ai_avatar_video_url or assistant_message.video_url,
        avatar_id=avatar_id if avatar_id is not None else assistant_message.avatar_id,
        avatar_type=avatar_type,
        avatar_style=avatar_style if avatar_style is not None else assistant_message.avatar_style,
        response_mode=response_mode if response_mode is not None else assistant_message.response_mode,
        speaking_state=speaking_state if speaking_state is not None else assistant_message.speaking_state,
        persona=persona if persona is not None else assistant_message.persona,
        video_status=video_status if video_status is not None else assistant_message.video_status,
        playback_metadata=(
            playback_metadata if playback_metadata is not None else assistant_message.playback_metadata
        ),
    )
    db.add_all([user_row, assistant_row])
    try:
        await db.commit()
        await db.refresh(user_row)
        await db.refresh(assistant_row)
    except Exception:
        await db.rollback()
        logger.exception("Interview turn persistence failed: interview_id=%s", interview_id)
        raise
    return user_row, assistant_row

async def get_interview_messages(db: AsyncSession, interview_id: int):
    result = await db.execute(
        select(InterviewMessage).where(InterviewMessage.interview_id == interview_id)
        .order_by(InterviewMessage.created_at)
    )
    return result.scalars().all()

async def get_interview_messages_for_interviews(db: AsyncSession, interview_ids: List[int]):
    if not interview_ids:
        return {}
    result = await db.execute(
        select(InterviewMessage)
        .where(InterviewMessage.interview_id.in_(interview_ids))
        .order_by(InterviewMessage.created_at, InterviewMessage.id)
    )
    messages_by_interview = {interview_id: [] for interview_id in interview_ids}
    for message in result.scalars().all():
        messages_by_interview.setdefault(message.interview_id, []).append(message)
    return messages_by_interview


# ---------------------------------------------------------------------------
# Config / question plan / transcript helpers
# ---------------------------------------------------------------------------

async def update_interview_config(
    db: AsyncSession, interview_id: int, config: Dict[str, Any]
) -> Optional[Interview]:
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()
    if not interview:
        return None
    interview.config = config
    db.add(interview)
    try:
        await db.commit()
        await db.refresh(interview)
    except Exception:
        await db.rollback()
        logger.exception("Interview config update failed: interview_id=%s", interview_id)
        raise
    return interview


async def _get_session_metadata(db: AsyncSession, interview_id: int) -> Optional[Dict[str, Any]]:
    result = await db.execute(
        select(Interview.session_metadata).where(Interview.id == interview_id)
    )
    row = result.scalar_one_or_none()
    return row if isinstance(row, dict) else {}


async def save_question_plan(
    db: AsyncSession, interview_id: int, plan: Dict[str, Any]
) -> Optional[Interview]:
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()
    if not interview:
        return None
    metadata = dict(interview.session_metadata or {})
    metadata["question_plan"] = plan
    interview.session_metadata = metadata
    db.add(interview)
    try:
        await db.commit()
        await db.refresh(interview)
    except Exception:
        await db.rollback()
        logger.exception("Question plan save failed: interview_id=%s", interview_id)
        raise
    return interview


async def get_question_plan(db: AsyncSession, interview_id: int) -> Optional[Dict[str, Any]]:
    metadata = await _get_session_metadata(db, interview_id)
    return metadata.get("question_plan") if metadata else None


async def update_covered_competencies(
    db: AsyncSession, interview_id: int, covered: List[str]
) -> Optional[Interview]:
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()
    if not interview:
        return None
    metadata = dict(interview.session_metadata or {})
    metadata["covered_competencies"] = list(covered)
    interview.session_metadata = metadata
    db.add(interview)
    try:
        await db.commit()
        await db.refresh(interview)
    except Exception:
        await db.rollback()
        logger.exception("Covered competencies update failed: interview_id=%s", interview_id)
        raise
    return interview


async def get_covered_competencies(db: AsyncSession, interview_id: int) -> List[str]:
    metadata = await _get_session_metadata(db, interview_id)
    val = metadata.get("covered_competencies", []) if metadata else []
    return list(val) if isinstance(val, list) else []


async def append_transcript_segment(
    db: AsyncSession, interview_id: int, segment: Dict[str, Any]
) -> Optional[Interview]:
    result = await db.execute(select(Interview).where(Interview.id == interview_id))
    interview = result.scalar_one_or_none()
    if not interview:
        return None
    segments = list(interview.transcript_segments or [])
    segments.append(segment)
    interview.transcript_segments = segments
    db.add(interview)
    try:
        await db.commit()
        await db.refresh(interview)
    except Exception:
        await db.rollback()
        logger.exception("Transcript segment append failed: interview_id=%s", interview_id)
        raise
    return interview


async def get_transcript_segments(db: AsyncSession, interview_id: int) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Interview.transcript_segments).where(Interview.id == interview_id)
    )
    row = result.scalar_one_or_none()
    return list(row) if isinstance(row, list) else []


async def set_interview_completed(db: AsyncSession, interview_id: int) -> Optional[Interview]:
    return await update_interview_status(db, interview_id, InterviewSessionState.COMPLETED)


# ---------------------------------------------------------------------------
# Interview Report CRUD
# ---------------------------------------------------------------------------
from app.models.interview import InterviewReport
from app.schemas.interview import InterviewReportCreate


async def get_interview_report(db: AsyncSession, interview_id: int):
    result = await db.execute(
        select(InterviewReport).where(InterviewReport.interview_id == interview_id)
    )
    return result.scalar_one_or_none()


async def get_interview_reports_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(InterviewReport).where(InterviewReport.user_id == user_id)
    )
    return result.scalars().all()


async def create_interview_report(db: AsyncSession, report: InterviewReportCreate):
    db_report = InterviewReport(**report.model_dump())
    db.add(db_report)
    try:
        await db.commit()
        await db.refresh(db_report)
    except Exception:
        await db.rollback()
        logger.exception("Interview report insert failed: interview_id=%s", report.interview_id)
        raise
    return db_report


async def upsert_interview_report(db: AsyncSession, report: InterviewReportCreate):
    existing = await get_interview_report(db, report.interview_id)
    if existing:
        for key, value in report.model_dump().items():
            setattr(existing, key, value)
        db.add(existing)
        try:
            await db.commit()
            await db.refresh(existing)
        except Exception:
            await db.rollback()
            logger.exception("Interview report update failed: interview_id=%s", report.interview_id)
            raise
        return existing
    return await create_interview_report(db, report)

