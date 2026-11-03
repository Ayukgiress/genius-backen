from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal


class NextAction(BaseModel):
    id: str
    type: str
    title: str
    description: str
    priority: int = Field(ge=1, le=10)
    reason: str
    action: Dict[str, Any] = Field(default_factory=dict)
    deadline: Optional[datetime] = None


class NextActionsResponse(BaseModel):
    actions: List[NextAction] = Field(default_factory=list)
    generated_at: datetime


class CopilotChatMessage(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class CopilotChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=4000)
    history: List[CopilotChatMessage] = Field(default_factory=list)
    context: Optional[Dict[str, Any]] = None


class CopilotToolCall(BaseModel):
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None


class CopilotChatResponse(BaseModel):
    response: str
    tool_calls: List[CopilotToolCall] = Field(default_factory=list)
    suggestions: List[NextAction] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class WeeklySummary(BaseModel):
    user_id: int
    week_start: datetime
    week_end: datetime
    applications_count: int = 0
    interviews_count: int = 0
    score_changes: List[Dict[str, Any]] = Field(default_factory=list)
    goal_next_week: str
    highlights: List[str] = Field(default_factory=list)
    created_at: datetime
