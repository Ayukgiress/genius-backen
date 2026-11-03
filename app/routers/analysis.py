from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.db.session import get_db, SessionLocal
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.analysis import Analysis, AnalysisCreate, AnalysisUpdate, FocusArea
from app.crud.analysis import get_analysis, get_analysis_by_resume, create_analysis, update_analysis
from app.crud.resume import get_resume
from app.crud.user_usage import get_current_month_usage, increment_usage
from app.services.ai_analysis import resume_analysis_service, MAX_RESUME_LENGTH
from app.services.events import track_event
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Rate limiter instance for AI endpoints (per-IP, in addition to per-user LLM limits)
limiter = Limiter(key_func=get_remote_address)


@router.get("", response_model=List[Analysis])
async def list_analyses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from sqlalchemy import select
    from app.models.analysis import Analysis
    from app.models.resume import Resume
    result = await db.execute(
        select(Analysis)
        .join(Resume, Analysis.resume_id == Resume.id)
        .where(Resume.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("", response_model=Analysis, status_code=status.HTTP_201_CREATED)
async def create_resume_analysis(
    analysis_in: AnalysisCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resume = await get_resume(db, analysis_in.resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")

    existing = await get_analysis_by_resume(db, analysis_in.resume_id)
    if existing:
        raise HTTPException(status_code=400, detail="Analysis already exists for this resume")

    return await create_analysis(db, analysis_in)


@router.get("/resume/{resume_id}", response_model=Analysis)
async def get_analysis_by_resume_id(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")

    analysis = await get_analysis_by_resume(db, resume_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found for this resume")

    return analysis


@router.get("/{analysis_id}", response_model=Analysis)
async def get_resume_analysis(
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    analysis = await get_analysis(db, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    resume = await get_resume(db, analysis.resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return analysis


@router.patch("/{analysis_id}", response_model=Analysis)
async def update_resume_analysis(
    analysis_id: int,
    analysis_in: AnalysisUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    analysis = await get_analysis(db, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    resume = await get_resume(db, analysis.resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return await update_analysis(db, analysis, analysis_in)


async def _run_resume_analysis(
    analysis_id: int,
    resume_id: int,
    resume_content: str,
    user_id: int,
):
    """Background task: run AI analysis and update the analysis record."""
    async with SessionLocal() as db:
        try:
            ai_result = await resume_analysis_service.analyze_resume(
                resume_content, user_id=user_id
            )
            analysis = await get_analysis(db, analysis_id)
            if analysis:
                await update_analysis(
                    db,
                    analysis,
                    AnalysisUpdate(
                        status="completed",
                        result=ai_result,
                        feedback=ai_result.get("summary", ""),
                    ),
                )
            await track_event(
                db,
                user_id,
                "analysis_done",
                {
                    "resume_id": resume_id,
                    "analysis_id": analysis_id,
                    "score": ai_result.get("overall_score"),
                },
            )
            await increment_usage(db, user_id, "ai_analysis")
            logger.info(
                "Background analysis completed: analysis_id=%s resume_id=%s user_id=%s",
                analysis_id, resume_id, user_id,
            )
        except Exception as e:
            logger.exception(
                "Background analysis failed: analysis_id=%s resume_id=%s user_id=%s",
                analysis_id, resume_id, user_id,
            )
            try:
                async with SessionLocal() as fix_db:
                    analysis = await get_analysis(fix_db, analysis_id)
                    if analysis:
                        await update_analysis(
                            fix_db,
                            analysis,
                            AnalysisUpdate(status="failed", feedback=str(e)[:1000]),
                        )
            except Exception:
                logger.exception("Failed to mark analysis %s as failed", analysis_id)


@router.post("/resume/{resume_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/minute")
async def analyze_resume_with_ai(
    request: Request,
    background_tasks: BackgroundTasks,
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Queue a resume AI analysis in a background task so the API never blocks
    on slow provider calls. Returns 202 immediately; poll GET /analysis/{id}
    for the completed result.
    Rate limited to 10 requests per minute per IP.
    Limited to 3 analyses per month for free users.
    """
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")

    from app.core.config import settings
    if current_user.subscription_plan == "free":
        current_usage = await get_current_month_usage(db, current_user.id, "ai_analysis")
        if current_usage >= settings.FREE_AI_ANALYSIS_PER_MONTH:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Free users are limited to {settings.FREE_AI_ANALYSIS_PER_MONTH} AI resume analyses per month. Please upgrade to Pro for unlimited access.",
            )

    if not resume.content or not resume.content.strip():
        raise HTTPException(status_code=400, detail="Resume has no content to analyze")

    if resume.content.startswith("["):
        raise HTTPException(status_code=400, detail="Resume content could not be extracted. Please upload a text-based PDF or plain text resume.")

    if len(resume.content) > MAX_RESUME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters",
        )

    existing = await get_analysis_by_resume(db, resume_id)
    if existing:
        analysis = await update_analysis(
            db,
            existing,
            AnalysisUpdate(status="pending", result=None, feedback=None),
        )
    else:
        analysis_in = AnalysisCreate(
            resume_id=resume_id,
            status="pending",
        )
        analysis = await create_analysis(db, analysis_in)

    background_tasks.add_task(
        _run_resume_analysis,
        analysis.id,
        resume_id,
        resume.content,
        current_user.id,
    )

    return {
        "analysis_id": analysis.id,
        "status": "pending",
        "message": "Resume analysis queued. Poll GET /analysis/{analysis_id} for the result.",
    }


@router.post("/resume/{resume_id}/suggestions")
@limiter.limit("10/minute")
async def get_resume_suggestions(
    request: Request,
    resume_id: int,
    focus_area: Optional[FocusArea] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get AI-generated suggestions for improving a resume.
    Optionally specify a focus area (summary, experience, skills, education).
    Rate limited to 10 requests per minute per IP.
    Limited to 3 analyses per month for free users.
    """
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")

    from app.core.config import settings
    if current_user.subscription_plan == "free":
        current_usage = await get_current_month_usage(db, current_user.id, "ai_analysis")
        if current_usage >= settings.FREE_AI_ANALYSIS_PER_MONTH:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Free users are limited to {settings.FREE_AI_ANALYSIS_PER_MONTH} AI resume analyses per month. Please upgrade to Pro for unlimited access.",
            )

    if not resume.content or not resume.content.strip():
        raise HTTPException(status_code=400, detail="Resume has no content")

    if len(resume.content) > MAX_RESUME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters",
        )

    try:
        suggestions = await resume_analysis_service.get_suggestions(
            resume.content,
            focus_area=focus_area,
            user_id=current_user.id,
        )

        if current_user.subscription_plan == "free":
            await increment_usage(db, current_user.id, "ai_analysis")

        return suggestions
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate suggestions: {str(e)}")
