from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, ForeignKey, Integer, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
from app.db.session import Base


class CareerProfile(Base):
    __tablename__ = "career_profiles"
    __table_args__ = (
        # One profile per user
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False, unique=True
    )
    target_roles: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    skills: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    locations: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    remote_preference: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    salary_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    experience_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    weekly_goals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
