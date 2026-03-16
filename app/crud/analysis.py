from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.analysis import Analysis
from app.schemas.analysis import AnalysisCreate, AnalysisUpdate

async def get_analysis(db: AsyncSession, analysis_id: int):
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    return result.scalar_one_or_none()

async def get_analysis_by_resume(db: AsyncSession, resume_id: int):
    result = await db.execute(select(Analysis).where(Analysis.resume_id == resume_id))
    return result.scalar_one_or_none()

async def create_analysis(db: AsyncSession, analysis: AnalysisCreate):
    db_analysis = Analysis(**analysis.model_dump())
    db.add(db_analysis)
    await db.commit()
    await db.refresh(db_analysis)
    return db_analysis

async def update_analysis(db: AsyncSession, db_analysis: Analysis, analysis: AnalysisUpdate):
    analysis_data = analysis.model_dump(exclude_unset=True)
    for key, value in analysis_data.items():
        setattr(db_analysis, key, value)
    db.add(db_analysis)
    await db.commit()
    await db.refresh(db_analysis)
    return db_analysis
