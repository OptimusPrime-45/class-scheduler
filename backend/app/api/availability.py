from __future__ import annotations

from datetime import date, time, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from typing import List

from app.db import get_session
from app.models import TeacherAvailability, AvailabilityWindow, AvailabilityStatus, AvailabilitySource

router = APIRouter()

# --------------------------------------------------------------------------- #
# Pydantic Schemas                                                           #
# --------------------------------------------------------------------------- #

class WindowInput(BaseModel):
    start: time
    end: time


class AvailabilityUpsertRequest(BaseModel):
    teacher_id: int
    availability_date: date
    status: AvailabilityStatus
    windows: List[WindowInput] = []
    source: AvailabilitySource = AvailabilitySource.ADMIN
    notes: str | None = None


class AvailabilityWindowResponse(BaseModel):
    id: int
    window_start: str
    window_end: str

    class Config:
        from_attributes = True


class TeacherAvailabilityResponse(BaseModel):
    id: int
    teacher_id: int
    availability_date: date
    status: AvailabilityStatus
    is_default: bool
    responded_at: datetime | None
    source: AvailabilitySource
    notes: str | None
    windows: List[AvailabilityWindowResponse] = []

    class Config:
        from_attributes = True


def to_availability_response(ta: TeacherAvailability) -> TeacherAvailabilityResponse:
    window_responses = []
    for w in getattr(ta, "windows", []):
        window_responses.append(
            AvailabilityWindowResponse(
                id=w.id,
                window_start=w.window_start.isoformat() if w.window_start else "00:00:00",
                window_end=w.window_end.isoformat() if w.window_end else "00:00:00",
            )
        )
    return TeacherAvailabilityResponse(
        id=ta.id,
        teacher_id=ta.teacher_id,
        availability_date=ta.availability_date,
        status=ta.status,
        is_default=ta.is_default,
        responded_at=ta.responded_at,
        source=ta.source,
        notes=ta.notes,
        windows=window_responses
    )


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #

@router.post("", response_model=TeacherAvailabilityResponse, status_code=status.HTTP_200_OK)
async def upsert_availability(
    body: AvailabilityUpsertRequest,
    session: AsyncSession = Depends(get_session)
):
    """Upserts a TeacherAvailability record.
    
    If the status changes or status is PARTIAL, updates/deletes windows accordingly.
    """
    # 1. Fetch existing TeacherAvailability
    stmt = (
        select(TeacherAvailability)
        .filter(
            TeacherAvailability.teacher_id == body.teacher_id,
            TeacherAvailability.availability_date == body.availability_date
        )
        .options(selectinload(TeacherAvailability.windows))
    )
    res = await session.execute(stmt)
    ta = res.scalar_one_or_none()

    if ta:
        # Update existing availability
        status_changed = ta.status != body.status
        ta.status = body.status
        ta.notes = body.notes
        ta.source = body.source
        ta.responded_at = datetime.now(timezone.utc)
        ta.is_default = False  # Explicitly updated by user/API

        # "Deletes old windows if status changed or updates windows in-place."
        # If status changed or status is PARTIAL, we update the window set.
        # Clearing and recreating windows under the same relationship is the most robust implementation
        # of in-place list update.
        if status_changed or body.status == AvailabilityStatus.PARTIAL:
            # Delete old windows
            for w in list(ta.windows):
                await session.delete(w)
            ta.windows = []

            # Add new windows if status is PARTIAL
            if body.status == AvailabilityStatus.PARTIAL:
                for w in body.windows:
                    win = AvailabilityWindow(
                        window_start=w.start,
                        window_end=w.end
                    )
                    ta.windows.append(win)
    else:
        # Create new availability
        ta = TeacherAvailability(
            teacher_id=body.teacher_id,
            availability_date=body.availability_date,
            status=body.status,
            is_default=False,
            responded_at=datetime.now(timezone.utc),
            source=body.source,
            notes=body.notes
        )
        if body.status == AvailabilityStatus.PARTIAL:
            for w in body.windows:
                win = AvailabilityWindow(
                    window_start=w.start,
                    window_end=w.end
                )
                ta.windows.append(win)
        session.add(ta)

    await session.commit()
    # Eagerly load the refreshed teacher availability with windows to avoid lazy loading error
    refresh_stmt = (
        select(TeacherAvailability)
        .filter(TeacherAvailability.id == ta.id)
        .options(selectinload(TeacherAvailability.windows))
    )
    refresh_res = await session.execute(refresh_stmt)
    ta = refresh_res.scalar_one()
    return to_availability_response(ta)


@router.get("/date/{date_val}", response_model=List[TeacherAvailabilityResponse])
async def get_availability_by_date(
    date_val: date,
    session: AsyncSession = Depends(get_session)
):
    """Returns all availability records for the given date."""
    stmt = (
        select(TeacherAvailability)
        .filter(TeacherAvailability.availability_date == date_val)
        .options(selectinload(TeacherAvailability.windows))
    )
    res = await session.execute(stmt)
    records = res.scalars().all()
    return [to_availability_response(r) for r in records]
