from datetime import datetime
from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.analytics import Analytics, AnalyticsCreate
from app.schemas.interview import InterviewTrendsResponse
from app.crud.analytics import (
    create_analytics_event,
    get_analytics_by_user,
    count_analytics_by_type,
)
from app.models.interview import Interview, InterviewReport
from app.models.analytics import Analytics as AnalyticsModel

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/interview-trends", response_model=InterviewTrendsResponse)
async def get_interview_trends(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Get all interviews for user
    interviews_result = await db.execute(select(Interview).where(Interview.user_id == current_user.id))
    interviews = interviews_result.scalars().all()
    
    reports_result = await db.execute(select(InterviewReport).where(InterviewReport.user_id == current_user.id))
    reports = reports_result.scalars().all()
    
    total_interviews = len(interviews)
    completed_interviews = len([i for i in interviews if i.status == "completed"])
    
    scores = []
    rubric_scores = {"relevance": [], "star_structure": [], "specificity": [], "communication": []}
    all_strengths = []
    all_gaps = []
    score_trend = []
    
    for report in reports:
        if report.overall_score is not None:
            scores.append(report.overall_score)
            score_trend.append({
                "interview_id": report.interview_id,
                "score": report.overall_score,
                "date": report.created_at.isoformat() if report.created_at else None
            })
        if report.rubric and isinstance(report.rubric, dict):
            for key in rubric_scores:
                if report.rubric.get(key) is not None:
                    rubric_scores[key].append(report.rubric[key])
        if report.strengths:
            all_strengths.extend(report.strengths)
        if report.gaps:
            all_gaps.extend(report.gaps)
    
    # Count frequencies
    from collections import Counter
    strength_counts = Counter(all_strengths)
    gap_counts = Counter(all_gaps)
    common_strengths = [s for s, _ in strength_counts.most_common(5)]
    common_gaps = [g for g, _ in gap_counts.most_common(5)]
    
    average_score = sum(scores) / len(scores) if scores else None
    
    rubric_averages = None
    if any(rubric_scores.values()):
        rubric_averages = {
            "relevance": sum(rubric_scores["relevance"]) / len(rubric_scores["relevance"]) if rubric_scores["relevance"] else None,
            "star_structure": sum(rubric_scores["star_structure"]) / len(rubric_scores["star_structure"]) if rubric_scores["star_structure"] else None,
            "specificity": sum(rubric_scores["specificity"]) / len(rubric_scores["specificity"]) if rubric_scores["specificity"] else None,
            "communication": sum(rubric_scores["communication"]) / len(rubric_scores["communication"]) if rubric_scores["communication"] else None,
        }
    
    return InterviewTrendsResponse(
        total_interviews=total_interviews,
        completed_interviews=completed_interviews,
        average_score=average_score,
        score_trend=score_trend,
        common_strengths=common_strengths,
        common_gaps=common_gaps,
        rubric_averages=rubric_averages,
        interviews_with_reports=len(reports),
    )

@router.get("", response_model=List[Analytics])
async def list_analytics(
    event_type: str | None = None,
    interview_id: int | None = None,
    job_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_analytics_by_user(
        db,
        user_id=current_user.id,
        event_type=event_type,
        interview_id=interview_id,
        job_id=job_id,
        since=since,
        until=until,
        offset=offset,
        limit=limit,
    )

@router.post("", response_model=Analytics, status_code=status.HTTP_201_CREATED)
async def create_analytics(
    event_in: AnalyticsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    event = event_in.model_copy(update={"user_id": current_user.id})
    return await create_analytics_event(db, event)

@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    event_types = await count_analytics_by_type(db, user_id=current_user.id)
    return {
        "total_events": sum(event_types.values()),
        "event_types": event_types
    }


@router.get("/funnel")
async def get_funnel_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.crud import kanban as kanban_crud
    from app.crud import resume as resume_crud
    from collections import defaultdict
    
    boards = await kanban_crud.get_boards_by_user(db, current_user.id)
    all_cards = []
    for board in boards:
        cards = await kanban_crud.get_cards_by_board(db, board.id)
        all_cards.extend(cards)
    
    funnel = {
        "applied": 0,
        "interview": 0,
        "offer": 0,
        "rejected": 0
    }
    for card in all_cards:
        if card.status in funnel:
            funnel[card.status] += 1
    
    # Resume version conversion
    resumes = await resume_crud.get_resumes_by_user(db, current_user.id)
    resume_conversions = []
    for resume in resumes:
        resume_conversions.append({
            "resume_id": resume.id,
            "file_name": resume.file_name,
            "score": resume.score,
            "conversions": 0  # simplified
        })
    
    return {
        "funnel": funnel,
        "conversion_rates": {
            "applied_to_interview": round(funnel["interview"] / funnel["applied"] * 100, 2) if funnel["applied"] > 0 else 0,
            "interview_to_offer": round(funnel["offer"] / funnel["interview"] * 100, 2) if funnel["interview"] > 0 else 0,
        },
        "resume_conversions": resume_conversions
    }
