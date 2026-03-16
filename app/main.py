from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, resumes, analysis, analytics
from app.routers.kanban import router as kanban_router
from app.db.session import engine, Base
import app.models.user
import app.models.analysis
import app.models.analytics
import app.models.kanban
import app.models.resume

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
    from sqlalchemy import text
    try:
        # First, try to connect and create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("Database tables created successfully!")
    except Exception as e:
        print(f"Error during startup: {e}")
        # Try to create database if it doesn't exist
        try:
            # Extract db name from URL for creating database
            db_url = str(settings.DATABASE_URL)
            # Create a connection to the default 'postgres' database
            from sqlalchemy.ext.asyncio import create_async_engine
            
            # Parse the DATABASE_URL to get connection details
            # Format: postgresql+asyncpg://user:password@host:port/dbname
            if "localhost" in db_url:
                # Try connecting to postgres db to create the database
                create_db_url = db_url.replace("/genius", "/postgres")
                temp_engine = create_async_engine(create_db_url, echo=False)
                
                async with temp_engine.connect() as conn:
                    # Check if database exists
                    result = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = 'genius'"))
                    exists = result.scalar()
                    
                    if not exists:
                        await conn.execute(text("CREATE DATABASE genius"))
                        print("Database 'genius' created!")
                    
                await temp_engine.dispose()
                
                # Now create tables
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                print("Database tables created successfully!")
        except Exception as db_error:
            print(f"Could not create database: {db_error}")

app.include_router(auth.router)
app.include_router(resumes.router)
app.include_router(kanban_router)
app.include_router(analysis.router)
app.include_router(analytics.router)

@app.get("/")
async def root():
    return {"message": "Welcome to Genius API"}
