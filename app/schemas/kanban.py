from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List

class KanbanCardBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "todo"
    order: int = 0

class KanbanCardCreate(KanbanCardBase):
    board_id: int

class KanbanCardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    order: Optional[int] = None

class KanbanCard(KanbanCardBase):
    id: int
    board_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class KanbanBoardBase(BaseModel):
    name: str

class KanbanBoardCreate(KanbanBoardBase):
    user_id: int

class KanbanBoardUpdate(BaseModel):
    name: Optional[str] = None

class KanbanBoard(KanbanBoardBase):
    id: int
    user_id: int
    created_at: datetime
    cards: List[KanbanCard] = []

    model_config = ConfigDict(from_attributes=True)
