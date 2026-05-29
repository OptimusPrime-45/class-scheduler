from __future__ import annotations

from datetime import datetime, timezone, time
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Schedule,
    ScheduleEntry,
    ScheduleStatus,
    SolverStatus,
    EntryStatus,
)
from app.schemas import SolverResult


async def persist_solver_result(
    session: AsyncSession,
    result: SolverResult,
    solver_input_snapshot: dict
) -> Schedule:
    """Persists the SolverResult into the database.

    - Checks for any existing non-archived schedules for the date and archives them.
    - Gets the next version number (highest version + 1, default 1).
    - Creates a new Schedule in DRAFT status.
    - Saves all assignments as PLANNED schedule entries.
    - Saves all unfilled slots as PLANNED schedule entries with teacher_id = NULL and reason.
    """
    # 1. Find existing non-archived schedules for the date and archive them
    stmt = select(Schedule).filter(
        Schedule.schedule_date == result.target_date,
        Schedule.status != ScheduleStatus.ARCHIVED
    )
    res = await session.execute(stmt)
    existing_schedules = res.scalars().all()
    for s in existing_schedules:
        s.status = ScheduleStatus.ARCHIVED

    # 2. Determine next version number
    version_stmt = select(func.max(Schedule.version)).filter(
        Schedule.schedule_date == result.target_date
    )
    version_res = await session.execute(version_stmt)
    max_version = version_res.scalar()
    next_version = (max_version or 0) + 1

    # 3. Construct input_size counts for observability
    batches = solver_input_snapshot.get("batches", [])
    subjects = solver_input_snapshot.get("subjects", [])
    slots = solver_input_snapshot.get("slots", [])
    teachers = solver_input_snapshot.get("teachers", [])
    demands = solver_input_snapshot.get("demands", [])

    input_size = {
        "batches": len(batches),
        "subjects": len(subjects),
        "slots": len(slots),
        "teachers": len(teachers),
        "demands": len(demands),
    }

    # Create new Schedule
    new_schedule = Schedule(
        schedule_date=result.target_date,
        version=next_version,
        status=ScheduleStatus.DRAFT,
        solver_status=SolverStatus(result.status.value),
        objective_value=result.objective_value,
        solve_time_ms=result.solve_time_ms,
        num_unfilled=len(result.unfilled_slots),
        solver_seed=solver_input_snapshot.get("random_seed"),
        contract_version=result.contract_version,
        solver_input_snapshot=solver_input_snapshot,
        input_size=input_size,
        generated_at=datetime.now(timezone.utc)
    )
    session.add(new_schedule)
    await session.flush()  # Populates new_schedule.id

    # Create mappings of slot_id to metadata (period_index, start, end times)
    slot_period_map = {}
    slot_start_map = {}
    slot_end_map = {}

    def parse_time(t) -> time:
        if isinstance(t, time):
            return t
        if isinstance(t, str):
            parts = list(map(int, t.split(":")))
            return time(*parts)
        return time(0, 0)

    for slot in slots:
        slot_id = slot.get("id") if isinstance(slot, dict) else getattr(slot, "id", None)
        p_idx = slot.get("period_index") if isinstance(slot, dict) else getattr(slot, "period_index", 1)
        start_val = slot.get("start") if isinstance(slot, dict) else getattr(slot, "start", None)
        end_val = slot.get("end") if isinstance(slot, dict) else getattr(slot, "end", None)

        if slot_id is not None:
            slot_period_map[slot_id] = p_idx
            slot_start_map[slot_id] = parse_time(start_val)
            slot_end_map[slot_id] = parse_time(end_val)

    # 4. Save all assignments as ScheduleEntry rows
    for a in result.assignments:
        entry = ScheduleEntry(
            schedule_id=new_schedule.id,
            batch_id=a.batch_id,
            batch_slot_id=a.slot_id,
            period_index=slot_period_map.get(a.slot_id, 1),
            subject_id=a.subject_id,
            teacher_id=a.teacher_id,
            status=EntryStatus.PLANNED,
            is_locked=False,
            start_time=a.start,
            end_time=a.end,
        )
        session.add(entry)

    # 5. Save all unfilled slots as ScheduleEntry rows (teacher_id = NULL)
    for u in result.unfilled_slots:
        subject_id = u.subject_id
        if subject_id is None:
            # Fallback: attempt to find a demand for this batch to get a valid subject_id
            for d in demands:
                d_batch_id = d.get("batch_id") if isinstance(d, dict) else getattr(d, "batch_id", None)
                d_sub_id = d.get("subject_id") if isinstance(d, dict) else getattr(d, "subject_id", None)
                if d_batch_id == u.batch_id and d_sub_id is not None:
                    subject_id = d_sub_id
                    break

        if subject_id is None:
            # If no subject is configured, we cannot write a row due to the non-nullable FK constraint
            continue

        entry = ScheduleEntry(
            schedule_id=new_schedule.id,
            batch_id=u.batch_id,
            batch_slot_id=u.slot_id,
            period_index=slot_period_map.get(u.slot_id, 1),
            subject_id=subject_id,
            teacher_id=None,
            status=EntryStatus.PLANNED,
            is_locked=False,
            start_time=slot_start_map.get(u.slot_id, time(0, 0)),
            end_time=slot_end_map.get(u.slot_id, time(0, 0)),
            cancelled_reason=u.reason or "Unfilled slot",
        )
        session.add(entry)

    return new_schedule
