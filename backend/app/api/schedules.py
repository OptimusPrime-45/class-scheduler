from __future__ import annotations

from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from typing import List

from app.db import get_session
from app.models import Schedule, ScheduleEntry, ScheduleStatus, SolverStatus, EntryStatus
from app.services.scheduling import generate_schedule

router = APIRouter()

# --------------------------------------------------------------------------- #
# Pydantic Schemas for Response Serialization                                #
# --------------------------------------------------------------------------- #

class ScheduleEntryResponse(BaseModel):
    id: int
    schedule_id: int
    batch_id: int
    batch_slot_id: int | None
    period_index: int
    subject_id: int
    teacher_id: int | None
    status: EntryStatus
    is_locked: bool
    start_time: str
    end_time: str
    cancelled_reason: str | None
    conducted_at: datetime | None

    class Config:
        from_attributes = True

class ScheduleResponse(BaseModel):
    id: int
    schedule_date: date
    version: int
    status: ScheduleStatus
    solver_status: SolverStatus
    objective_value: float | None
    solve_time_ms: int | None
    num_unfilled: int
    solver_seed: int | None
    contract_version: str
    generated_at: datetime | None
    approved_at: datetime | None
    approved_by_user_id: int | None
    published_at: datetime | None
    published_by_user_id: int | None
    notes: str | None
    entries: List[ScheduleEntryResponse] = []

    class Config:
        from_attributes = True


# Helper to convert schedule models to Pydantic responses
def to_schedule_response(schedule: Schedule) -> ScheduleResponse:
    entries_responses = []
    # If entries are loaded, format times as HH:MM:SS strings or keep time objects
    for entry in getattr(schedule, "entries", []):
        entries_responses.append(
            ScheduleEntryResponse(
                id=entry.id,
                schedule_id=entry.schedule_id,
                batch_id=entry.batch_id,
                batch_slot_id=entry.batch_slot_id,
                period_index=entry.period_index,
                subject_id=entry.subject_id,
                teacher_id=entry.teacher_id,
                status=entry.status,
                is_locked=entry.is_locked,
                start_time=entry.start_time.isoformat() if entry.start_time else "00:00:00",
                end_time=entry.end_time.isoformat() if entry.end_time else "00:00:00",
                cancelled_reason=entry.cancelled_reason,
                conducted_at=entry.conducted_at,
            )
        )
    return ScheduleResponse(
        id=schedule.id,
        schedule_date=schedule.schedule_date,
        version=schedule.version,
        status=schedule.status,
        solver_status=schedule.solver_status,
        objective_value=schedule.objective_value,
        solve_time_ms=schedule.solve_time_ms,
        num_unfilled=schedule.num_unfilled,
        solver_seed=schedule.solver_seed,
        contract_version=schedule.contract_version,
        generated_at=schedule.generated_at,
        approved_at=schedule.approved_at,
        approved_by_user_id=schedule.approved_by_user_id,
        published_at=schedule.published_at,
        published_by_user_id=schedule.published_by_user_id,
        notes=schedule.notes,
        entries=entries_responses
    )


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #

@router.post("/generate", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def generate_schedule_endpoint(
    target_date: date = Query(..., description="Target date to generate schedule (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_session)
):
    """Triggers the load -> solve -> persist schedule pipeline for the target date."""
    try:
        schedule = await generate_schedule(session, target_date)
        # Fetch with entries to return full details
        stmt = select(Schedule).filter(Schedule.id == schedule.id).options(selectinload(Schedule.entries))
        res = await session.execute(stmt)
        full_schedule = res.scalar_one()
        return to_schedule_response(full_schedule)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate schedule: {str(e)}"
        )


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Retrieves a schedule by ID along with its entries."""
    stmt = (
        select(Schedule)
        .filter(Schedule.id == schedule_id)
        .options(selectinload(Schedule.entries))
    )
    res = await session.execute(stmt)
    schedule = res.scalar_one_or_none()
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule with ID {schedule_id} not found"
        )
    return to_schedule_response(schedule)


@router.get("/date/{date_val}", response_model=ScheduleResponse)
async def get_schedule_by_date(
    date_val: date,
    session: AsyncSession = Depends(get_session)
):
    """Retrieves the latest non-archived schedule for the given date."""
    stmt = (
        select(Schedule)
        .filter(
            Schedule.schedule_date == date_val,
            Schedule.status != ScheduleStatus.ARCHIVED
        )
        .order_by(Schedule.version.desc())
        .options(selectinload(Schedule.entries))
        .limit(1)
    )
    res = await session.execute(stmt)
    schedule = res.scalar_one_or_none()
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active schedule found for date {date_val}"
        )
    return to_schedule_response(schedule)


@router.post("/{schedule_id}/approve", response_model=ScheduleResponse)
async def approve_schedule(
    schedule_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Updates status to APPROVED and stamps approved_at = UTC now."""
    stmt = (
        select(Schedule)
        .filter(Schedule.id == schedule_id)
        .options(selectinload(Schedule.entries))
    )
    res = await session.execute(stmt)
    schedule = res.scalar_one_or_none()
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule with ID {schedule_id} not found"
        )
    
    schedule.status = ScheduleStatus.APPROVED
    schedule.approved_at = datetime.now(timezone.utc)
    
    await session.commit()
    # Eagerly load the refreshed schedule with entries to avoid lazy loading error
    refresh_stmt = (
        select(Schedule)
        .filter(Schedule.id == schedule.id)
        .options(selectinload(Schedule.entries))
    )
    refresh_res = await session.execute(refresh_stmt)
    schedule = refresh_res.scalar_one()
    return to_schedule_response(schedule)


@router.post("/{schedule_id}/publish", response_model=ScheduleResponse)
async def publish_schedule(
    schedule_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Updates status to PUBLISHED and stamps published_at = UTC now."""
    stmt = (
        select(Schedule)
        .filter(Schedule.id == schedule_id)
        .options(selectinload(Schedule.entries))
    )
    res = await session.execute(stmt)
    schedule = res.scalar_one_or_none()
    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule with ID {schedule_id} not found"
        )
    
    schedule.status = ScheduleStatus.PUBLISHED
    schedule.published_at = datetime.now(timezone.utc)
    
    await session.commit()
    # Eagerly load the refreshed schedule with entries to avoid lazy loading error
    refresh_stmt = (
        select(Schedule)
        .filter(Schedule.id == schedule.id)
        .options(selectinload(Schedule.entries))
    )
    refresh_res = await session.execute(refresh_stmt)
    schedule = refresh_res.scalar_one()
    return to_schedule_response(schedule)
