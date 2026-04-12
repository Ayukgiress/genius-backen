from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.job import JobResponse, JobMatchResponse, JobSearchParams
from app.schemas.kanban import KanbanCardCreate
from app.services.job_scraper import job_service
from app.crud import kanban as crud_kanban
from app.crud import user as crud_user
from app.routers.deps import get_db, get_current_user
from app.models.user import User
from datetime import datetime

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/search")
async def search_jobs(
    query: Optional[str] = None,
    location: Optional[str] = None,
    remote: bool = False,
    job_type: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
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
    """Get AI-matched job recommendations based on user's resume and career preferences."""
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
    return recommendations


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
    
    return matched_job


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
    )
    
    card = await crud_kanban.create_card(db, card_data)
    return card


@router.get("/{job_id}")
async def get_job(job_id: str):
    """Get a specific job by ID."""
    all_jobs = await job_service.scraper.scrape_all_jobs()
    all_jobs.extend(job_service._sample_jobs)
    job = next((j for j in all_jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job