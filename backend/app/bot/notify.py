from __future__ import annotations

import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aiogram.exceptions import TelegramAPIError

from app.bot.webhook import bot
from app.models import (
    EntryStatus,
    NotificationKind,
    NotificationLog,
    NotificationStatus,
    Schedule,
    ScheduleEntry,
    Teacher,
)

logger = logging.getLogger(__name__)


async def send_schedule_notifications(session: AsyncSession, schedule: Schedule):
    """Sends class assignment notifications to all active teachers for the given schedule."""
    # 1. Fetch active teachers
    stmt_teachers = select(Teacher).where(Teacher.is_active == True)
    res_teachers = await session.execute(stmt_teachers)
    teachers = res_teachers.scalars().all()

    # 2. Fetch schedule entries with preloaded batch and subject
    stmt_entries = (
        select(ScheduleEntry)
        .where(
            ScheduleEntry.schedule_id == schedule.id,
            ScheduleEntry.status != EntryStatus.CANCELLED,
        )
        .options(
            selectinload(ScheduleEntry.batch),
            selectinload(ScheduleEntry.subject),
        )
    )
    res_entries = await session.execute(stmt_entries)
    entries = res_entries.scalars().all()

    # 3. Group entries by teacher
    entries_by_teacher = {}
    for entry in entries:
        if entry.teacher_id is not None:
            entries_by_teacher.setdefault(entry.teacher_id, []).append(entry)

    # Sort entries for each teacher chronologically by start_time
    for t_id in entries_by_teacher:
        entries_by_teacher[t_id].sort(key=lambda e: e.start_time)

    # 4. Notify each active teacher
    for teacher in teachers:
        # Check dedupe key first to avoid sending duplicates
        dedupe_key = f"sched:{schedule.id}:teacher:{teacher.id}:assignment"

        # Check if already processed
        stmt_check = select(NotificationLog).where(NotificationLog.dedupe_key == dedupe_key)
        res_check = await session.execute(stmt_check)
        if res_check.scalar_one_or_none() is not None:
            logger.info(
                f"Notification for schedule {schedule.id} and teacher {teacher.id} already exists (deduplicated)."
            )
            continue

        teacher_entries = entries_by_teacher.get(teacher.id, [])
        has_assignments = len(teacher_entries) > 0

        # Construct message content
        if has_assignments:
            lines = [f"Your schedule for {schedule.schedule_date}:"]
            for entry in teacher_entries:
                start_str = entry.start_time.strftime("%H:%M")
                end_str = entry.end_time.strftime("%H:%M")
                batch_name = entry.batch.name if entry.batch else "Unknown Batch"
                subj_name = entry.subject.name if entry.subject else "Unknown Subject"
                lines.append(f"- {start_str} - {end_str}: {batch_name} ({subj_name})")
            message_text = "\n".join(lines)
            kind = NotificationKind.ASSIGNMENT
        else:
            message_text = "No class scheduled for tomorrow"
            kind = NotificationKind.NO_ASSIGNMENT

        # If teacher doesn't have a chat ID, log and skip
        if not teacher.telegram_chat_id:
            log = NotificationLog(
                teacher_id=teacher.id,
                schedule_id=schedule.id,
                kind=kind,
                status=NotificationStatus.SKIPPED_NO_CHAT,
                target_date=schedule.schedule_date,
                telegram_chat_id=None,
                dedupe_key=dedupe_key,
                sent_at=None,
                attempt=1,
            )
            session.add(log)
            await session.commit()
            continue

        # Try sending the message via Telegram
        try:
            msg = await bot.send_message(chat_id=teacher.telegram_chat_id, text=message_text)
            log = NotificationLog(
                teacher_id=teacher.id,
                schedule_id=schedule.id,
                kind=kind,
                status=NotificationStatus.SENT,
                target_date=schedule.schedule_date,
                telegram_chat_id=teacher.telegram_chat_id,
                telegram_message_id=msg.message_id,
                dedupe_key=dedupe_key,
                sent_at=datetime.now(timezone.utc),
                attempt=1,
            )
            session.add(log)
            await session.commit()
        except TelegramAPIError as e:
            logger.warning(
                f"Telegram API error sending to teacher {teacher.id} (chat_id {teacher.telegram_chat_id}): {e}"
            )
            log = NotificationLog(
                teacher_id=teacher.id,
                schedule_id=schedule.id,
                kind=kind,
                status=NotificationStatus.FAILED,
                target_date=schedule.schedule_date,
                telegram_chat_id=teacher.telegram_chat_id,
                error_detail=str(e),
                dedupe_key=dedupe_key,
                sent_at=None,
                attempt=1,
            )
            session.add(log)
            await session.commit()
        except Exception as e:
            logger.exception(f"Unexpected error sending notification to teacher {teacher.id}")
            log = NotificationLog(
                teacher_id=teacher.id,
                schedule_id=schedule.id,
                kind=kind,
                status=NotificationStatus.FAILED,
                target_date=schedule.schedule_date,
                telegram_chat_id=teacher.telegram_chat_id,
                error_detail=str(e),
                dedupe_key=dedupe_key,
                sent_at=None,
                attempt=1,
            )
            session.add(log)
            await session.commit()
