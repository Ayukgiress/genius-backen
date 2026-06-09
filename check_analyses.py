import asyncio
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.analysis import Analysis

async def check():
    async with SessionLocal() as db:
        result = await db.execute(select(Analysis).limit(5))
        analyses = result.scalars().all()
        for a in analyses:
            print(f"ID: {a.id}, Status: {a.status}, Result: {a.result}")

if __name__ == "__main__":
    asyncio.run(check())
