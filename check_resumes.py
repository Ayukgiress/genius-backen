import asyncio
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.resume import Resume

async def check():
    async with SessionLocal() as db:
        result = await db.execute(select(Resume).limit(5))
        resumes = result.scalars().all()
        print(f"Found {len(resumes)} resumes")
        for r in resumes:
            print(f"ID: {r.id}, Name: {r.file_name}, Content Length: {len(r.content) if r.content else 0}")

if __name__ == "__main__":
    asyncio.run(check())
