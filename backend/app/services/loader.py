from __future__ import annotations

from datetime import date, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    InstitutionSettings,
    SettingsScope,
    Weekday,
    ScheduleEntry,
    Schedule,
    EntryStatus,
    ScheduleStatus,
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
)
from app.schemas import (
    SolverInput,
    BatchIn,
    SubjectIn,
    SlotIn,
    TeacherIn,
    BatchSubjectDemand,
    TimeWindow,
    CBoard,
    CTeacherType,
    Assignment,
)


async def load_solver_input(session: AsyncSession, target_date: date) -> SolverInput:
    """Loads and constructs SolverInput for the given target_date from the database.

    - Finds global week_start_day.
    - Calculates week_start_date and week_days_remaining.
    - Queries conducted counts of schedule entries.
    - Queries active batches, subjects, and batch slots for target weekday.
    - Queries active available teachers for this date, resolving their availability.
    - Resolves locked assignments from existing non-archived schedules.
    """
    # 1. Fetch global institution settings
    settings_stmt = select(InstitutionSettings).filter(
        InstitutionSettings.scope == SettingsScope.GLOBAL,
        InstitutionSettings.is_active == True
    )
    settings_res = await session.execute(settings_stmt)
    settings = settings_res.scalar_one_or_none()

    if settings is not None:
        week_start_day = settings.week_start_day
        timezone = settings.timezone
        solver_time_limit_seconds = settings.solver_time_limit_seconds
    else:
        week_start_day = Weekday.MON
        timezone = "Asia/Kolkata"
        solver_time_limit_seconds = 10.0

    # 2. Calculate week boundary dates
    target_weekday = target_date.weekday()
    days_back = (target_weekday - int(week_start_day)) % 7
    week_start_date = target_date - timedelta(days=days_back)
    week_days_remaining = 7 - (target_weekday - int(week_start_day)) % 7

    # 3. Query conducted counts in the target week (from week_start_date to week_start_date + 6)
    conducted_stmt = (
        select(
            ScheduleEntry.batch_id,
            ScheduleEntry.subject_id,
            func.count(ScheduleEntry.id).label("conducted_count")
        )
        .join(Schedule, ScheduleEntry.schedule_id == Schedule.id)
        .filter(
            Schedule.schedule_date >= week_start_date,
            Schedule.schedule_date <= week_start_date + timedelta(days=6),
            Schedule.status != ScheduleStatus.ARCHIVED,
            ScheduleEntry.status == EntryStatus.CONDUCTED
        )
        .group_by(ScheduleEntry.batch_id, ScheduleEntry.subject_id)
    )
    conducted_res = await session.execute(conducted_stmt)
    conducted_counts = {
        (row.batch_id, row.subject_id): row.conducted_count
        for row in conducted_res
    }

    # 4. Query active batches, subjects, batch slots, and batch-subject links
    batches_stmt = select(Batch).filter(Batch.is_active == True)
    batches_res = await session.execute(batches_stmt)
    active_batches = batches_res.scalars().all()

    subjects_stmt = (
        select(Subject)
        .filter(Subject.is_active == True)
        .options(selectinload(Subject.preferred_windows))
    )
    subjects_res = await session.execute(subjects_stmt)
    active_subjects = subjects_res.scalars().all()

    target_weekday_enum = Weekday(target_weekday)
    slots_stmt = (
        select(BatchSlot)
        .filter(
            BatchSlot.is_active == True,
            BatchSlot.weekday == target_weekday_enum
        )
        .join(Batch)
        .filter(Batch.is_active == True)
    )
    slots_res = await session.execute(slots_stmt)
    active_slots = slots_res.scalars().all()

    batch_subjects_stmt = (
        select(BatchSubject)
        .filter(BatchSubject.is_active == True)
        .join(Batch)
        .filter(Batch.is_active == True)
        .join(Subject)
        .filter(Subject.is_active == True)
    )
    batch_subjects_res = await session.execute(batch_subjects_stmt)
    active_batch_subjects = batch_subjects_res.scalars().all()

    # 5. Query active teachers with selectinload for their availability and standard windows
    teachers_stmt = (
        select(Teacher)
        .filter(Teacher.is_active == True)
        .options(
            selectinload(Teacher.subject_links),
            selectinload(Teacher.standard_availability),
            selectinload(Teacher.availabilities).selectinload(TeacherAvailability.windows),
        )
    )
    teachers_res = await session.execute(teachers_stmt)
    active_teachers = teachers_res.scalars().all()

    # 6. Query locked assignments from any existing non-archived schedule for this date
    sched_stmt = (
        select(Schedule)
        .filter(
            Schedule.schedule_date == target_date,
            Schedule.status != ScheduleStatus.ARCHIVED
        )
        .options(selectinload(Schedule.entries))
    )
    sched_res = await session.execute(sched_stmt)
    existing_schedules = sched_res.scalars().all()

    locked_assignments = []
    for s in existing_schedules:
        for entry in s.entries:
            if entry.is_locked and entry.teacher_id is not None and entry.batch_slot_id is not None:
                locked_assignments.append(
                    Assignment(
                        batch_id=entry.batch_id,
                        slot_id=entry.batch_slot_id,
                        subject_id=entry.subject_id,
                        teacher_id=entry.teacher_id,
                        start=entry.start_time,
                        end=entry.end_time
                    )
                )

    # 7. Construct Pydantic models
    batches_in = [
        BatchIn(
            id=b.id,
            name=b.name,
            grade=b.grade,
            board=CBoard(b.board.value)
        )
        for b in active_batches
    ]

    subjects_in = []
    for s in active_subjects:
        pref_windows = []
        for w in s.preferred_windows:
            if w.weekday is None or w.weekday == target_weekday_enum:
                pref_windows.append(
                    TimeWindow(start=w.window_start, end=w.window_end)
                )
        subjects_in.append(
            SubjectIn(
                id=s.id,
                code=s.code,
                name=s.name,
                is_difficult=(s.difficulty == SubjectDifficulty.DIFFICULT),
                preferred_windows=tuple(pref_windows)
            )
        )

    slots_in = [
        SlotIn(
            id=s.id,
            batch_id=s.batch_id,
            period_index=s.period_index,
            start=s.start_time,
            end=s.end_time
        )
        for s in active_slots
    ]

    demands_in = [
        BatchSubjectDemand(
            batch_id=bs.batch_id,
            subject_id=bs.subject_id,
            remaining_target=max(0, bs.weekly_target - conducted_counts.get((bs.batch_id, bs.subject_id), 0)),
            weekly_target=bs.weekly_target,
            week_days_remaining=week_days_remaining,
            owner_teacher_id=bs.owner_teacher_id
        )
        for bs in active_batch_subjects
    ]

    teachers_in = []
    for t in active_teachers:
        ta = next((a for a in t.availabilities if a.availability_date == target_date), None)

        is_available = False
        windows = []

        if ta is not None:
            if ta.status == AvailabilityStatus.AVAILABLE_ALL_DAY:
                is_available = True
                windows = []
            elif ta.status == AvailabilityStatus.PARTIAL:
                is_available = True
                windows = [
                    TimeWindow(start=w.window_start, end=w.window_end)
                    for w in ta.windows
                ]
            elif ta.status == AvailabilityStatus.UNAVAILABLE:
                is_available = False
        else:
            # Fallback logic: full-time teachers default to standard availability
            if t.teacher_type == TeacherType.FULL_TIME:
                is_available = True
                std_avail_list = [sa for sa in t.standard_availability if sa.weekday == target_weekday_enum and sa.is_active]
                windows = [
                    TimeWindow(start=sa.window_start, end=sa.window_end)
                    for sa in std_avail_list
                ]
            else:
                # Part-time teachers default to unavailable if they have no explicit row
                is_available = False

        if is_available:
            qualified_sub_ids = {link.subject_id for link in t.subject_links}
            pref_hours = None
            if t.preferred_hours_start is not None and t.preferred_hours_end is not None:
                pref_hours = TimeWindow(start=t.preferred_hours_start, end=t.preferred_hours_end)

            teachers_in.append(
                TeacherIn(
                    id=t.id,
                    full_name=t.full_name,
                    teacher_type=CTeacherType(t.teacher_type.value),
                    max_lectures_per_day=t.max_lectures_per_day,
                    qualified_subject_ids=frozenset(qualified_sub_ids),
                    windows=tuple(windows),
                    preferred_hours=pref_hours
                )
            )

    return SolverInput(
        target_date=target_date,
        weekday=target_weekday,
        timezone=timezone,
        solver_time_limit_seconds=solver_time_limit_seconds,
        batches=tuple(batches_in),
        subjects=tuple(subjects_in),
        slots=tuple(slots_in),
        teachers=tuple(teachers_in),
        demands=tuple(demands_in),
        locked_assignments=tuple(locked_assignments)
    )
