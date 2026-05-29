"""FastAPI application entrypoint.

Phase 0 ships only the app skeleton + health checks. Routers, the Telegram webhook
mount, and the APScheduler job runner are wired in later phases.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup hooks (scheduler, bot webhook registration) attach here from Phase 2/3.
    yield
    # Clean shutdown: release pooled DB connections.
    await engine.dispose()


app = FastAPI(title="Tuition Scheduler", version="0.1.0", lifespan=lifespan)


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
