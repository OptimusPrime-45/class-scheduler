from __future__ import annotations

import sys
import pytest
from datetime import date, time
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import Base, engine
from app.models import (
    Teacher,
    TeacherType,
    TeacherAvailability,
    TeacherStandardAvailability,
    AvailabilityWindow,
    AvailabilityStatus,
    AvailabilitySource,
    Weekday,
    Schedule,
    ScheduleStatus,
    SolverStatus,
    InstitutionSettings,
    SettingsScope,
    Subject,
    Batch,
    BatchSlot,
    BatchSubject,
    TeacherSubject,
    SubjectDifficulty,
    Board
)
import app.jobs.scheduler
from app.jobs.scheduler import run_cutoff_job, run_auto_solve_job, start_scheduler, shutdown_scheduler

# --------------------------------------------------------------------------- #
# Transactional DB Fixture                                                   #
# --------------------------------------------------------------------------- #

@pytest.fixture
async def session():
    """Provides a transactional database session that rolls back after each test."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            # Clean slate: Truncate tables first (in this transaction).
            # This is fully rolled back, leaving the dev database untouched.
            tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
            await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
            
            yield session
        await transaction.rollback()
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Scheduler Lifecycle Tests                                                  #
# --------------------------------------------------------------------------- #

async def test_scheduler_lifecycle():
    """Verifies starting and stopping the APScheduler instance."""
    scheduler_mod = sys.modules['app.jobs.scheduler']
    
    # Reset/ensure stopped state first since other tests/lifespans may have started it
    if scheduler_mod.scheduler.running:
        await shutdown_scheduler()
    
    scheduler_mod = sys.modules['app.jobs.scheduler']
    assert not scheduler_mod.scheduler.running
    await start_scheduler()
    
    # Refresh reference from sys.modules in case global variable was reassigned
    scheduler_mod = sys.modules['app.jobs.scheduler']
    assert scheduler_mod.scheduler.running
    
    await shutdown_scheduler()
    
    scheduler_mod = sys.modules['app.jobs.scheduler']
    assert not scheduler_mod.scheduler.running


# --------------------------------------------------------------------------- #
# Cutoff Job Tests                                                           #
# --------------------------------------------------------------------------- #

async def test_run_cutoff_job_behaviors(session: AsyncSession):
    # Setup Teachers:
    # 1. Full-time with standard availability on Monday (Weekday.MON == 0)
    t_ft_with_std = Teacher(
        full_name="FT with Standard",
        teacher_type=TeacherType.FULL_TIME,
        max_lectures_per_day=3,
        is_active=True
    )
    session.add(t_ft_with_std)
    await session.flush()

    std_avail = TeacherStandardAvailability(
        teacher_id=t_ft_with_std.id,
        weekday=Weekday.MON,
        window_start=time(14, 0),
        window_end=time(18, 0),
        is_active=True
    )
    session.add(std_avail)

    # 2. Full-time with no standard availability
    t_ft_no_std = Teacher(
        full_name="FT no Standard",
        teacher_type=TeacherType.FULL_TIME,
        max_lectures_per_day=3,
        is_active=True
    )
    session.add(t_ft_no_std)

    # 3. Part-time
    t_pt = Teacher(
        full_name="Part Time Teacher",
        teacher_type=TeacherType.PART_TIME,
        max_lectures_per_day=2,
        is_active=True
    )
    session.add(t_pt)

    # 4. Inactive teacher (should be ignored)
    t_inactive = Teacher(
        full_name="Inactive Teacher",
        teacher_type=TeacherType.FULL_TIME,
        max_lectures_per_day=3,
        is_active=False
    )
    session.add(t_inactive)

    # 5. Teacher who has already responded (should be ignored)
    t_responded = Teacher(
        full_name="Already Responded Teacher",
        teacher_type=TeacherType.PART_TIME,
        max_lectures_per_day=3,
        is_active=True
    )
    session.add(t_responded)
    await session.flush()

    existing_ta = TeacherAvailability(
        teacher_id=t_responded.id,
        availability_date=date(2026, 6, 1),  # Monday
        status=AvailabilityStatus.AVAILABLE_ALL_DAY,
        is_default=False,
        source=AvailabilitySource.TELEGRAM
    )
    session.add(existing_ta)
    await session.flush()

    # Execute the Cutoff Job for target date Monday, June 1, 2026
    target_date = date(2026, 6, 1)
    await run_cutoff_job(session, target_date)

    # --- Verification ---

    # Fetch all created availabilities for the target date
    stmt = (
        select(TeacherAvailability)
        .filter(TeacherAvailability.availability_date == target_date)
        .options(selectinload(TeacherAvailability.windows))
    )
    res = await session.execute(stmt)
    availabilities = res.scalars().all()
    avail_by_teacher_id = {ta.teacher_id: ta for ta in availabilities}

    # 1. Full-time with standard: should have status=PARTIAL, is_default=True, source=DEFAULT, and copied windows
    ta_ft_with_std = avail_by_teacher_id[t_ft_with_std.id]
    assert ta_ft_with_std.status == AvailabilityStatus.PARTIAL
    assert ta_ft_with_std.is_default is True
    assert ta_ft_with_std.source == AvailabilitySource.DEFAULT
    assert len(ta_ft_with_std.windows) == 1
    assert ta_ft_with_std.windows[0].window_start == time(14, 0)
    assert ta_ft_with_std.windows[0].window_end == time(18, 0)

    # 2. Full-time without standard: should have status=AVAILABLE_ALL_DAY, is_default=True, source=DEFAULT, no windows
    ta_ft_no_std = avail_by_teacher_id[t_ft_no_std.id]
    assert ta_ft_no_std.status == AvailabilityStatus.AVAILABLE_ALL_DAY
    assert ta_ft_no_std.is_default is True
    assert ta_ft_no_std.source == AvailabilitySource.DEFAULT
    assert len(ta_ft_no_std.windows) == 0

    # 3. Part-time: should have status=UNAVAILABLE, is_default=True, source=DEFAULT
    ta_pt = avail_by_teacher_id[t_pt.id]
    assert ta_pt.status == AvailabilityStatus.UNAVAILABLE
    assert ta_pt.is_default is True
    assert ta_pt.source == AvailabilitySource.DEFAULT
    assert len(ta_pt.windows) == 0

    # 4. Inactive teacher: should NOT have any availability created
    assert t_inactive.id not in avail_by_teacher_id

    # 5. Already responded teacher: should retain their original response and NOT have a new default one created
    ta_responded = avail_by_teacher_id[t_responded.id]
    assert ta_responded.status == AvailabilityStatus.AVAILABLE_ALL_DAY
    assert ta_responded.is_default is False
    assert ta_responded.source == AvailabilitySource.TELEGRAM


# --------------------------------------------------------------------------- #
# Auto Solve Job Tests                                                       #
# --------------------------------------------------------------------------- #

async def test_run_auto_solve_job(session: AsyncSession):
    # Setup data needed for schedule generation
    # 1. Global settings
    settings = InstitutionSettings(
        name="default",
        scope=SettingsScope.GLOBAL,
        week_start_day=Weekday.MON,
        timezone="Asia/Kolkata",
        solver_time_limit_seconds=10.0
    )
    session.add(settings)

    # 2. Subjects
    math = Subject(code="MATH", name="Mathematics", difficulty=SubjectDifficulty.DIFFICULT)
    session.add(math)

    # 3. Batches
    batch1 = Batch(name="Grade 8 SSC", grade=8, board=Board.SSC)
    session.add(batch1)
    await session.flush()

    # 4. Slots on Monday
    slot1 = BatchSlot(batch_id=batch1.id, weekday=Weekday.MON, period_index=1, start_time=time(16, 0), end_time=time(17, 0))
    session.add(slot1)

    # 5. Teachers
    t_full = Teacher(
        full_name="Full Time Teacher",
        teacher_type=TeacherType.FULL_TIME,
        max_lectures_per_day=3,
        preferred_hours_start=time(16, 0),
        preferred_hours_end=time(19, 0)
    )
    session.add(t_full)
    await session.flush()

    # Qualification
    ts1 = TeacherSubject(teacher_id=t_full.id, subject_id=math.id, proficiency=5)
    session.add(ts1)

    # Availability
    ta = TeacherAvailability(
        teacher_id=t_full.id,
        availability_date=date(2026, 6, 1),
        status=AvailabilityStatus.AVAILABLE_ALL_DAY
    )
    session.add(ta)

    # 6. Batch Subjects
    bs1 = BatchSubject(batch_id=batch1.id, subject_id=math.id, weekly_target=4, owner_teacher_id=t_full.id)
    session.add(bs1)
    await session.flush()

    # Run auto solve job
    target_date = date(2026, 6, 1)
    await run_auto_solve_job(session, target_date)

    # Verify a schedule is created for the target date
    stmt = select(Schedule).filter(Schedule.schedule_date == target_date)
    res = await session.execute(stmt)
    schedule = res.scalar_one_or_none()
    
    assert schedule is not None
    assert schedule.status == ScheduleStatus.DRAFT
