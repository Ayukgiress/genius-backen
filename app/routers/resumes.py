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
import io
import logging
import zipfile
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

# A .docx file is just a ZIP archive; the body text lives in word/document.xml.
# We use the Python stdlib to avoid adding a new dependency.
WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/zip",  # some clients send the .docx as generic application/zip
}
NUL = "\x00"
DEL = "\x7f"


def _sanitize_text(value):
    """Strip characters that PostgreSQL UTF-8 will reject (notably NUL).

    Accepts str or bytes; always returns a str.
    """
    if value is None:
        return ""
    # Coerce bytes (e.g. accidentally-passed raw file bytes) to str first so
    # the per-char comparisons below operate on a uniform string type.
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return ""
    # Remove NUL bytes and other ASCII control chars except TAB / LF / CR
    out = []
    for ch in value:
        o = ord(ch)
        if ch == "\n" or ch == "\r" or ch == "\t":
            out.append(ch)
        elif o < 0x20 or o == 0x7f:
            # drop other ASCII control characters
            continue
        else:
            out.append(ch)
    return "".join(out)


def _extract_text_from_docx(file_content: bytes) -> str:
    """Extract plain paragraph text from a .docx file using only the stdlib."""
    try:
        with zipfile.ZipFile(io.BytesIO(file_content)) as zf:
            with zf.open("word/document.xml") as f:
                tree = ET.parse(f)
        root = tree.getroot()
        paragraphs = []
        for para in root.iter(f"{{{WORD_NS['w']}}}p"):
            texts = [t.text or "" for t in para.iter(f"{{{WORD_NS['w']}}}t")]
            line = "".join(texts).strip()
            if line:
                paragraphs.append(line)
        return "\n".join(paragraphs)
    except Exception as e:
        logger.error("docx extraction failed: %s", e)
        return ""


def _is_docx(file_content: bytes, content_type, filename) -> bool:
    if content_type in DOCX_MIME_TYPES:
        return True
    if filename and filename.lower().endswith(".docx"):
        return True
    # Magic bytes: a .docx starts with "PK\x03\x04" (ZIP local file header)
    return file_content[:4] == b"PK\x03\x04"


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
    # Read raw bytes once (needed for both Cloudinary upload and text extraction)
    file_content = await file.read()

    # Generate unique filename to avoid Cloudinary name collisions
    unique_filename = f"{current_user.id}_{uuid.uuid4().hex}_{file.filename}"

    # 1) Upload the original file to Cloudinary — we keep the raw bytes there,
    #    NEVER in PostgreSQL. The DB only stores the URL.
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

    # 2) Extract plain text for AI/search features. Always sanitize before
    #    writing to the DB — PostgreSQL UTF-8 rejects NUL bytes (\x00) and other
    #    control characters, which are common inside .docx ZIP containers.
    content = None
    try:
        if file.content_type == "application/pdf":
            # Extract text from PDF
            try:
                from pypdf import PdfReader
                pdf_reader = PdfReader(io.BytesIO(file_content))
                text_parts = []
                for page in pdf_reader.pages:
                    text_parts.append(page.extract_text() or "")
                content = "\n".join(text_parts)
            except Exception as e:
                logger.error("PDF text extraction failed: %s", e)

        elif _is_docx(file_content, file.content_type, file.filename):
            # Extract text from .docx via stdlib zipfile + XML
            content = _extract_text_from_docx(file_content)

        else:
            # Plain text / markdown / etc.
            try:
                content = file_content.decode("utf-8", errors="ignore")
            except Exception:
                content = None
    except Exception as e:
        logger.error("Unexpected error during text extraction: %s", e)
        content = None

    # Always sanitize: NUL bytes and other control chars kill PostgreSQL inserts
    if content:
        content = _sanitize_text(content).strip()

    if not content:
        # Don't store raw bytes — fall back to a small pointer to Cloudinary
        content = f"[No text extracted. Full file: {cloudinary_result['url']}]"

    resume_data = {
        "file_name": file.filename,
        "file_path": cloudinary_result["url"],  # Store Cloudinary URL, not bytes
        "content": content,
        "user_id": current_user.id
    }
    resume = ResumeCreate(**resume_data)
    return await create_resume_db(db, resume)
