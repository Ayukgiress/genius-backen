from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.resume import Resume, ResumeCreate, ResumeUpdate
from app.crud.resume import get_resume, get_resumes_by_user, create_resume as create_resume_db, update_resume, delete_resume
from app.services.cloudinary import upload_file_to_cloudinary
from app.services.interview import interview_service
from app.services.job_scraper import job_service
from app.models.resume import Resume as ResumeModel
import uuid
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

@router.get("", response_model=List[Resume])
async def list_resumes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_resumes_by_user(db, user_id=current_user.id)


@router.post("", response_model=Resume, status_code=status.HTTP_201_CREATED)
async def create_resume(
    resume_in: ResumeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resume_data = resume_in.model_dump()
    resume = ResumeCreate(**resume_data)
    return await create_resume_db(db, current_user.id, resume)


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
    file_content = await file.read()
    unique_filename = f"{current_user.id}_{uuid.uuid4().hex}_{file.filename}"
    try:
        cloudinary_result = await upload_file_to_cloudinary(
            file_content,
            unique_filename,
            folder=f"genius/user_{current_user.id}"
        )
        if not cloudinary_result or not cloudinary_result.get("url"):
            raise Exception("Cloudinary upload failed to return a URL")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload file to cloud storage: {str(e)}"
        )
    
    content = None
    if file.content_type == "application/pdf":
        try:
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                text_parts = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                content = "\n\n".join(text_parts).strip()
            if not content or len(content) < 50:
                content += f"\n[Full file at Cloudinary: {cloudinary_result['url']}]"
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            try:
                import io
                from pypdf import PdfReader
                pdf_reader = PdfReader(io.BytesIO(file_content))
                text_parts = []
                for page in pdf_reader.pages:
                    text_parts.append(page.extract_text() or "")
                content = "\n".join(text_parts).strip()
            except Exception as e2:
                logger.error(f"pypdf fallback failed: {e2}")
                content = f"[PDF extraction failed. Full file: {cloudinary_result['url']}]"
    else:
        try:
            content = file_content.decode("utf-8", errors="ignore").strip()
        except:
            content = None

    if not content or len(content) < 10:
        content = f"[No content extracted. Full file: {cloudinary_result['url']}]"
    
    resume_data = {
        "file_name": file.filename,
        "file_path": cloudinary_result["url"], 
        "content": content,
    }
    resume = ResumeCreate(**resume_data)
    return await create_resume_db(db, current_user.id, resume)


@router.post("/{resume_id}/tailor")
async def tailor_resume(
    resume_id: int,
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    resume = await get_resume(db, resume_id)
    if not resume or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    
    job = await job_service.match_with_resume(job_id, resume.content or "")
    job_dict = {
        "title": getattr(job, "title", "Unknown"),
        "company": getattr(job, "company", "Unknown"),
        "description": getattr(job, "description", "") or "",
        "requirements": getattr(job, "requirements", "") or "",
    } if job else {"title": "Unknown", "company": "Unknown", "description": "", "requirements": ""}
    
    if not interview_service.groq_client:
        raise HTTPException(status_code=503, detail="AI service not configured")
    
    prompt = f"""You are an expert resume writer. Tailor this resume for the job.

Job: {job_dict}
Resume:
{resume.content}

Return JSON with:
{{
  "tailored_resume": "full tailored resume content",
  "keywords_matched": ["keyword1"],
  "keywords_missing": ["keyword2"],
  "ats_keyword_diff": {{
    "added": ["..."],
    "removed": ["..."],
    "suggestions": ["..."]
  }},
  "improvements": ["..."]
}}"""
    
    try:
        response = await interview_service.groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a resume tailoring expert. Output only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        logger.exception("Resume tailoring failed")
        raise HTTPException(status_code=500, detail="Failed to tailor resume")
