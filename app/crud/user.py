from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.services.email import generate_verification_token
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

async def get_user(db: AsyncSession, user_id: int):
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

async def get_user_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()

async def create_user(db: AsyncSession, user: UserCreate):
    verification_token, token_expires = generate_verification_token()
    db_user = User(
        email=user.email,
        name=user.name,
        hashed_password=get_password_hash(user.password),
        verification_token=verification_token,
        verification_token_expires=token_expires
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

async def verify_user_email(db: AsyncSession, user: User) -> User:
    """Mark a user's email as verified."""
    user.is_verified = True
    user.verification_token = None
    user.verification_token_expires = None
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def update_user(db: AsyncSession, db_user: User, user: UserUpdate):
    user_data = user.model_dump(exclude_unset=True)
    for key, value in user_data.items():
        setattr(db_user, key, value)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

async def regenerate_verification_token(db: AsyncSession, user: User):
    """Regenerate a new verification token for a user."""
    verification_token, token_expires = generate_verification_token()
    user.verification_token = verification_token
    user.verification_token_expires = token_expires
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_google_id(db: AsyncSession, google_id: str):
    """Get a user by Google ID."""
    result = await db.execute(select(User).where(User.google_id == google_id))
    return result.scalar_one_or_none()


async def create_google_user(db: AsyncSession, email: str, name: str, google_id: str):
    """Create a new user via Google OAuth."""
    db_user = User(
        email=email,
        name=name,
        google_id=google_id,
        oauth_provider="google",
        is_verified=True  # Google email is already verified
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


async def get_or_create_google_user(db: AsyncSession, email: str, name: str, google_id: str):
    """Get existing user or create a new one via Google OAuth."""
    # First check if user exists by email
    user = await get_user_by_email(db, email)
    
    if user:
        # If user exists but doesn't have google_id, link it
        if not user.google_id:
            user.google_id = google_id
            user.oauth_provider = "google"
            if not user.is_verified:
                user.is_verified = True  # Google email is verified
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user
    
    # Create new user
    return await create_google_user(db, email, name, google_id)


async def update_career_preferences(db: AsyncSession, user_id: int, preferences: Optional[dict]):
    """Update user's career preferences."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.career_preferences = preferences
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user
