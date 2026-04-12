from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timedelta, timezone
from app.db.session import get_db
from app.crud.user import create_user, get_user_by_email, verify_password, verify_user_email, regenerate_verification_token, get_or_create_google_user
from app.schemas.user import UserCreate, User, Token, UserCreateResponse, VerificationResponse
from app.core.security import create_access_token
from app.services.email import send_verification_email
from app.routers.deps import get_current_user
from app.core.config import settings
import httpx

router = APIRouter(prefix="/auth", tags=["auth"])

# Google OAuth URLs
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

def get_google_oauth_url() -> str:
    """Generate Google OAuth authorization URL."""
    import urllib.parse
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent"
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


@router.get("/google")
async def google_login():
    """Redirect to Google OAuth authorization page."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Please contact the administrator."
        )
    auth_url = get_google_oauth_url()
    return {"authorization_url": auth_url}


@router.get("/google/callback")
async def google_callback(code: str, db: AsyncSession = Depends(get_db)):
    """Handle Google OAuth callback and exchange code for tokens."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured."
        )
    
    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        # Get access token
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.GOOGLE_REDIRECT_URI
            }
        )
        
        if token_response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to exchange code for tokens"
            )
        
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        
        # Get user info
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if userinfo_response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Failed to get user info"
            )
        
        userinfo = userinfo_response.json()
        
        email = userinfo.get("email")
        name = userinfo.get("name", "")
        google_id = userinfo.get("id")
        
        if not email or not google_id:
            raise HTTPException(
                status_code=400,
                detail="Failed to get email from Google"
            )
    
    # Get or create user
    user = await get_or_create_google_user(db, email, name, google_id)
    
    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    # Create access token
    access_token = create_access_token(subject=user.email)
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name
        }
    }

@router.post("/register", response_model=UserCreateResponse)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    user = await get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = await create_user(db, user=user_in)
    
    # Send verification email
    if user.verification_token:
        await send_verification_email(user.email, user.verification_token)
    
    return UserCreateResponse(
        message="User registered successfully. Please check your email to verify your account.",
        user=user
    )

@router.post("/verify-email", response_model=VerificationResponse)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    """Verify user email with the provided token."""
    from sqlalchemy import select
    from app.models.user import User
    
    result = await db.execute(
        select(User).where(User.verification_token == token)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Invalid verification token.",
        )
    
    if user.is_verified:
        raise HTTPException(
            status_code=400,
            detail="Email already verified.",
        )
    
    # Handle both timezone-aware and timezone-naive datetimes
    if user.verification_token_expires:
        expires_at = user.verification_token_expires
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        if expires_at < datetime.now():
            raise HTTPException(
                status_code=400,
                detail="Verification token has expired.",
            )
    
    await verify_user_email(db, user)
    
    return VerificationResponse(message="Email verified successfully!")


@router.get("/verify-email-page")
async def verify_email_page(token: str, db: AsyncSession = Depends(get_db)):
    """Verify user email and return an HTML page."""
    from sqlalchemy import select
    from app.models.user import User
    
    result = await db.execute(
        select(User).where(User.verification_token == token)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        return {
            "status": "error",
            "message": "Invalid verification token."
        }
    
    if user.is_verified:
        return {
            "status": "already_verified",
            "message": "Email already verified."
        }
    
    # Handle both timezone-aware and timezone-naive datetimes
    if user.verification_token_expires:
        expires_at = user.verification_token_expires
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        if expires_at < datetime.now():
            return {
                "status": "error",
                "message": "Verification token has expired."
            }
    
    await verify_user_email(db, user)
    
    return {
        "status": "success",
        "message": "Email verified successfully!"
    }


@router.get("/verify-email-html")
async def verify_email_html(token: str, db: AsyncSession = Depends(get_db)):
    """Verify user email and return an HTML page."""
    from sqlalchemy import select
    from app.models.user import User
    from fastapi.responses import HTMLResponse
    
    result = await db.execute(
        select(User).where(User.verification_token == token)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h2 style="color: red;">Invalid Verification Token</h2>
                <p>The verification token is invalid or has already been used.</p>
                <p>Please register again or request a new verification email.</p>
            </body>
            </html>
            """,
            status_code=400
        )
    
    if user.is_verified:
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h2 style="color: orange;">Email Already Verified</h2>
                <p>Your email has already been verified.</p>
                <p>You can now log in to your account.</p>
            </body>
            </html>
            """
        )
    
    # Handle both timezone-aware and timezone-naive datetimes
    if user.verification_token_expires:
        expires_at = user.verification_token_expires
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        if expires_at < datetime.now():
            return HTMLResponse(
                content="""
                <!DOCTYPE html>
                <html>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h2 style="color: red;">Verification Token Expired</h2>
                    <p>The verification token has expired.</p>
                <p>Please request a new verification email.</p>
            </body>
            </html>
            """,
            status_code=400
        )
    
    await verify_user_email(db, user)
    
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h2 style="color: green;">Email Verified Successfully!</h2>
            <p>Your email has been verified.</p>
            <p>You can now log in to your account.</p>
        </body>
        </html>
        """
    )

@router.post("/resend-verification", response_model=VerificationResponse)
async def resend_verification(email: str, db: AsyncSession = Depends(get_db)):
    """Resend verification email to the user."""
    user = await get_user_by_email(db, email=email)
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )
    
    if user.is_verified:
        raise HTTPException(
            status_code=400,
            detail="Email already verified.",
        )
    
    # Regenerate verification token
    user = await regenerate_verification_token(db, user)
    
    # Send verification email
    await send_verification_email(user.email, user.verification_token)
    
    return VerificationResponse(message="Verification email sent. Please check your inbox.")

@router.post("/token", response_model=Token)
async def login(
    db: AsyncSession = Depends(get_db), 
    form_data: OAuth2PasswordRequestForm = Depends()
):
    user = await get_user_by_email(db, email=form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    
    # Check if email is verified
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email not verified. Please verify your email address.",
        )
    
    access_token = create_access_token(subject=user.email)
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=User)
async def update_me(
    name: Optional[str] = None,
    bio: Optional[str] = None,
    career_preferences: Optional[dict] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update current user profile."""
    if name is not None:
        current_user.name = name
    if bio is not None:
        current_user.bio = bio
    if career_preferences is not None:
        current_user.career_preferences = career_preferences
    
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user

@router.post("/logout")
async def logout():
    return {"message": "User logged out"}

@router.post("/refresh", response_model=Token)
async def refresh_token(current_user: User = Depends(get_current_user)):
    access_token = create_access_token(subject=current_user.email)
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/google")
async def google_oauth():
    return {"message": "Google OAuth login"}
