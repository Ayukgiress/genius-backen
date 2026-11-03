from __future__ import annotations

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
    config: Optional["InterviewConfig"] = None
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


# ---------------------------------------------------------------------------
# Interview configuration
# ---------------------------------------------------------------------------

class InterviewType(str, Enum):
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    MIXED = "mixed"
    CASE = "case"


class InterviewDifficulty(str, Enum):
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"


class InterviewConfig(BaseModel):
    """Configuration for an interview session.

    type: behavioral / technical / mixed / case
    difficulty: entry / mid / senior
    duration: interview length in minutes
    persona: optional free-form interviewer persona description
    language: BCP-47 language tag (e.g. "en", "fr", "en-CM")
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    type: InterviewType = InterviewType.MIXED
    difficulty: InterviewDifficulty = InterviewDifficulty.MID
    duration: int = Field(default=30, ge=5, le=120)
    persona: Optional[str] = Field(default=None, max_length=500)
    language: str = Field(default="en", max_length=10)


class InterviewPlanQuestion(BaseModel):
    id: str
    text: str
    competency: str
    covered: bool = False


class InterviewQuestionPlan(BaseModel):
    competencies: List[str] = Field(default_factory=list)
    questions: List[InterviewPlanQuestion] = Field(default_factory=list)
    current_index: int = 0


# ---------------------------------------------------------------------------
# Slim text-only WebSocket protocol
# ---------------------------------------------------------------------------

class InterviewWebSocketAuth(BaseModel):
    type: Literal["auth"]
    token: str = Field(min_length=1, max_length=8_192)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class InterviewWebSocketConfig(BaseModel):
    type: Literal["config"]
    config: InterviewConfig

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class InterviewWebSocketUserText(BaseModel):
    type: Literal["user_text"]
    text: str = Field(min_length=1, max_length=10_000)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class InterviewWebSocketEnd(BaseModel):
    type: Literal["end"]

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class InterviewWebSocketPing(BaseModel):
    type: Literal["ping"]

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# Server -> client messages


class InterviewWSAuthOk(BaseModel):
    type: Literal["auth_ok"]
    session_state: str
    interview_id: int
    job_id: str


class InterviewWSAIToken(BaseModel):
    type: Literal["ai_token"]
    token: str
    index: int


class InterviewWSAIDone(BaseModel):
    type: Literal["ai_done"]
    text: str


class InterviewWSEnd(BaseModel):
    type: Literal["end"]
    session_state: str
    reason: Optional[str] = None


class InterviewWSError(BaseModel):
    type: Literal["error"]
    error: str
    error_type: Optional[str] = None


class InterviewWSPing(BaseModel):
    type: Literal["pong"]


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------

class TranscriptSegment(BaseModel):
    speaker: Literal["user", "assistant"]
    text: str
    start_ms: int
    end_ms: int

    model_config = ConfigDict(str_strip_whitespace=True)


class TranscriptResponse(BaseModel):
    interview_id: int
    segments: List[TranscriptSegment] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Interview feedback report
# ---------------------------------------------------------------------------


class InterviewReportQuestionScore(BaseModel):
    question: str
    answer: Optional[str] = None
    score: Optional[float] = None
    strengths: Optional[List[str]] = None
    gaps: Optional[List[str]] = None
    sample_answer: Optional[str] = None


class InterviewRubric(BaseModel):
    relevance: Optional[float] = None
    star_structure: Optional[float] = None
    specificity: Optional[float] = None
    communication: Optional[float] = None


class InterviewReportBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    interview_id: int
    user_id: int
    job_id: str
    resume_id: Optional[int] = None
    kanban_card_id: Optional[int] = None
    overall_score: Optional[float] = None
    per_question_scores: Optional[List[Dict[str, Any]]] = None
    strengths: Optional[List[str]] = None
    gaps: Optional[List[str]] = None
    sample_answer: Optional[Dict[str, Any]] = None
    rubric: Optional[Dict[str, Any]] = None
    feedback: Optional[Dict[str, Any]] = None
    report_data: Optional[Dict[str, Any]] = None


class InterviewReportCreate(InterviewReportBase):
    pass


class InterviewReport(InterviewReportBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InterviewReportResponse(InterviewReport):
    pass


class InterviewTrendsResponse(BaseModel):
    total_interviews: int = 0
    completed_interviews: int = 0
    average_score: Optional[float] = None
    score_trend: List[Dict[str, Any]] = Field(default_factory=list)
    common_strengths: List[str] = Field(default_factory=list)
    common_gaps: List[str] = Field(default_factory=list)
    rubric_averages: Optional[InterviewRubric] = None
    interviews_with_reports: int = 0


# ---------------------------------------------------------------------------
# Interview feedback report
# ---------------------------------------------------------------------------


class InterviewReportQuestionScore(BaseModel):
    question: str
    answer: Optional[str] = None
    score: Optional[float] = None
    strengths: Optional[List[str]] = None
    gaps: Optional[List[str]] = None
    sample_answer: Optional[str] = None


class InterviewRubric(BaseModel):
    relevance: Optional[float] = None
    star_structure: Optional[float] = None
    specificity: Optional[float] = None
    communication: Optional[float] = None


class InterviewReportBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    interview_id: int
    user_id: int
    job_id: str
    resume_id: Optional[int] = None
    kanban_card_id: Optional[int] = None
    overall_score: Optional[float] = None
    per_question_scores: Optional[List[Dict[str, Any]]] = None
    strengths: Optional[List[str]] = None
    gaps: Optional[List[str]] = None
    sample_answer: Optional[Dict[str, Any]] = None
    rubric: Optional[Dict[str, Any]] = None
    feedback: Optional[Dict[str, Any]] = None
    report_data: Optional[Dict[str, Any]] = None


class InterviewReportCreate(InterviewReportBase):
    pass


class InterviewReport(InterviewReportBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InterviewReportResponse(InterviewReport):
    pass


class InterviewTrendsResponse(BaseModel):
    total_interviews: int = 0
    completed_interviews: int = 0
    average_score: Optional[float] = None
    score_trend: List[Dict[str, Any]] = Field(default_factory=list)
    common_strengths: List[str] = Field(default_factory=list)
    common_gaps: List[str] = Field(default_factory=list)
    rubric_averages: Optional[InterviewRubric] = None
    interviews_with_reports: int = 0


# Keep backward compatibility
TranscriptResponse = TranscriptResponse  # type: ignore

