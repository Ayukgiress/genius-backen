from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.letter import Letter, LetterCreate, LetterUpdate, LetterGenerateRequest
from app.crud.letter import get_letters, get_letter, create_letter, update_letter, delete_letter
from app.services.ai_letter import letter_generation_service
from app.crud.resume import get_resume

router = APIRouter(prefix="/letters", tags=["letters"])

@router.get("", response_model=List[Letter])
async def list_letters(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all letters for the current user."""
    return await get_letters(db, current_user.id)

@router.post("", response_model=Letter, status_code=status.HTTP_201_CREATED)
async def create_user_letter(
    letter_in: LetterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new letter."""
    return await create_letter(db, letter_in, current_user.id)

@router.get("/{letter_id}", response_model=Letter)
async def get_user_letter(
    letter_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific letter."""
    letter = await get_letter(db, letter_id, current_user.id)
    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")
    return letter

@router.patch("/{letter_id}", response_model=Letter)
async def update_user_letter(
    letter_id: int,
    letter_in: LetterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a letter."""
    letter = await get_letter(db, letter_id, current_user.id)
    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")

    return await update_letter(db, letter, letter_in)

@router.delete("/{letter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_letter(
    letter_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a letter."""
    success = await delete_letter(db, letter_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Letter not found")

@router.post("/generate", response_model=Letter, status_code=status.HTTP_201_CREATED)
async def generate_custom_letter(
    request: LetterGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate a custom letter using AI."""
    # Check subscription for free users
    if current_user.subscription_plan == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Custom letter generation is available for Pro users only. Please upgrade your subscription."
        )

    resume_content = ""
    if request.resume_id:
        resume = await get_resume(db, request.resume_id)
        if resume and resume.user_id == current_user.id:
            resume_content = resume.content or ""

    try:
        # Generate letter content using AI
        letter_content = await letter_generation_service.generate_letter(
            job_title=request.job_title,
            company_name=request.company_name,
            recipient_name=request.recipient_name,
            resume_content=resume_content,
            letter_type=request.letter_type,
            custom_instructions=request.custom_instructions
        )

        # Create the letter in database
        letter_in = LetterCreate(
            title=f"{request.letter_type.title().replace('_', ' ')} - {request.company_name}",
            recipient=request.recipient_name or f"Hiring Manager at {request.company_name}",
            content=letter_content,
            letter_type=request.letter_type
        )

        return await create_letter(db, letter_in, current_user.id)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate letter: {str(e)}")