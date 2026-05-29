from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import (
    Teacher,
    TeacherAvailability,
    AvailabilityWindow,
    TeacherType,
    AvailabilityStatus,
    AvailabilitySource,
    InstitutionSettings,
    SettingsScope,
)
from app.services.scheduling import generate_schedule

logger = logging.getLogger(__name__)

# Configure the global scheduler instance
scheduler = AsyncIOScheduler()

# Job identifiers (stable so re-registration replaces rather than duplicates).
JOB_POLL_OPEN = "poll_open"
JOB_REMINDER_PREFIX = "reminder_"
JOB_CUTOFF = "cutoff"
JOB_AUTO_SOLVE = "auto_solve"

# Fallbacks used only when no global InstitutionSettings row can be read. They mirror
# the server_defaults declared on the InstitutionSettings model.
_DEFAULT_POLL_OPEN = time(19, 0)
_DEFAULT_CUTOFF = time(22, 0)
_DEFAULT_SOLVE = time(22, 15)
_DEFAULT_REMINDER_OFFSETS = [60, 120]
_DEFAULT_TARGET_OFFSET_DAYS = 1


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _add_minutes(t: time, minutes: int) -> time:
    """Add minutes to a wall-clock time, wrapping past midnight."""
    base = datetime(2000, 1, 1, t.hour, t.minute, t.second)
    return (base + timedelta(minutes=minutes)).time()


def _compute_target_date(tz_name: str, target_offset_days: int) -> date:
    """The date a job acts on: 'today' in the institution timezone plus the offset
    (typically +1, since polls run in the evening for the next day)."""
    now_local = datetime.now(ZoneInfo(tz_name))
    return now_local.date() + timedelta(days=target_offset_days)


