from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.kanban import KanbanBoard, KanbanCard
from app.schemas.kanban import KanbanBoardCreate, KanbanBoardUpdate, KanbanCardCreate, KanbanCardUpdate
from typing import List

# Board CRUD
async def get_board(db: AsyncSession, board_id: int):
    result = await db.execute(select(KanbanBoard).where(KanbanBoard.id == board_id))
    return result.scalar_one_or_none()

async def get_boards_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(select(KanbanBoard).where(KanbanBoard.user_id == user_id))
    return result.scalars().all()

async def create_board(db: AsyncSession, board: KanbanBoardCreate):
    db_board = KanbanBoard(**board.model_dump())
    db.add(db_board)
    await db.commit()
    await db.refresh(db_board)
    return db_board

async def update_board(db: AsyncSession, db_board: KanbanBoard, board: KanbanBoardUpdate):
    board_data = board.model_dump(exclude_unset=True)
    for key, value in board_data.items():
        setattr(db_board, key, value)
    db.add(db_board)
    await db.commit()
    await db.refresh(db_board)
    return db_board

# Card CRUD
async def get_card(db: AsyncSession, card_id: int):
    result = await db.execute(select(KanbanCard).where(KanbanCard.id == card_id))
    return result.scalar_one_or_none()

async def get_cards_by_board(db: AsyncSession, board_id: int):
    result = await db.execute(select(KanbanCard).where(KanbanCard.board_id == board_id))
    return result.scalars().all()

async def create_card(db: AsyncSession, card: KanbanCardCreate):
    db_card = KanbanCard(**card.model_dump())
    db.add(db_card)
    await db.commit()
    await db.refresh(db_card)
    return db_card

async def update_card(db: AsyncSession, db_card: KanbanCard, card: KanbanCardUpdate):
    card_data = card.model_dump(exclude_unset=True)
    for key, value in card_data.items():
        setattr(db_card, key, value)
    db.add(db_card)
    await db.commit()
    await db.refresh(db_card)
    return db_card

async def delete_card(db: AsyncSession, db_card: KanbanCard):
    await db.delete(db_card)
    await db.commit()
    return True
