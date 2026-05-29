from __future__ import annotations

import pytest
from datetime import date, time, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import Base, engine
from app.models import (
    InstitutionSettings,
    SettingsScope,
    Weekday,
    Batch,
    Subject,
    BatchSlot,
    BatchSubject,
    Teacher,
    TeacherAvailability,
    AvailabilityStatus,
    TeacherStandardAvailability,
    TeacherSubject,
    TeacherType,
    SubjectDifficulty,
    Schedule,
    ScheduleEntry,
    EntryStatus,
    ScheduleStatus,
    SolverStatus,
    Board,
)
from app.services.loader import load_solver_input
from app.services.persister import persist_solver_result
from app.services.scheduling import generate_schedule
from app.schemas import (
    SolverResult,
    Assignment,
    UnfilledSlot,
    CSolverStatus,
)


from sqlalchemy import text

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
            
            # We open a nested transaction so that code using session.begin_nested()
            # works seamlessly under test.
            async with session.begin_nested():
                yield session
        await transaction.rollback()
    await engine.dispose()


async def setup_test_data(session: AsyncSession):
    """Inserts a minimal database schema representation for test cases."""
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
    eng = Subject(code="ENG", name="English", difficulty=SubjectDifficulty.STANDARD)
    session.add_all([math, eng])

    # 3. Batches
    batch1 = Batch(name="Grade 8 SSC", grade=8, board=Board.SSC)
    batch2 = Batch(name="Grade 9 SSC", grade=9, board=Board.SSC)
    session.add_all([batch1, batch2])

    await session.flush()

    # 4. Slots on Monday
    slot1 = BatchSlot(batch_id=batch1.id, weekday=Weekday.MON, period_index=1, start_time=time(16, 0), end_time=time(17, 0))
    slot2 = BatchSlot(batch_id=batch1.id, weekday=Weekday.MON, period_index=2, start_time=time(17, 0), end_time=time(18, 0))
    slot3 = BatchSlot(batch_id=batch2.id, weekday=Weekday.MON, period_index=1, start_time=time(16, 0), end_time=time(17, 0))
    session.add_all([slot1, slot2, slot3])

    # 5. Teachers
    t_full = Teacher(
        full_name="Full Time Teacher",
        teacher_type=TeacherType.FULL_TIME,
        max_lectures_per_day=3,
        preferred_hours_start=time(16, 0),
        preferred_hours_end=time(19, 0)
    )
    t_part = Teacher(
        full_name="Part Time Teacher",
        teacher_type=TeacherType.PART_TIME,
        max_lectures_per_day=2
    )
    session.add_all([t_full, t_part])
    await session.flush()

    # Qualifications
    ts1 = TeacherSubject(teacher_id=t_full.id, subject_id=math.id, proficiency=5)
    ts2 = TeacherSubject(teacher_id=t_part.id, subject_id=eng.id, proficiency=4)
    session.add_all([ts1, ts2])

    # Standard Availability for full time teacher
    sa1 = TeacherStandardAvailability(
        teacher_id=t_full.id,
        weekday=Weekday.MON,
        window_start=time(16, 0),
        window_end=time(20, 0),
        is_active=True
    )
    session.add(sa1)

    # 6. Batch Subjects
    bs1 = BatchSubject(batch_id=batch1.id, subject_id=math.id, weekly_target=4, owner_teacher_id=t_full.id)
    bs2 = BatchSubject(batch_id=batch2.id, subject_id=eng.id, weekly_target=3, owner_teacher_id=t_part.id)
    session.add_all([bs1, bs2])

    await session.flush()

    return {
        "math": math,
        "eng": eng,
        "batch1": batch1,
        "batch2": batch2,
        "t_full": t_full,
        "t_part": t_part,
        "slot1": slot1,
        "slot2": slot2,
        "slot3": slot3,
        "bs1": bs1,
        "bs2": bs2,
    }


async def test_load_solver_input_basic(session: AsyncSession):
    """Verifies that loader properly loads batches, slots, subjects, demands and teachers availability fallback."""
    data = await setup_test_data(session)
    target_date = date(2026, 6, 1)  # Monday

    solver_input = await load_solver_input(session, target_date)

    assert solver_input.target_date == target_date
    assert solver_input.weekday == 0

    # Batches check
    batch_ids = {b.id for b in solver_input.batches}
    assert data["batch1"].id in batch_ids
    assert data["batch2"].id in batch_ids

    # Slots check
    slot_ids = {s.id for s in solver_input.slots}
    assert data["slot1"].id in slot_ids
    assert data["slot3"].id in slot_ids

    # Demands check
    assert len(solver_input.demands) == 2
    demand_math = next(d for d in solver_input.demands if d.subject_id == data["math"].id)
    assert demand_math.remaining_target == 4
    assert demand_math.owner_teacher_id == data["t_full"].id

    # Teacher check: full-time teacher should fallback to standard availability
    teacher_ids = {t.id for t in solver_input.teachers}
    assert data["t_full"].id in teacher_ids
    # part-time teacher has no availability row, so should be omitted
    assert data["t_part"].id not in teacher_ids

    t_full_in = next(t for t in solver_input.teachers if t.id == data["t_full"].id)
    assert len(t_full_in.windows) == 1
    assert t_full_in.windows[0].start == time(16, 0)
    assert t_full_in.windows[0].end == time(20, 0)


