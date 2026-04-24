from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, DateTime, JSON
from datetime import datetime, timezone
from app.db.session import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    bio: Mapped[str] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_token: Mapped[str] = mapped_column(String(255), nullable=True)
    verification_token_expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    
    google_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=True)
    oauth_provider: Mapped[str] = mapped_column(String(50), nullable=True)
    
    career_preferences: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Subscription fields
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=True)
    subscription_plan: Mapped[str] = mapped_column(String(50), default="free")  # free, pro
    subscription_status: Mapped[str] = mapped_column(String(50), default="inactive")  # inactive, active, canceled, past_due
    subscription_id: Mapped[str] = mapped_column(String(255), nullable=True)  # Stripe subscription ID

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
