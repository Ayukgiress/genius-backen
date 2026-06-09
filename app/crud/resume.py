from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.resume import Resume
from app.schemas.resume import ResumeCreate, ResumeUpdate
from app.crud.analysis import delete_analyses_by_resume
from typing import List

import logging

logger = logging.getLogger(__name__)


def _sanitize_text(value):
    """Remove characters that PostgreSQL UTF-8 will reject (notably NUL \\x00).

    This is a last-line-of-defense guard so that any code path creating a
    Resume cannot accidentally push binary file bytes into the `content`
    VARCHAR/Text column.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        # Coerce bytes/other to string via lossy decode so we never raise here
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            try:
                value = str(value)
            except Exception:
                return None
    return "".join(
        ch for ch in value
        if ch == "\n" or ch == "\r" or ch == "\t" or (ch >= " " and ch != "\x7f")
    )


async def get_resume(db: AsyncSession, resume_id: int):
    result = await db.execute(select(Resume).where(Resume.id == resume_id))
    return result.scalar_one_or_none()

async def get_resumes_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(select(Resume).where(Resume.user_id == user_id))
    return result.scalars().all()

async def create_resume(db: AsyncSession, resume: ResumeCreate):
    data = resume.model_dump()
    # Always sanitize the textual content. NUL bytes (and other ASCII control
    # characters) make PostgreSQL reject the INSERT with a UTF-8 encoding
    # error, which is exactly the bug we are guarding against.
    data["content"] = _sanitize_text(data.get("content"))
    db_resume = Resume(**data)
    db.add(db_resume)
    await db.commit()
    await db.refresh(db_resume)
    return db_resume

async def update_resume(db: AsyncSession, db_resume: Resume, resume: ResumeUpdate):
    resume_data = resume.model_dump(exclude_unset=True)
    if "content" in resume_data:
        resume_data["content"] = _sanitize_text(resume_data["content"])
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
