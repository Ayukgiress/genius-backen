from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Genius API"
    VERSION: str = "1.0.0"
    DATABASE_URL: Optional[str] = None
    REDIS_URL: Optional[str] = None
    S3_BUCKET: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    SECRET_KEY: str = "supersecretkey"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Email settings
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "noreply@genius.com"
    SMTP_FROM_NAME: str = "Genius API"
    SMTP_TLS: bool = True
    SMTP_TIMEOUT: int = 10

    # Alternative Email Providers
    RESEND_API_KEY: Optional[str] = None
    SENDGRID_API_KEY: Optional[str] = None
    BREVO_API_KEY: Optional[str] = None
    # EMAIL_PROVIDER: str = Field(default="gmail", validation_alias=AliasChoices("EMAIL_PROVIDER", "email_provider"))  # Options: gmail, resend, sendgrid, brevo
    EMAIL_PROVIDER: str = "gmail"

    # def __init__(self, **data):
    #     super().__init__(**data)
    #     # Auto-select email provider based on available API keys
    #     if self.RESEND_API_KEY and self.EMAIL_PROVIDER == "gmail":
    #         self.EMAIL_PROVIDER = "resend"
    #     elif self.SENDGRID_API_KEY and self.EMAIL_PROVIDER == "gmail":
    #         self.EMAIL_PROVIDER = "sendgrid"
    #     elif self.BREVO_API_KEY and self.EMAIL_PROVIDER == "gmail":
    #         self.EMAIL_PROVIDER = "brevo"
    
    # Frontend URL for verification links
    FRONTEND_URL: Optional[str] = None
    
    # Google OAuth settings
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None
    
    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    
    # Groq AI Configuration (free tier)
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Gemini AI Configuration
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # OpenRouter Configuration
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "openrouter/auto"

    # LLM per-user rate limiting (requests per minute)
    LLM_RATE_LIMIT_PER_MINUTE: int = 60

    # ElevenLabs TTS Configuration
    ELEVENLABS_API_KEY: Optional[str] = None

    # Stripe Configuration
    STRIPE_PUBLISHABLE_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("STRIPE_PUBLISHABLE_KEY", "PUBLISHABLE_KEY"))
    STRIPE_SECRET_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("STRIPE_SECRET_KEY", "SECRET_KEY_STRIPE"))
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    # Plan limits
    FREE_INTERVIEWS_PER_DAY: int = 2
    FREE_AI_ANALYSIS_PER_MONTH: int = 3
    FREE_JOB_MATCHING_PER_MONTH: int = 5
    PRO_INTERVIEWS_PER_DAY: int = 1000  # effectively unlimited
    PRO_AI_ANALYSIS_PER_MONTH: int = 10000
    PRO_JOB_MATCHING_PER_MONTH: int = 10000
    MAX_SESSION_LENGTH_MINUTES: int = 60  # max session length

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
