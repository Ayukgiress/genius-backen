from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.resume import Resume
from app.schemas.resume import ResumeCreate, ResumeUpdate
from app.crud.analysis import delete_analyses_by_resume
from typing import List

async def get_resume(db: AsyncSession, resume_id: int):
    result = await db.execute(select(Resume).where(Resume.id == resume_id))
    return result.scalar_one_or_none()

async def get_resumes_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(select(Resume).where(Resume.user_id == user_id))
    return result.scalars().all()

async def create_resume(db: AsyncSession, resume: ResumeCreate):
    db_resume = Resume(**resume.model_dump())
    db.add(db_resume)
    await db.commit()
    await db.refresh(db_resume)
    return db_resume

async def update_resume(db: AsyncSession, db_resume: Resume, resume: ResumeUpdate):
    resume_data = resume.model_dump(exclude_unset=True)
    for key, value in resume_data.items():
        setattr(db_resume, key, value)
    db.add(db_resume)
    await db.commit()
    await db.refresh(db_resume)
    return db_resume

async def delete_resume(db: AsyncSession, db_resume: Resume):
    # Delete related analyses first to avoid foreign key constraint
    await delete_analyses_by_resume(db, db_resume.id)
    await db.delete(db_resume)
    await db.commit()
    return True
