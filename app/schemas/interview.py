from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, List, Dict, Any, Union, Literal
from enum import Enum


class InterviewSessionState(str, Enum):
    STARTED = "started"
    ACTIVE = "active"
    LISTENING = "listening"
    AI_SPEAKING = "ai_speaking"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_SPEECH = "no_speech"

class InterviewMessageBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    role: Literal["system", "assistant", "user"]
    content: str = Field(min_length=1, max_length=20_000)

class InterviewMessageCreate(InterviewMessageBase):
    generate_audio: bool = False
    avatar_style: Optional[str] = Field(default=None, max_length=100)
    avatar_id: Optional[str] = Field(default=None, max_length=100)
    video_url: Optional[str] = Field(default=None, max_length=2_048)
    video_status: Optional[str] = Field(default=None, max_length=50)
    response_mode: Optional[str] = Field(default=None, max_length=50)
    speaking_state: Optional[str] = Field(default=None, max_length=30)
    persona: Optional[Union[str, Dict[str, Any]]] = None
    playback_metadata: Optional[Dict[str, Any]] = None

class InterviewMessageResponse(InterviewMessageBase):
    id: int
    interview_id: int
    # no_speech and structured error responses legitimately have no text.
    content: str = Field(default="", max_length=20_000)
    created_at: Optional[datetime] = None
    status: str = "success"  # success, no_speech, error, analyzing, responding
    response_status: Optional[str] = None
    session_state: Optional[InterviewSessionState] = None
    error: Optional[str] = None
    error_type: Optional[str] = None  # format, decode, transcription, or ai_generation
    audio_content: Optional[str] = None  # Base64 encoded audio (legacy)
    transcript: Optional[str] = None  # Visual/STT transcript
    visual_data: Optional[Dict[str, Any]] = None
    visual_analysis: Optional[Dict[str, Any]] = None  # Face/posture data
    audio_data: Optional[str] = None  # Base64 encoded AI audio response
    ai_audio_data: Optional[str] = None  # Canonical name for generated audio
    ai_avatar_video_url: Optional[str] = None
    avatar_type: Optional[str] = None
    avatar_style: Optional[str] = None
    avatar_id: Optional[str] = None
    video_url: Optional[str] = None
    response_mode: Optional[str] = None
    speaking_state: Optional[str] = None
    persona: Optional[Union[str, Dict[str, Any]]] = None
    video_status: Optional[str] = None
    playback_metadata: Optional[Dict[str, Any]] = None
    # Legacy WebSocket keys retained during the frontend contract migration.
    ai_text: Optional[str] = None
    ai_audio_base64: Optional[str] = None
    ai_message_id: Optional[int] = None

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True  # For dict

class InterviewBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    job_id: str = Field(min_length=1, max_length=50)
    status: InterviewSessionState = InterviewSessionState.STARTED
    persona_config: Optional[Dict[str, Any]] = None
    session_metadata: Optional[Dict[str, Any]] = None
    interviewer_type: Optional[str] = None
    camera_settings: Optional[Dict[str, Any]] = None
    audio_settings: Optional[Dict[str, Any]] = None

class InterviewCreate(InterviewBase):
    resume_id: Optional[int] = Field(default=None, gt=0)
    # Accept legacy client-supplied values; persistence normalizes them to
    # the explicit lifecycle states and always starts a new session at started.
    status: Literal[
        "started", "active", "listening", "ai_speaking", "waiting_for_user",
        "completed", "failed", "no_speech", "ongoing",
    ] = InterviewSessionState.STARTED.value

class InterviewResponse(InterviewBase):
    id: int
    user_id: int
    session_state: InterviewSessionState
    created_at: datetime
    updated_at: datetime
    messages: List[InterviewMessageResponse] = []
    initial_message_status: Optional[str] = None
    initial_message_error: Optional[str] = None
    session_created: Optional[bool] = None

    class Config:
        from_attributes = True

class InterviewStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: Optional[int] = Field(default=None, gt=0)

class InterviewAudioMessageCreate(BaseModel):
    base64_audio: str = Field(min_length=1, max_length=35_000_000)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class InterviewWebSocketAuth(BaseModel):
    type: Literal["auth"]
    token: str = Field(min_length=1, max_length=8_192)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class InterviewWebSocketAudioMessage(BaseModel):
    type: Literal["audio_chunk"]
    data: str = Field(min_length=1, max_length=35_000_000)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class InterviewWebSocketVideoFrame(BaseModel):
    type: Literal["video_frame"]
    data: str = Field(min_length=1, max_length=8_000_000)
    timestamp: int = Field(default=0, ge=0)
    generate_ai: bool = True

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
