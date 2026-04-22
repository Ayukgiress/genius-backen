from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Genius API"
    VERSION: str = "1.0.0"
    DATABASE_URL: str = "postgresql://genius_jjum_user:sHKb4XNigYxgHAIcvjo6pNIIUh1nvyhj@dpg-d7ivqcgsfn5c738n50hg-a.oregon-postgres.render.com/genius_jjum"
    REDIS_URL: str = "redis://localhost:6379/0"
    S3_BUCKET: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    SECRET_KEY: str = "your-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Email settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "noreply@genius.com"
    SMTP_FROM_NAME: str = "Genius API"
    
    # Frontend URL for verification links
    FRONTEND_URL: str = "https://genuis-pi.vercel.app"
    
    # Google OAuth settings
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "https://genuis-pi.vercel.app/auth/google/callback"
    
    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    
    # Groq AI Configuration (free tier)
    GROQ_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"

settings = Settings()
