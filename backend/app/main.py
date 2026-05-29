"""FastAPI application entrypoint.

Wires the API routers, the Telegram webhook mount, and the APScheduler job runner.
On startup the scheduler registers the nightly jobs (poll-open, reminders, cutoff,
auto-solve) from the global InstitutionSettings windows; see app/jobs/scheduler.py.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal, engine
from app.jobs import start_scheduler, shutdown_scheduler
from app.api import schedules_router, availability_router, master_data_router
from app.bot import bot_router


from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup hooks: start APScheduler job runner
    await start_scheduler()
    yield
    # Clean shutdown: stop scheduler and release pooled DB connections.
    await shutdown_scheduler()
    await engine.dispose()


app = FastAPI(title="Tuition Scheduler", version="0.1.0", lifespan=lifespan)

# Add CORS Middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers under prefix '/api'
app.include_router(schedules_router, prefix="/api/schedules", tags=["schedules"])
app.include_router(availability_router, prefix="/api/availability", tags=["availability"])
app.include_router(master_data_router, prefix="/api", tags=["master-data"])
app.include_router(bot_router, tags=["bot"])


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Liveness probe — does not touch the database."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/health/db", tags=["health"])
async def health_db() -> dict:
    """Readiness probe — proves DB connectivity end to end (``SELECT 1``)."""
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception as exc:  # surfaced, never swallowed
        return {"status": "error", "database": "unreachable", "detail": str(exc)}

