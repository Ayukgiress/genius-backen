from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.schemas.user import User
from app.schemas.kanban import KanbanBoard, KanbanBoardCreate, KanbanBoardUpdate, KanbanCard, KanbanCardCreate, KanbanCardUpdate
from app.crud.kanban import (
    get_board, get_boards_by_user, create_board, update_board,
    get_card, get_cards_by_board, create_card, update_card, delete_card
)

router = APIRouter(prefix="/kanban", tags=["kanban"])

# Board routes
@router.get("/boards", response_model=List[KanbanBoard])
async def list_boards(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_boards_by_user(db, user_id=current_user.id)

@router.post("/boards", response_model=KanbanBoard, status_code=status.HTTP_201_CREATED)
async def create_kanban_board(
    board_in: KanbanBoardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board_data = board_in.model_dump()
    board_data["user_id"] = current_user.id
    board = KanbanBoardCreate(**board_data)
    return await create_board(db, board)

@router.get("/boards/{board_id}", response_model=KanbanBoard)
async def get_kanban_board(
    board_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board = await get_board(db, board_id)
    if not board or board.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Board not found")
    return board

@router.patch("/boards/{board_id}", response_model=KanbanBoard)
async def update_kanban_board(
    board_id: int,
    board_in: KanbanBoardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board = await get_board(db, board_id)
    if not board or board.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Board not found")
    return await update_board(db, board, board_in)

# Card routes
@router.get("/boards/{board_id}/cards", response_model=List[KanbanCard])
async def list_cards(
    board_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board = await get_board(db, board_id)
    if not board or board.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Board not found")
    return await get_cards_by_board(db, board_id)

@router.post("/boards/{board_id}/cards", response_model=KanbanCard, status_code=status.HTTP_201_CREATED)
async def create_kanban_card(
    board_id: int,
    card_in: KanbanCardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    board = await get_board(db, board_id)
    if not board or board.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Board not found")
    card_data = card_in.model_dump()
    card_data["board_id"] = board_id
    card = KanbanCardCreate(**card_data)
    return await create_card(db, card)

@router.get("/cards/{card_id}", response_model=KanbanCard)
async def get_kanban_card(
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    card = await get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    board = await get_board(db, card.board_id)
    if not board or board.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Card not found")
    return card

@router.patch("/cards/{card_id}", response_model=KanbanCard)
async def update_kanban_card(
    card_id: int,
    card_in: KanbanCardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    card = await get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    board = await get_board(db, card.board_id)
    if not board or board.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Card not found")
    return await update_card(db, card, card_in)

@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kanban_card(
    card_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    card = await get_card(db, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    board = await get_board(db, card.board_id)
    if not board or board.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Card not found")
    await delete_card(db, card)
    return None
