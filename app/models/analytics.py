from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, ForeignKey, Integer, JSON, Index
from datetime import datetime
from app.db.session import Base

class Analytics(Base):
    __tablename__ = "analytics"
    __table_args__ = (
        Index("ix_analytics_interview_id", "interview_id"),
        Index("ix_analytics_user_event_created_at", "user_id", "event_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False) # resume_upload, analysis_complete, card_moved
    interview_id: Mapped[int | None] = mapped_column(ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
