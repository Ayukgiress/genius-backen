from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.analysis import Analysis, AnalysisCreate, AnalysisUpdate
from app.crud.analysis import get_analysis, get_analysis_by_resume, create_analysis, update_analysis
from app.crud.resume import get_resume

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.get("/", response_model=List[Analysis])
async def list_analyses(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Get all analyses for resumes owned by the current user
    from sqlalchemy import select
    from app.models.analysis import Analysis
    from app.models.resume import Resume
    result = await db.execute(
        select(Analysis)
        .join(Resume, Analysis.resume_id == Resume.id)
        .where(Resume.user_id == current_user.id)
    )
    return result.scalars().all()

@router.post("/", response_model=Analysis, status_code=status.HTTP_201_CREATED)
async def create_resume_analysis(
    analysis_in: AnalysisCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify the resume belongs to the current user
    resume = await get_resume(db, analysis_in.resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Check if analysis already exists for this resume
    existing = await get_analysis_by_resume(db, analysis_in.resume_id)
    if existing:
        raise HTTPException(status_code=400, detail="Analysis already exists for this resume")
    
    return await create_analysis(db, analysis_in)

@router.get("/{analysis_id}", response_model=Analysis)
async def get_resume_analysis(
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    analysis = await get_analysis(db, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    # Verify the resume belongs to the current user
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
    
    # Verify the resume belongs to the current user
    resume = await get_resume(db, analysis.resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    return await update_analysis(db, analysis, analysis_in)

@router.get("/resume/{resume_id}", response_model=Analysis)
async def get_analysis_by_resume_id(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify the resume belongs to the current user
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    analysis = await get_analysis_by_resume(db, resume_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found for this resume")
    
    return analysis
