from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Genius API"
    VERSION: str = "1.0.0"
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/genius"
    REDIS_URL: str = "redis://localhost:6379/0"
    S3_BUCKET: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    SECRET_KEY: str = "your-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    class Config:
        env_file = ".env"

settings = Settings()
