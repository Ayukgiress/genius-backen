from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional, List

class KanbanCardBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=20_000)
    status: str = Field(default="todo", min_length=1, max_length=50)
    order: int = Field(default=0, ge=0)

class KanbanCardCreate(KanbanCardBase):
    board_id: Optional[int] = Field(default=None, gt=0)

class KanbanCardUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=20_000)
    status: Optional[str] = Field(default=None, min_length=1, max_length=50)
    order: Optional[int] = Field(default=None, ge=0)

class KanbanCard(KanbanCardBase):
    id: int
    board_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class KanbanBoardBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)

class KanbanBoardCreate(KanbanBoardBase):
    user_id: Optional[int] = Field(default=None, gt=0)

class KanbanBoardUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)

class KanbanBoard(KanbanBoardBase):
    id: int
    user_id: int
    created_at: datetime
    cards: List[KanbanCard] = []

    model_config = ConfigDict(from_attributes=True)
