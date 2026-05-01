import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from app.models.user import User
from app.core.config import settings

async def check_token():
    database_url = settings.DATABASE_URL
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url, echo=False)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as session:
        # Check all users
        result = await session.execute(select(User))
        users = result.scalars().all()
        print(f"Total users: {len(users)}")
        for u in users:
            print(f"  ID: {u.id}, Email: {u.email}, Verified: {u.is_verified}, Token: {u.verification_token}, Updated: {u.updated_at}")
        
        token = "Oy1d0E0uMIju4i94X48RSaiY6-78YT6GKZp6RDGhHDg"
        result = await session.execute(select(User).where(User.verification_token == token))
        user = result.scalar_one_or_none()
        if user:
            print(f"User found: {user.email}, verified: {user.is_verified}, expires: {user.verification_token_expires}")
        else:
            print("No user found with that token")
        
        # Also check all users with verification_token not null
        result2 = await session.execute(select(User).where(User.verification_token.isnot(None)))
        users = result2.scalars().all()
        print(f"Users with verification tokens: {len(users)}")
        for u in users:
            print(f"  {u.email}: {u.verification_token[:10]}..., verified: {u.is_verified}")

if __name__ == "__main__":
    asyncio.run(check_token())