import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.job import JobResponse, JobMatchResponse, JobSearchParams
from app.schemas.kanban import KanbanCardCreate
from app.services.job_scraper import job_service
from app.services.interview import interview_service
from app.crud import kanban as crud_kanban
from app.crud import user as crud_user
from app.crud import interview as crud_interview
from app.crud.user_usage import get_current_month_usage, increment_usage
from app.routers.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.interview import InterviewCreate, InterviewStartRequest, InterviewSessionState
from app.services.analytics import track_interview_event
from datetime import datetime

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


@router.get("/search")
async def search_jobs(
    query: Optional[str] = Query(default=None, max_length=200),
    location: Optional[str] = Query(default=None, max_length=200),
    remote: bool = False,
    job_type: Optional[str] = Query(default=None, max_length=80),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    use_live_data: bool = True,
):
    """Search for jobs with filters."""
    jobs = await job_service.search_jobs(
        query=query,
        location=location,
        remote=remote if remote else None,
        job_type=job_type,
        page=page,
        limit=limit,
        use_live_data=use_live_data,
    )
    return jobs


@router.get("/recommendations")
async def get_recommendations(
    resume_id: Optional[int] = Query(None, description="Resume ID to match against"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    print(f"[DEBUG] User {current_user.id} ({current_user.email}): plan={current_user.subscription_plan}, checking job_matching usage")
    """Get AI-matched job recommendations based on user's resume and career preferences."""
    # Check usage limits for free users
    if current_user.subscription_plan == "free":
        from app.core.config import settings
        current_usage = await get_current_month_usage(db, current_user.id, "job_matching")
        if current_usage >= settings.FREE_JOB_MATCHING_PER_MONTH:  # Allow N job matching requests per month for free users
            return {
                "recommendations": [],
                "limit_reached": True,
                "message": f"Free users are limited to {settings.FREE_JOB_MATCHING_PER_MONTH} job matching requests per month. Please upgrade to Pro for unlimited access."
            }

    resume_content = ""
    career_preferences = None

    if resume_id:
        from app.crud.resume import get_resume as crud_get_resume
        resume = await crud_get_resume(db, resume_id)
        if resume and resume.user_id == current_user.id:
            resume_content = resume.content or ""

    if current_user.career_preferences:
        career_preferences = current_user.career_preferences

    recommendations = await job_service.get_recommendations(
        resume_content,
        career_preferences=career_preferences
    )

    # Increment usage counter for free users
    if current_user.subscription_plan == "free":
        await increment_usage(db, current_user.id, "job_matching")

    return {
        "recommendations": recommendations,
        "limit_reached": False
    }


@router.get("/live-count")
async def get_live_job_count():
    """Get count of live scraped jobs."""
    return {"count": await job_service.get_live_job_count()}


@router.post("/{job_id}/match")
async def match_job(
    job_id: str,
    resume_id: int = Query(..., description="Resume ID to match against"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Match a specific job with a resume."""
    # Check usage limits for free users
    if current_user.subscription_plan == "free":
        from app.core.config import settings
        current_usage = await get_current_month_usage(db, current_user.id, "job_matching")
        if current_usage >= settings.FREE_JOB_MATCHING_PER_MONTH:  # Allow N job matching requests per month for free users
            return {
                "job": None,
                "limit_reached": True,
                "message": f"Free users are limited to {settings.FREE_JOB_MATCHING_PER_MONTH} job matching requests per month. Please upgrade to Pro for unlimited access."
            }

    from app.crud.resume import get_resume as crud_get_resume

    resume = await crud_get_resume(db, resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if resume.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this resume")

    resume_content = resume.content or ""
    matched_job = await job_service.match_with_resume(job_id, resume_content)

    if not matched_job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Increment usage counter for free users
    if current_user.subscription_plan == "free":
        await increment_usage(db, current_user.id, "job_matching")

    return {
        "job": matched_job,
        "limit_reached": False
    }


@router.post("/{job_id}/add-to-kanban")
async def add_to_kanban(
    job_id: str,
    board_id: int = Query(..., description="Kanban board ID"),
    status: str = Query("todo", description="Column status (todo, in_progress, review, done)"),
    resume_id: Optional[int] = Query(None, description="Resume ID for matching"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a job to the Kanban pipeline."""
    board = await crud_kanban.get_board(db, board_id)
    if not board or board.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Board not found")
    
    job = await job_service.match_with_resume(job_id, "")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    card_data = KanbanCardCreate(
        title=job.title,
        description=job.description,
        status=status,
        board_id=board_id
    )
    
    card = await crud_kanban.create_card(db, card_data)
    return card


@router.get("/{job_id}")
async def get_job(job_id: str):
    """Get a specific job by ID."""
    all_jobs = await job_service.scraper.scrape_all_jobs()
    all_jobs.extend(job_service._sample_jobs)

    # Remove duplicates by ID, preferring live jobs over sample jobs
    seen_ids = set()
    unique_jobs = []
    for job in all_jobs:
        if job["id"] not in seen_ids:
            seen_ids.add(job["id"])
            unique_jobs.append(job)

    job = next((j for j in unique_jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/start-interview")
async def start_job_interview(
    job_id: str,
    request: InterviewStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start an AI interview for a specific job."""
    db_interview = None
    try:
        # Persist the session before generation so startup failures are visible
        # as failed sessions rather than disappearing from interview history.
        interview_create = InterviewCreate(job_id=job_id)
        db_interview, session_created = await crud_interview.get_or_create_interview(
            db, interview_create, current_user.id
        )
        logger.info(
            "Job interview session resolved: user_id=%s job_id=%s interview_id=%s created=%s",
            current_user.id,
            job_id,
            db_interview.id,
            session_created,
        )
        if not session_created:
            db_interview.messages = await crud_interview.get_interview_messages(db, db_interview.id)
            db_interview.__dict__["session_created"] = False
            return {
                "interview": db_interview,
                "session_state": db_interview.session_state,
                "session_created": False,
                "job_info": {"title": job_id, "company": None},
            }

        resume_content = None
        if request.resume_id:
            from app.crud.resume import get_resume as crud_get_resume
            resume = await crud_get_resume(db, request.resume_id)
            if resume and resume.user_id == current_user.id:
                resume_content = resume.content

        await track_interview_event(
            db,
            user_id=current_user.id,
            event_type="interview_started",
            interview_id=db_interview.id,
            job_id=job_id,
            payload={"session_state": InterviewSessionState.STARTED.value, "source": "jobs.start_interview"},
        )
        await crud_interview.update_interview_status(
            db, db_interview.id, InterviewSessionState.ACTIVE
        )

        logger.info("Generating initial interview prompt: interview_id=%s job_id=%s", db_interview.id, job_id)
        interview_data = await interview_service.start_interview(job_id, resume_content)

        # Save initial AI message
        from app.schemas.interview import InterviewMessageCreate
        initial_message = InterviewMessageCreate(
            role="assistant",
            content=interview_data["initial_message"]
        )
        saved_initial_message = await crud_interview.create_interview_message(
            db,
            db_interview.id,
            initial_message,
            audio_data=interview_data.get("ai_audio_data") or interview_data.get("initial_audio_base64"),
            ai_avatar_video_url=interview_data.get("ai_avatar_video_url"),
            video_url=interview_data.get("video_url"),
            avatar_type=interview_data.get("avatar_type"),
            avatar_style=interview_data.get("avatar_style"),
            avatar_id=interview_data.get("avatar_id"),
            response_mode=interview_data.get("response_mode"),
            speaking_state=interview_data.get("speaking_state"),
            persona=interview_data.get("persona"),
            video_status=interview_data.get("video_status"),
            playback_metadata=interview_data.get("playback_metadata"),
        )
        await track_interview_event(
            db,
            user_id=current_user.id,
            event_type="question_generated",
            interview_id=db_interview.id,
            job_id=job_id,
            payload={"source": "interview_initial_prompt", "message_id": saved_initial_message.id},
        )
        final_state = (
            InterviewSessionState.AI_SPEAKING
            if interview_data.get("ai_audio_data") or interview_data.get("initial_audio_base64") or interview_data.get("ai_avatar_video_url")
            else InterviewSessionState.WAITING_FOR_USER
        )
        await crud_interview.update_interview_status(db, db_interview.id, final_state)

        # Get the complete interview with messages
        interview = await crud_interview.get_interview(db, db_interview.id)
        interview.messages = await crud_interview.get_interview_messages(db, db_interview.id)
        interview.__dict__["session_created"] = True

        return {
            "interview": interview,
            "session_state": final_state.value,
            "session_created": True,
            "job_info": {
                "title": interview_data["job_title"],
                "company": interview_data["company"]
            }
        }

    except ValueError as e:
        logger.warning(
            "Interview prompt could not be generated: user_id=%s job_id=%s interview_id=%s reason=%s",
            current_user.id,
            job_id,
            getattr(db_interview, "id", None),
            str(e),
        )
        if db_interview is not None:
            await crud_interview.update_interview_status(
                db, db_interview.id, InterviewSessionState.FAILED
            )
        raise HTTPException(status_code=400, detail="Unable to generate an interview prompt for this job.") from e
    except Exception as e:
        logger.exception(
            "Job interview startup failed: user_id=%s job_id=%s interview_id=%s",
            current_user.id,
            job_id,
            getattr(db_interview, "id", None),
        )
        if db_interview is not None:
            await crud_interview.update_interview_status(
                db, db_interview.id, InterviewSessionState.FAILED
            )
        raise HTTPException(status_code=500, detail="Failed to start interview.") from e

@router.get("/{job_id}/research")
async def get_company_research(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.services.interview import interview_service
    from app.services.job_scraper import job_service
    from datetime import datetime, timedelta
    import json
    
    job = await job_service.get_job(job_id) or await job_service.match_with_resume(job_id, "")
    job_dict = {
        "title": getattr(job, "title", "Unknown"),
        "company": getattr(job, "company", "Unknown"),
        "description": getattr(job, "description", "") or "",
        "requirements": getattr(job, "requirements", "") or "",
    } if job else {"title": "Unknown", "company": "Unknown", "description": "", "requirements": ""}
    
    company = job_dict.get("company", "Unknown")
    
    if not interview_service.groq_client:
        raise HTTPException(status_code=503, detail="AI service not configured")
    
    prompt = f"""You are a company research expert. Provide a comprehensive brief for interviewing at this company.

Job: {job_dict}
Company: {company}

Return JSON with:
{{
  "company_summary": "brief company overview",
  "culture": "culture insights",
  "values": ["value1"],
  "likely_questions": [
    {{"question": "...", "reason": "...", "prep_tip": "..."}}
  ],
  "questions_to_ask_them": [
    {{"question": "...", "category": "culture/team/role/growth", "reason": "..."}}
  ],
  "tips": ["tip1"],
  "red_flags": ["..."],
  "recent_news": ["..."]
}}"""
    
    try:
        response = await interview_service.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a company research analyst. Output only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        result["company"] = company
        result["cached_at"] = datetime.utcnow().isoformat()
        result["cache_ttl_hours"] = 24
        result["cached"] = True
        return result
    except Exception as e:
        logger.exception("Company research failed")
        raise HTTPException(status_code=500, detail="Failed to generate research brief")