async def test_load_solver_input_availability_override(session: AsyncSession):
    """Verifies that explicit availability rows override the fallback rules."""
    data = await setup_test_data(session)
    target_date = date(2026, 6, 1)  # Monday

    # Override: make part-time teacher available all day, and full-time teacher unavailable
    ta_part = TeacherAvailability(
        teacher_id=data["t_part"].id,
        availability_date=target_date,
        status=AvailabilityStatus.AVAILABLE_ALL_DAY
    )
    ta_full = TeacherAvailability(
        teacher_id=data["t_full"].id,
        availability_date=target_date,
        status=AvailabilityStatus.UNAVAILABLE
    )
    session.add_all([ta_part, ta_full])
    await session.flush()

    solver_input = await load_solver_input(session, target_date)

    teacher_ids = {t.id for t in solver_input.teachers}
    assert data["t_part"].id in teacher_ids
    assert data["t_full"].id not in teacher_ids


async def test_load_solver_input_conducted_counts(session: AsyncSession):
    """Verifies conducted counts logic and remaining target computation."""
    data = await setup_test_data(session)
    target_date = date(2026, 6, 1)  # Monday (week start)

    # Create an archived schedule (should be ignored)
    archived_sched = Schedule(
        schedule_date=target_date,
        version=1,
        status=ScheduleStatus.ARCHIVED,
        solver_status=SolverStatus.OPTIMAL
    )
    session.add(archived_sched)
    await session.flush()

    archived_entry = ScheduleEntry(
        schedule_id=archived_sched.id,
        batch_id=data["batch1"].id,
        batch_slot_id=data["slot1"].id,
        period_index=1,
        subject_id=data["math"].id,
        status=EntryStatus.CONDUCTED,
        start_time=time(16, 0),
        end_time=time(17, 0)
    )
    session.add(archived_entry)

    # Create a draft schedule with conducted class
    draft_sched = Schedule(
        schedule_date=target_date,
        version=2,
        status=ScheduleStatus.DRAFT,
        solver_status=SolverStatus.OPTIMAL
    )
    session.add(draft_sched)
    await session.flush()

    conducted_entry = ScheduleEntry(
        schedule_id=draft_sched.id,
        batch_id=data["batch1"].id,
        batch_slot_id=data["slot1"].id,
        period_index=1,
        subject_id=data["math"].id,
        status=EntryStatus.CONDUCTED,
        start_time=time(16, 0),
        end_time=time(17, 0)
    )
    session.add(conducted_entry)
    await session.flush()

    solver_input = await load_solver_input(session, target_date)

    # remaining target should be weekly_target (4) - conducted (1) = 3
    demand_math = next(d for d in solver_input.demands if d.subject_id == data["math"].id)
    assert demand_math.remaining_target == 3


async def test_persist_solver_result(session: AsyncSession):
    """Verifies that solver result is correctly persisted and archives old schedules."""
    data = await setup_test_data(session)
    target_date = date(2026, 6, 1)

    # Pre-existing schedule
    old_sched = Schedule(
        schedule_date=target_date,
        version=1,
        status=ScheduleStatus.DRAFT,
        solver_status=SolverStatus.FEASIBLE
    )
    session.add(old_sched)
    await session.flush()

    # Define mock result
    result = SolverResult(
        target_date=target_date,
        status=CSolverStatus.OPTIMAL,
        objective_value=1500.0,
        assignments=(
            Assignment(
                batch_id=data["batch1"].id,
                slot_id=data["slot1"].id,
                subject_id=data["math"].id,
                teacher_id=data["t_full"].id,
                start=time(16, 0),
                end=time(17, 0)
            ),
        ),
        unfilled_slots=(
            UnfilledSlot(
                batch_id=data["batch2"].id,
                slot_id=data["slot3"].id,
                subject_id=data["eng"].id,
                reason="No teacher available"
            ),
        ),
        solve_time_ms=75
    )

    solver_input = await load_solver_input(session, target_date)
    snapshot = solver_input.model_dump(mode="json")

    schedule = await persist_solver_result(session, result, snapshot)

    # Check old schedule is archived
    await session.refresh(old_sched)
    assert old_sched.status == ScheduleStatus.ARCHIVED

    # Check new schedule properties
    assert schedule.schedule_date == target_date
    assert schedule.version == 2
    assert schedule.status == ScheduleStatus.DRAFT
    assert schedule.solver_status == SolverStatus.OPTIMAL
    assert schedule.objective_value == 1500.0
    assert schedule.solve_time_ms == 75
    assert schedule.num_unfilled == 1

    # Verify saved entries
    entry_stmt = select(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.id).options(selectinload(ScheduleEntry.teacher))
    entry_res = await session.execute(entry_stmt)
    entries = entry_res.scalars().all()

    assert len(entries) == 2

    assigned = next(e for e in entries if e.teacher_id is not None)
    assert assigned.batch_id == data["batch1"].id
    assert assigned.batch_slot_id == data["slot1"].id
    assert assigned.subject_id == data["math"].id
    assert assigned.teacher_id == data["t_full"].id
    assert assigned.status == EntryStatus.PLANNED

    unfilled = next(e for e in entries if e.teacher_id is None)
    assert unfilled.batch_id == data["batch2"].id
    assert unfilled.batch_slot_id == data["slot3"].id
    assert unfilled.subject_id == data["eng"].id
    assert unfilled.status == EntryStatus.PLANNED
    assert unfilled.cancelled_reason == "No teacher available"


async def test_generate_schedule(session: AsyncSession):
    """Verifies end-to-end load -> solve -> persist flow in generate_schedule."""
    data = await setup_test_data(session)
    target_date = date(2026, 6, 1)

    schedule = await generate_schedule(session, target_date)

    assert schedule.schedule_date == target_date
    assert schedule.status == ScheduleStatus.DRAFT

    # Load from DB and verify entries exist
    stmt = select(ScheduleEntry).filter(ScheduleEntry.schedule_id == schedule.id)
    res = await session.execute(stmt)
    entries = res.scalars().all()
    assert len(entries) > 0
