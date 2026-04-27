from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List
from app.models.letter import Letter
from app.schemas.letter import LetterCreate, LetterUpdate

async def get_letters(db: AsyncSession, user_id: int) -> List[Letter]:
    """Get all letters for a user."""
    result = await db.execute(
        select(Letter).where(Letter.user_id == user_id).order_by(Letter.created_at.desc())
    )
    return result.scalars().all()

async def get_letter(db: AsyncSession, letter_id: int, user_id: int) -> Letter:
    """Get a specific letter by ID for a user."""
    result = await db.execute(
        select(Letter).where(Letter.id == letter_id, Letter.user_id == user_id)
    )
    return result.scalar_one_or_none()

async def create_letter(db: AsyncSession, letter_in: LetterCreate, user_id: int) -> Letter:
    """Create a new letter."""
    letter = Letter(
        user_id=user_id,
        title=letter_in.title,
        recipient=letter_in.recipient,
        content=letter_in.content,
        letter_type=letter_in.letter_type
    )
    db.add(letter)
    await db.commit()
    await db.refresh(letter)
    return letter

async def update_letter(db: AsyncSession, letter: Letter, letter_in: LetterUpdate) -> Letter:
    """Update an existing letter."""
    for field, value in letter_in.dict(exclude_unset=True).items():
        setattr(letter, field, value)

    letter.updated_at = letter.updated_at  # This will be auto-updated by SQLAlchemy

    db.add(letter)
    await db.commit()
    await db.refresh(letter)
    return letter

async def delete_letter(db: AsyncSession, letter_id: int, user_id: int) -> bool:
    """Delete a letter."""
    result = await db.execute(
        delete(Letter).where(Letter.id == letter_id, Letter.user_id == user_id)
    )
    await db.commit()
    return result.rowcount > 0