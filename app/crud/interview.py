from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.interview import Interview, InterviewMessage
from app.schemas.interview import InterviewCreate, InterviewMessageCreate
from typing import List

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

async def get_interviews_by_job(db: AsyncSession, user_id: int, job_id: str):
    result = await db.execute(
        select(Interview).where(
            Interview.user_id == user_id,
            Interview.job_id == job_id
        )
    )
    return result.scalars().all()

async def create_interview(db: AsyncSession, interview: InterviewCreate, user_id: int):
    db_interview = Interview(
        user_id=user_id,
        job_id=interview.job_id,
        status=interview.status
    )
    db.add(db_interview)
    await db.commit()
    await db.refresh(db_interview)
    return db_interview

async def update_interview_status(db: AsyncSession, interview_id: int, status: str):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    db_interview = result.scalar_one_or_none()
    if db_interview:
        db_interview.status = status
        db.add(db_interview)
        await db.commit()
        await db.refresh(db_interview)
    return db_interview

async def delete_interview(db: AsyncSession, interview_id: int):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id)
    )
    db_interview = result.scalar_one_or_none()
    if db_interview:
        await db.delete(db_interview)
        await db.commit()
    return True

# Interview Message CRUD
async def create_interview_message(db: AsyncSession, interview_id: int, message: InterviewMessageCreate):
    db_message = InterviewMessage(
        interview_id=interview_id,
        role=message.role,
        content=message.content
    )
    db.add(db_message)
    await db.commit()
    await db.refresh(db_message)
    return db_message

async def get_interview_messages(db: AsyncSession, interview_id: int):
    result = await db.execute(
        select(InterviewMessage).where(InterviewMessage.interview_id == interview_id)
        .order_by(InterviewMessage.created_at)
    )
    return result.scalars().all()