async def _get_global_settings(session: AsyncSession) -> InstitutionSettings | None:
    stmt = select(InstitutionSettings).where(
        InstitutionSettings.scope == SettingsScope.GLOBAL
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def _load_schedule_config() -> dict:
    """Read the global scheduling windows, falling back to defaults if the row (or DB)
    is unavailable so the scheduler can always start."""
    try:
        async with SessionLocal() as session:
            s = await _get_global_settings(session)
    except Exception:
        logger.warning(
            "Could not read InstitutionSettings; using default schedule config.",
            exc_info=True,
        )
        s = None

    if s is None:
        return {
            "tz_name": app_settings.default_timezone,
            "poll_open": _DEFAULT_POLL_OPEN,
            "reminder_offsets": list(_DEFAULT_REMINDER_OFFSETS),
            "cutoff": _DEFAULT_CUTOFF,
            "solve": _DEFAULT_SOLVE,
            "target_offset_days": _DEFAULT_TARGET_OFFSET_DAYS,
        }

    return {
        "tz_name": s.timezone,
        "poll_open": s.poll_open_time,
        "reminder_offsets": list(s.reminder_offsets_minutes or []),
        "cutoff": s.cutoff_time,
        "solve": s.solve_time,
        "target_offset_days": s.target_offset_days,
    }


async def start_scheduler():
    """Starts the AsyncIO background scheduler and registers the nightly jobs."""
    global scheduler
    if not scheduler.running:
        try:
            scheduler.start()
        except RuntimeError:
            # If the scheduler has been shut down, recreate it
            scheduler = AsyncIOScheduler()
            scheduler.start()

    cfg = await _load_schedule_config()
    register_jobs(scheduler, **cfg)


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


async def run_poll_open_job(session: AsyncSession, target_date: date) -> int:
    """Sends the availability poll for ``target_date`` to every active teacher who has
    linked their Telegram account. Returns the number of polls sent."""
    # Import here to avoid a circular import at module load (app.bot imports app.db/models).
    from app.bot import bot, send_availability_poll

    stmt = select(Teacher).where(
        Teacher.is_active == True,  # noqa: E712
        Teacher.telegram_chat_id.isnot(None),
    )
    res = await session.execute(stmt)
    teachers = res.scalars().all()

    sent = 0
    for teacher in teachers:
        try:
            await send_availability_poll(bot, teacher.telegram_chat_id, target_date)
            sent += 1
        except Exception:
            logger.exception(
                "Failed to send availability poll to teacher %s (chat %s)",
                teacher.id,
                teacher.telegram_chat_id,
            )
    logger.info("Poll-open job sent %s polls for %s", sent, target_date)
    return sent


async def run_reminder_job(session: AsyncSession, target_date: date) -> int:
    """Re-sends the poll as a reminder to active, linked teachers who have NOT yet
    responded for ``target_date``. Returns the number of reminders sent."""
    from app.bot import bot, send_availability_poll

    # Teachers who already have any availability row for the date are considered responded.
    responded_stmt = select(TeacherAvailability.teacher_id).where(
        TeacherAvailability.availability_date == target_date
    )
    responded_res = await session.execute(responded_stmt)
    responded_ids = set(responded_res.scalars().all())

    stmt = select(Teacher).where(
        Teacher.is_active == True,  # noqa: E712
        Teacher.telegram_chat_id.isnot(None),
    )
    res = await session.execute(stmt)
    teachers = res.scalars().all()

    sent = 0
    for teacher in teachers:
        if teacher.id in responded_ids:
            continue
        try:
            await send_availability_poll(
                bot, teacher.telegram_chat_id, target_date, is_reminder=True
            )
            sent += 1
        except Exception:
            logger.exception(
                "Failed to send reminder to teacher %s (chat %s)",
                teacher.id,
                teacher.telegram_chat_id,
            )
    logger.info("Reminder job sent %s reminders for %s", sent, target_date)
    return sent


# --------------------------------------------------------------------------- #
# Cron wrappers — own their session + compute the target date at fire time     #
# --------------------------------------------------------------------------- #


async def _run_poll_open_cron(tz_name: str, target_offset_days: int):
    target_date = _compute_target_date(tz_name, target_offset_days)
    async with SessionLocal() as session:
        await run_poll_open_job(session, target_date)


async def _run_reminder_cron(tz_name: str, target_offset_days: int):
    target_date = _compute_target_date(tz_name, target_offset_days)
    async with SessionLocal() as session:
        await run_reminder_job(session, target_date)


async def _run_cutoff_cron(tz_name: str, target_offset_days: int):
    target_date = _compute_target_date(tz_name, target_offset_days)
    async with SessionLocal() as session:
        # run_cutoff_job opens its own transaction (session.begin) which commits on exit.
        await run_cutoff_job(session, target_date)


async def _run_auto_solve_cron(tz_name: str, target_offset_days: int):
    target_date = _compute_target_date(tz_name, target_offset_days)
    async with SessionLocal() as session:
        # generate_schedule opens its own transaction which commits on exit.
        await run_auto_solve_job(session, target_date)


# --------------------------------------------------------------------------- #
# Job registration                                                            #
# --------------------------------------------------------------------------- #


def register_jobs(
    sched: AsyncIOScheduler,
    *,
    tz_name: str,
    poll_open: time,
    reminder_offsets: list[int],
    cutoff: time,
    solve: time | None,
    target_offset_days: int,
) -> None:
    """(Re)register the nightly cron jobs on ``sched`` using the given windows.

    Times are interpreted in ``tz_name`` (the institution timezone). Re-registration
    replaces existing jobs by id, so calling this repeatedly is safe (idempotent).
    Reminders fire at ``poll_open + offset`` for each configured offset; the reminder
    job itself only messages teachers who have not yet responded.
    """
    tz = ZoneInfo(tz_name)
    kwargs = {"tz_name": tz_name, "target_offset_days": target_offset_days}

    sched.add_job(
        _run_poll_open_cron,
        CronTrigger(hour=poll_open.hour, minute=poll_open.minute, timezone=tz),
        id=JOB_POLL_OPEN,
        replace_existing=True,
        kwargs=kwargs,
    )

    # Clear any stale reminder jobs from a previous (longer) offsets list.
    for job in sched.get_jobs():
        if job.id.startswith(JOB_REMINDER_PREFIX):
            sched.remove_job(job.id)

    for i, offset in enumerate(reminder_offsets):
        rt = _add_minutes(poll_open, offset)
        sched.add_job(
            _run_reminder_cron,
            CronTrigger(hour=rt.hour, minute=rt.minute, timezone=tz),
            id=f"{JOB_REMINDER_PREFIX}{i}",
            replace_existing=True,
            kwargs=kwargs,
        )

    sched.add_job(
        _run_cutoff_cron,
        CronTrigger(hour=cutoff.hour, minute=cutoff.minute, timezone=tz),
        id=JOB_CUTOFF,
        replace_existing=True,
        kwargs=kwargs,
    )

    if solve is not None:
        sched.add_job(
            _run_auto_solve_cron,
            CronTrigger(hour=solve.hour, minute=solve.minute, timezone=tz),
            id=JOB_AUTO_SOLVE,
            replace_existing=True,
            kwargs=kwargs,
        )
    elif sched.get_job(JOB_AUTO_SOLVE) is not None:
        # No solve time configured anymore — drop a previously registered auto-solve job.
        sched.remove_job(JOB_AUTO_SOLVE)

    logger.info(
        "Registered scheduler jobs (tz=%s): poll_open=%s, reminders=%s, cutoff=%s, solve=%s",
        tz_name,
        poll_open.strftime("%H:%M"),
        reminder_offsets,
        cutoff.strftime("%H:%M"),
        solve.strftime("%H:%M") if solve else None,
    )
