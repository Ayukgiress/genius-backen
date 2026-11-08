from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from uvloop import install as install_uvloop
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
import logging
import asyncio

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
from app.routers.career_profile import router as career_profile_router
from app.routers.copilot import router as copilot_router
from app.db.session import engine, Base, SessionLocal
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
import app.models.career_profile
import app.models.event

app = FastAPI(title="Genius API", version="1.0.0", redirect_slashes=False)

# CORS Configuration
origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:5173",
    "http://localhost:5174",
    "https://genuis-pi.vercel.app",
    "https://genius-pi.vercel.app",
    "https://genuis-pi.vercel.app/",
    "https://genius-pi.vercel.app/",
    "https://genius-backen.onrender.com",
    "https://genius-backen.onrender.com/",
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

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])


async def _ensure_interview_session_metadata(conn):
    """Add optional interview fields to existing databases without data loss."""
    optional_columns = (
        ("persona_config", "JSONB"),
        ("session_metadata", "JSONB"),
        ("interviewer_type", "VARCHAR(50)"),
        ("camera_settings", "JSONB"),
        ("audio_settings", "JSONB"),
    )
    for column_name, column_type in optional_columns:
        await conn.execute(
            text(
                f"ALTER TABLE interviews ADD COLUMN IF NOT EXISTS "
                f"{column_name} {column_type} NULL"
            )
        )


def _error_response(request: Request, status_code: int, content: dict) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content=content)
    origin = request.headers.get("origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    response = _error_response(
        request,
        exc.status_code,
        {"detail": exc.detail, "message": str(exc.detail)},
    )
    if exc.headers:
        response.headers.update(exc.headers)
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    logger = logging.getLogger(__name__)
    logger.info("Request validation failed: method=%s path=%s", request.method, request.url.path)
    errors = [
        {"location": error.get("loc", []), "message": error.get("msg", "Invalid value"), "type": error.get("type")}
        for error in exc.errors()
    ]
    return _error_response(
        request,
        422,
        {"detail": "Request validation failed", "message": "Request validation failed", "errors": errors},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).exception(
        "Unhandled API error: method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return _error_response(
        request,
        500,
        {"detail": "Internal server error", "message": "Internal server error"},
    )

@app.on_event("startup")
async def startup():
    """Create database tables on startup."""
    try:
        print(f"DB URL: {engine.url}")

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
            await _ensure_interview_session_metadata(conn)
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255);"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_plan VARCHAR(50) DEFAULT 'free';"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50) DEFAULT 'inactive';"))
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_id VARCHAR(255);"))
        print("Database tables created/updated successfully!")

        # Initialize job scraping in the background so a slow scraper
        # can't block startup or health checks.
        async def _initialize_scraping_background():
            try:
                from app.services.job_scraper import job_service
                await job_service.initialize()
                print("Job scraping service initialized successfully!")
            except Exception as e:
                print(f"Job service initialization error (background): {e}")

        asyncio.create_task(_initialize_scraping_background())
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
app.include_router(career_profile_router, prefix="/api")
app.include_router(copilot_router, prefix="/api")
app.include_router(letters.router, prefix="/api")
from app.routers.debug import router as debug_router
app.include_router(debug_router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Welcome to Genius API"}


@app.get("/health")
@app.get("/api/health")
async def health_check():
    """Health check endpoint that never depends on scrapers or external calls."""
    return {"status": "healthy", "service": "genius-api"}
