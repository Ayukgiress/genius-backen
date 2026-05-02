from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
import logging

# Patch passlib to work with bcrypt 4.0.0+
try:
    import bcrypt
    if not hasattr(bcrypt, "__about__"):
        bcrypt.__about__ = type("About", (object,), {"__version__": bcrypt.__version__})
except ImportError:
    pass

from app.routers import auth, resumes, analysis, analytics, letters
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
import app.models.user_usage
import app.models.letter

app = FastAPI(title="Genius API", version="1.0.0", redirect_slashes=False)

# CORS Configuration
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "https://genuis-pi.vercel.app",
    "https://genius-pi.vercel.app",
    "https://genuis-pi.vercel.app/",
    "https://genius-pi.vercel.app/",
]

if settings.FRONTEND_URL:
    if settings.FRONTEND_URL not in origins:
        origins.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Global error: {exc}", exc_info=True)
    
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        detail = exc.detail
        message = str(exc.detail)
    else:
        status_code = 500
        detail = "Internal Server Error"
        message = str(exc)
        
    response = JSONResponse(
        status_code=status_code,
        content={"detail": detail, "message": message},
    )
    
    # Manually add CORS headers to error responses as they sometimes bypass middleware
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
            
    return response

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
app.include_router(resumes.router, prefix="/api")
app.include_router(kanban_router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(interviews_router, prefix="/api")
app.include_router(preferences_router, prefix="/api")
app.include_router(payment_router, prefix="/api")
app.include_router(letters.router, prefix="/api")
from app.routers.debug import router as debug_router
app.include_router(debug_router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Welcome to Genius API"}

# Handler for Vercel deployment
from mangum import Mangum
handler = Mangum(app, lifespan="off")
