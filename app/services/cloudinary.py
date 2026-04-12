import cloudinary
import cloudinary.uploader
from app.core.config import settings


def init_cloudinary():
    """Initialize Cloudinary with settings from config."""
    if settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET:
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True
        )
        return True
    return False


async def upload_file_to_cloudinary(file_content: bytes, filename: str, folder: str = "genius/resumes") -> dict:
    """Upload a file to Cloudinary and return the result."""
    import io
    
    if not init_cloudinary():
        raise Exception("Cloudinary is not configured. Please set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in .env")
    
    # Upload to Cloudinary
    result = cloudinary.uploader.upload(
        file_content,
        public_id=filename.rsplit('.', 1)[0],  # Remove extension from filename
        folder=folder,
        resource_type="auto",
        use_filename=True,
        unique_filename=True
    )
    
    return {
        "url": result.get("secure_url"),
        "public_id": result.get("public_id"),
        "format": result.get("format"),
        "size": result.get("bytes"),
        "resource_type": result.get("resource_type")
    }


async def delete_file_from_cloudinary(public_id: str) -> bool:
    """Delete a file from Cloudinary."""
    if not init_cloudinary():
        return False
    
    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception as e:
        print(f"Error deleting file from Cloudinary: {e}")
        return False
