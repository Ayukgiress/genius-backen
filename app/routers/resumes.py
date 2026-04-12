from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.resume import Resume, ResumeCreate, ResumeUpdate
from app.crud.resume import get_resume, get_resumes_by_user, create_resume as create_resume_db, update_resume, delete_resume
from app.services.cloudinary import upload_file_to_cloudinary
import uuid

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
    return await create_resume_db(db, resume)

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
    # Upload file to Cloudinary
    file_content = await file.read()
    
    # Generate unique filename to avoid conflicts
    unique_filename = f"{current_user.id}_{uuid.uuid4().hex}_{file.filename}"
    
    try:
        cloudinary_result = await upload_file_to_cloudinary(
            file_content, 
            unique_filename,
            folder=f"genius/user_{current_user.id}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload file to cloud storage: {str(e)}"
        )
    
    # Extract text content from file
    content = None
    if file.content_type == "application/pdf":
        # Extract text from PDF
        try:
            import io
            from pypdf import PdfReader
            pdf_reader = PdfReader(io.BytesIO(file_content))
            text_parts = []
            for page in pdf_reader.pages:
                text_parts.append(page.extract_text())
            content = "\n".join(text_parts)
            if not content or content.strip() == "":
                content = f"[PDF file uploaded to Cloudinary: {cloudinary_result['url']}]"
        except Exception as e:
            print(f"Error extracting PDF text: {e}")
            content = f"[PDF file uploaded to Cloudinary: {cloudinary_result['url']}]"
    else:
        # For text files, try to extract content
        try:
            content = file_content.decode("utf-8", errors="ignore")
        except:
            content = None
    
    resume_data = {
        "file_name": file.filename,
        "file_path": cloudinary_result["url"],  # Store Cloudinary URL
        "content": content,
        "user_id": current_user.id
    }
    resume = ResumeCreate(**resume_data)
    return await create_resume_db(db, resume)
