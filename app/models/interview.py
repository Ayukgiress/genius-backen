from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.db.session import Base

class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = (
        Index("ix_interviews_user_updated_at", "user_id", "updated_at"),
        Index("ix_interviews_user_job_status", "user_id", "job_id", "status"),
        Index(
            "uq_interviews_user_job_open",
            "user_id",
            "job_id",
            unique=True,
            postgresql_where=text("status NOT IN ('completed', 'failed')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_id: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="started")
    persona_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    session_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    interviewer_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    camera_settings: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    audio_settings: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    messages: Mapped[List["InterviewMessage"]] = relationship("InterviewMessage", back_populates="interview", cascade="all, delete-orphan")

    @property
    def session_state(self) -> str:
        """Explicit lifecycle alias for clients while retaining status."""
        return "waiting_for_user" if self.status == "ongoing" else self.status

class InterviewMessage(Base):
    __tablename__ = "interview_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # system, assistant, user
    content: Mapped[str] = mapped_column(Text, nullable=False)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # STT/visual transcript
    visual_data: Mapped[Optional[JSONB]] = mapped_column(JSONB, nullable=True)  # Face/posture JSON
    audio_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Base64 encoded audio response
    ai_avatar_video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    avatar_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    avatar_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    avatar_style: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    response_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    speaking_state: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    persona: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    video_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    playback_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    interview: Mapped["Interview"] = relationship("Interview", back_populates="messages")

    # Compatibility aliases exposed by the API while clients migrate to the
    # canonical media field names.
    @property
    def audio_content(self) -> Optional[str]:
        return self.audio_data

    @property
    def visual_analysis(self) -> Optional[dict]:
        return self.visual_data

    @property
    def ai_text(self) -> Optional[str]:
        return self.content if self.role == "assistant" else None

    @property
    def ai_audio_base64(self) -> Optional[str]:
        return self.audio_data if self.role == "assistant" else None

    @property
    def ai_audio_data(self) -> Optional[str]:
        return self.audio_data if self.role == "assistant" else None

    @property
    def response_status(self) -> str:
        return "success"
