from __future__ import annotations

from app.api.schedules import router as schedules_router
from app.api.availability import router as availability_router
from app.api.master_data import router as master_data_router

__all__ = [
    "schedules_router",
    "availability_router",
    "master_data_router",
]
