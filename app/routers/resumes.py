from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.resume import Resume, ResumeCreate, ResumeUpdate
from app.crud.resume import get_resume, get_resumes_by_user, create_resume, update_resume, delete_resume

router = APIRouter(prefix="/resumes", tags=["resumes"])

@router.get("/", response_model=List[Resume])
async def list_resumes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_resumes_by_user(db, user_id=current_user.id)

@router.post("/", response_model=Resume, status_code=status.HTTP_201_CREATED)
async def create_resume(
    resume_in: ResumeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resume_data = resume_in.model_dump()
    resume_data["user_id"] = current_user.id
    resume = ResumeCreate(**resume_data)
    return await create_resume(db, resume)

@router.get("/{resume_id}", response_model=Resume)
async def get_resume_by_id(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume

@router.patch("/{resume_id}", response_model=Resume)
async def update_resume_by_id(
    resume_id: int,
    resume_in: ResumeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    return await update_resume(db, resume, resume_in)

@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume_by_id(
    resume_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    await delete_resume(db, resume)
    return None

@router.post("/upload", response_model=Resume, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # In a real application, you would save the file to disk/cloud storage
    # and extract the content using a PDF parser or other method
    file_path = f"uploads/{current_user.id}/{file.filename}"
    
    # Read file content (in real app, save to storage)
    content = await file.read()
    
    resume_data = {
        "file_name": file.filename,
        "file_path": file_path,
        "content": content.decode("utf-8", errors="ignore") if content else None,
        "user_id": current_user.id
    }
    resume = ResumeCreate(**resume_data)
    return await create_resume(db, resume)
