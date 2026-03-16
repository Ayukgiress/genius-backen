from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.analysis import Analysis, AnalysisCreate, AnalysisUpdate, FocusArea
from app.crud.analysis import get_analysis, get_analysis_by_resume, create_analysis, update_analysis
from app.crud.resume import get_resume
from app.services.ai_analysis import resume_analysis_service, MAX_RESUME_LENGTH

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Rate limiter instance for AI endpoints
limiter = Limiter(key_func=get_remote_address)

@router.get("/", response_model=List[Analysis])
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

@router.post("/", response_model=Analysis, status_code=status.HTTP_201_CREATED)
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


@router.post("/resume/{resume_id}/analyze", response_model=Analysis, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def analyze_resume_with_ai(
    request: Request,
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Analyze a resume using AI (Gemini) and save the analysis results.
    Rate limited to 10 requests per minute per IP.
    """
    # Verify the resume belongs to the current user
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Check if resume has content to analyze
    if not resume.content:
        raise HTTPException(status_code=400, detail="Resume has no content to analyze")
    
    if len(resume.content) > MAX_RESUME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters"
        )
    
    # Check if analysis already exists for this resume
    existing = await get_analysis_by_resume(db, resume_id)
    if existing:
        # Update existing analysis
        try:
            ai_result = await resume_analysis_service.analyze_resume(resume.content)
            analysis_update = AnalysisUpdate(
                status="completed",
                result=ai_result,
                feedback=ai_result.get("summary", "")
            )
            return await update_analysis(db, existing, analysis_update)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(e)}")
    
    try:
        # Generate AI analysis
        ai_result = await resume_analysis_service.analyze_resume(resume.content)
        
        # Create new analysis with AI results
        analysis_in = AnalysisCreate(
            resume_id=resume_id,
            status="completed",
            result=ai_result,
            feedback=ai_result.get("summary", "")
        )
        return await create_analysis(db, analysis_in)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(e)}")


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
    """
    # Verify the resume belongs to the current user
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    # Check if resume has content
    if not resume.content:
        raise HTTPException(status_code=400, detail="Resume has no content")
    
    if len(resume.content) > MAX_RESUME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Resume content exceeds maximum length of {MAX_RESUME_LENGTH} characters"
        )
    
    try:
        suggestions = await resume_analysis_service.generate_suggestions(
            resume.content, 
            focus_area=focus_area
        )
        return suggestions
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate suggestions: {str(e)}")
