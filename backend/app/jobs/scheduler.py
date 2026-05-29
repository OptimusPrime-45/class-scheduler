from __future__ import annotations

from datetime import date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Teacher,
    TeacherAvailability,
    AvailabilityWindow,
    TeacherType,
    AvailabilityStatus,
    AvailabilitySource
)
from app.services.scheduling import generate_schedule

# Configure the global scheduler instance
scheduler = AsyncIOScheduler()


async def start_scheduler():
    """Starts the AsyncIO background scheduler if not already running."""
    global scheduler
    if not scheduler.running:
        try:
            scheduler.start()
        except RuntimeError:
            # If the scheduler has been shut down, recreate it
            scheduler = AsyncIOScheduler()
            scheduler.start()


async def shutdown_scheduler():
    """Shuts down the AsyncIO background scheduler if it is running."""
    global scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)
        import asyncio
        await asyncio.sleep(0.05)


async def run_cutoff_job(session: AsyncSession, target_date: date):
    """Executes the Cutoff Job for the target date.
    
    For each active teacher who has NOT responded (no TeacherAvailability record for target_date):
      - If FULL_TIME: Create TeacherAvailability with status=PARTIAL (if standard availability exists)
        or status=AVAILABLE_ALL_DAY (if standard availability is empty). Copy standard availability
        windows to AvailabilityWindow rows.
      - If PART_TIME: Create TeacherAvailability with status=UNAVAILABLE.
    """
    # 1. Get all active teachers and load their standard availability
    stmt = (
        select(Teacher)
        .filter(Teacher.is_active == True)
        .options(selectinload(Teacher.standard_availability))
    )
    res = await session.execute(stmt)
    active_teachers = res.scalars().all()

    # 2. Find teacher IDs who already have availability for this target date
    avail_stmt = select(TeacherAvailability.teacher_id).filter(
        TeacherAvailability.availability_date == target_date
    )
    avail_res = await session.execute(avail_stmt)
    responded_teacher_ids = set(avail_res.scalars().all())

    # 3. Filter non-responded teachers
    unresponded_teachers = [t for t in active_teachers if t.id not in responded_teacher_ids]

    target_weekday = target_date.weekday()

    # Perform updates in a transaction/nested transaction block
    async with session.begin_nested() if session.in_transaction() else session.begin():
        for teacher in unresponded_teachers:
            if teacher.teacher_type == TeacherType.FULL_TIME:
                # Get active standard availabilities matching the target weekday
                std_avails = [
                    sa for sa in teacher.standard_availability
                    if sa.weekday == target_weekday and sa.is_active
                ]

                status = AvailabilityStatus.PARTIAL if std_avails else AvailabilityStatus.AVAILABLE_ALL_DAY

                ta = TeacherAvailability(
                    teacher_id=teacher.id,
                    availability_date=target_date,
                    status=status,
                    is_default=True,
                    source=AvailabilitySource.DEFAULT,
                )
                session.add(ta)
                await session.flush()  # Generates ta.id

                # Copy windows
                for sa in std_avails:
                    win = AvailabilityWindow(
                        availability_id=ta.id,
                        window_start=sa.window_start,
                        window_end=sa.window_end,
                    )
                    session.add(win)

            elif teacher.teacher_type == TeacherType.PART_TIME:
                ta = TeacherAvailability(
                    teacher_id=teacher.id,
                    availability_date=target_date,
                    status=AvailabilityStatus.UNAVAILABLE,
                    is_default=True,
                    source=AvailabilitySource.DEFAULT,
                )
                session.add(ta)


async def run_auto_solve_job(session: AsyncSession, target_date: date):
    """Executes the Auto-Solve Job which triggers automated schedule generation."""
    await generate_schedule(session, target_date)
