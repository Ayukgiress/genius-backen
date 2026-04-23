from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
import logging

# Patch passlib to work with bcrypt 4.0.0+
try:
    import bcrypt
    if not hasattr(bcrypt, "__about__"):
        bcrypt.__about__ = type("About", (object,), {"__version__": bcrypt.__version__})
except ImportError:
    pass

from app.routers import auth, resumes, analysis, analytics
from app.routers.kanban import router as kanban_router
from app.routers.jobs import router as jobs_router
from app.routers.interviews import router as interviews_router
from app.routers.preferences import router as preferences_router
from app.routers.payment import router as payment_router
from app.db.session import engine, Base
from app.core.config import settings
import app.models.user
import app.models.analysis
import app.models.analytics
import app.models.kanban
import app.models.resume
import app.models.job
import app.models.interview

app = FastAPI(title="Genius API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    """Create database tables on startup."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
            # Add missing columns for existing tables
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255);"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_plan VARCHAR(50) DEFAULT 'free';"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50) DEFAULT 'inactive';"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_id VARCHAR(255);"))
        print("Database tables created/updated successfully!")
    except Exception as e:
        print(f"Error during startup: {e}")

app.include_router(auth.router)
app.include_router(resumes.router)
app.include_router(kanban_router)
app.include_router(analysis.router)
app.include_router(analytics.router)
app.include_router(jobs_router)
app.include_router(interviews_router)
app.include_router(preferences_router)
app.include_router(payment_router)

@app.get("/")
async def root():
    return {"message": "Welcome to Genius API"}
