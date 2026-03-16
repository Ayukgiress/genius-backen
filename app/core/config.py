from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Genius API"
    VERSION: str = "1.0.0"
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/genius"
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
    FRONTEND_URL: str = "http://localhost:3000"
    
    # Google OAuth settings
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://127.0.0.1:8000/auth/google/callback"

    class Config:
        env_file = ".env"

settings = Settings()
