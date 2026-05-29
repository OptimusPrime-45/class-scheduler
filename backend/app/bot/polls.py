from __future__ import annotations

import re
import logging
from datetime import date, datetime, time, timezone, timedelta
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot, Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.db import SessionLocal
from app.models import (
    AvailabilitySource,
    AvailabilityStatus,
    AvailabilityWindow,
    BatchSlot,
    Teacher,
    TeacherAvailability,
    Weekday,
)

logger = logging.getLogger(__name__)
router = Router()


def parse_date_from_message(text: str) -> date | None:
    """Helper to search and parse target date from a message text."""
    if not text:
        return None
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def extract_date(query_data: str, message_text: str) -> date:
    """Extracts date from callback query data or message text, falling back to tomorrow."""
    # 1. Try callback data (e.g. avail:all:2026-06-01)
    parts = query_data.split(":")
    if len(parts) >= 3:
        try:
            return datetime.strptime(parts[-1], "%Y-%m-%d").date()
        except ValueError:
            pass

    # 2. Try message text
    d = parse_date_from_message(message_text)
    if d:
        return d

    # 3. Fallback
    return date.today() + timedelta(days=1)


async def upsert_availability(
    session: AsyncSession,
    teacher_id: int,
    target_date: date,
    status: AvailabilityStatus,
    chat_id: int,
    windows_data: list[tuple[time, time]] | None = None,
) -> TeacherAvailability:
    """Upsert TeacherAvailability and refresh its AvailabilityWindows."""
    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher_id,
        TeacherAvailability.availability_date == target_date,
    )
    res = await session.execute(stmt)
    avail = res.scalar_one_or_none()

    if avail:
        avail.status = status
        avail.responded_at = datetime.now(timezone.utc)
        avail.source = AvailabilitySource.TELEGRAM
        avail.source_chat_id = chat_id
        # Clear existing windows
        await session.execute(
            delete(AvailabilityWindow).where(AvailabilityWindow.availability_id == avail.id)
        )
    else:
        avail = TeacherAvailability(
            teacher_id=teacher_id,
            availability_date=target_date,
            status=status,
            responded_at=datetime.now(timezone.utc),
            source=AvailabilitySource.TELEGRAM,
            source_chat_id=chat_id,
            is_default=False,
        )
        session.add(avail)
        await session.flush()

    if windows_data and status == AvailabilityStatus.PARTIAL:
        for start_t, end_t in windows_data:
            win = AvailabilityWindow(
                availability_id=avail.id,
                window_start=start_t,
                window_end=end_t,
            )
            session.add(win)

    await session.commit()
    return avail


async def send_availability_poll(
    bot: Bot, chat_id: int, target_date: date, is_reminder: bool = False
):
    """Sends availability poll with Available all day, Pick slots, and Unavailable options."""
    date_str = target_date.strftime("%Y-%m-%d")
    if is_reminder:
        text = (
            f"Reminder: you haven't submitted your availability for {date_str} yet. "
            "Please choose an option below before the cutoff."
        )
    else:
        text = f"Availability Poll for {date_str}: Please choose your availability."
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Available all day", callback_data=f"avail:all:{date_str}")],
            [InlineKeyboardButton(text="Pick slots", callback_data=f"avail:partial:{date_str}")],
            [InlineKeyboardButton(text="Unavailable", callback_data=f"avail:none:{date_str}")],
        ]
    )
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


# --- Commands & Messages ---


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Welcome command requesting contact verification."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Share Phone Number", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Welcome! Please share your contact details to verify your identity as a teacher.",
        reply_markup=keyboard,
    )


@router.message(F.contact)
async def handle_contact(message: Message):
    """Verify shared phone number and link user chat ID."""
    contact = message.contact
    if not contact:
        return

    phone = contact.phone_number.replace(" ", "").replace("-", "").lstrip("+")

    async with SessionLocal() as session:
        stmt = select(Teacher).where(Teacher.is_active == True, Teacher.phone.isnot(None))
        res = await session.execute(stmt)
        teachers = res.scalars().all()

        matched_teacher = None
        for t in teachers:
            t_phone = t.phone.replace(" ", "").replace("-", "").lstrip("+")
            if t_phone == phone:
                matched_teacher = t
                break

        if matched_teacher:
            matched_teacher.telegram_chat_id = message.chat.id
            if message.from_user and message.from_user.username:
                matched_teacher.telegram_username = message.from_user.username
            await session.commit()
            await message.answer(
                f"Thank you, {matched_teacher.full_name}! Your contact has been verified, and your account is now linked.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await message.answer(
                "Sorry, we could not find an active teacher account with that phone number. Please contact the administrator.",
                reply_markup=ReplyKeyboardRemove(),
            )


# --- Callbacks ---


@router.callback_query(F.data.startswith("avail:all"))
async def handle_avail_all(query: CallbackQuery):
    """Teacher is available all day."""
    chat_id = query.message.chat.id
    target_date = extract_date(query.data, query.message.text)

    async with SessionLocal() as session:
        stmt = select(Teacher).where(Teacher.telegram_chat_id == chat_id, Teacher.is_active == True)
        res = await session.execute(stmt)
        teacher = res.scalar_one_or_none()
        if not teacher:
            await query.answer("You are not registered as an active teacher.", show_alert=True)
            return

        await upsert_availability(
            session=session,
            teacher_id=teacher.id,
            target_date=target_date,
            status=AvailabilityStatus.AVAILABLE_ALL_DAY,
            chat_id=chat_id,
        )

    date_str = target_date.strftime("%Y-%m-%d")
    await query.message.edit_text(
        text=f"Thank you! Your availability for {date_str} has been set to: Available all day.",
        reply_markup=None,
    )
    await query.answer()


@router.callback_query(F.data.startswith("avail:none"))
async def handle_avail_none(query: CallbackQuery):
    """Teacher is unavailable."""
    chat_id = query.message.chat.id
    target_date = extract_date(query.data, query.message.text)

    async with SessionLocal() as session:
        stmt = select(Teacher).where(Teacher.telegram_chat_id == chat_id, Teacher.is_active == True)
        res = await session.execute(stmt)
        teacher = res.scalar_one_or_none()
        if not teacher:
            await query.answer("You are not registered as an active teacher.", show_alert=True)
            return

        await upsert_availability(
            session=session,
            teacher_id=teacher.id,
            target_date=target_date,
            status=AvailabilityStatus.UNAVAILABLE,
            chat_id=chat_id,
        )

    date_str = target_date.strftime("%Y-%m-%d")
    await query.message.edit_text(
        text=f"Thank you! Your availability for {date_str} has been set to: Unavailable.",
        reply_markup=None,
    )
    await query.answer()


@router.callback_query(F.data.startswith("avail:partial"))
async def handle_avail_partial(query: CallbackQuery):
    """Teacher wants to pick specific slots."""
    chat_id = query.message.chat.id
    target_date = extract_date(query.data, query.message.text)
    weekday_enum = Weekday(target_date.weekday())

    async with SessionLocal() as session:
        stmt = select(Teacher).where(Teacher.telegram_chat_id == chat_id, Teacher.is_active == True)
        res = await session.execute(stmt)
        teacher = res.scalar_one_or_none()
        if not teacher:
            await query.answer("You are not registered as an active teacher.", show_alert=True)
            return

        # Query unique slots
        stmt_slots = (
            select(BatchSlot.start_time, BatchSlot.end_time)
            .where(BatchSlot.weekday == weekday_enum, BatchSlot.is_active == True)
            .distinct()
            .order_by(BatchSlot.start_time)
        )
        res_slots = await session.execute(stmt_slots)
        slots = res_slots.all()

    if not slots:
        await query.message.edit_text(
            text=f"No active lecture slots found for {target_date.strftime('%A')} ({target_date.strftime('%Y-%m-%d')}).",
            reply_markup=None,
        )
        await query.answer()
        return

    keyboard_buttons = []
    for start_t, end_t in slots:
        time_str = f"{start_t.strftime('%H:%M')}-{end_t.strftime('%H:%M')}"
        btn_text = f"⬜ {start_t.strftime('%H:%M')} - {end_t.strftime('%H:%M')}"
        keyboard_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"slot:toggle:{time_str}")])

    keyboard_buttons.append([InlineKeyboardButton(text="Confirm", callback_data="slot:confirm")])
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    date_str = target_date.strftime("%Y-%m-%d")
    await query.message.edit_text(
        text=f"Select available slots for {date_str}:",
        reply_markup=reply_markup,
    )
    await query.answer()


@router.callback_query(F.data.startswith("slot:toggle:"))
async def handle_slot_toggle(query: CallbackQuery):
    """Toggle a slot between checked and unchecked state."""
    markup = query.message.reply_markup
    if not markup:
        await query.answer()
        return

    new_keyboard = []
    for row in markup.inline_keyboard:
        new_row = []
        for btn in row:
            if btn.callback_data == query.data:
                if btn.text.startswith("⬜"):
                    btn.text = btn.text.replace("⬜", "✅", 1)
                elif btn.text.startswith("✅"):
                    btn.text = btn.text.replace("✅", "⬜", 1)
            new_row.append(btn)
        new_keyboard.append(new_row)

    await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_keyboard))
    await query.answer()


@router.callback_query(F.data == "slot:confirm")
async def handle_slot_confirm(query: CallbackQuery):
    """Confirm checked slots and save to DB."""
    chat_id = query.message.chat.id
    target_date = extract_date("", query.message.text)

    markup = query.message.reply_markup
    if not markup:
        await query.answer()
        return

    checked_slots = []
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.text.startswith("✅") and btn.callback_data and btn.callback_data.startswith("slot:toggle:"):
                time_str = btn.callback_data[len("slot:toggle:"):]
                checked_slots.append(time_str)

    windows_data = []
    for slot_str in checked_slots:
        start_str, end_str = slot_str.split("-")
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
        windows_data.append((time(sh, sm), time(eh, em)))

    async with SessionLocal() as session:
        stmt = select(Teacher).where(Teacher.telegram_chat_id == chat_id, Teacher.is_active == True)
        res = await session.execute(stmt)
        teacher = res.scalar_one_or_none()
        if not teacher:
            await query.answer("You are not registered as an active teacher.", show_alert=True)
            return

        await upsert_availability(
            session=session,
            teacher_id=teacher.id,
            target_date=target_date,
            status=AvailabilityStatus.PARTIAL,
            chat_id=chat_id,
            windows_data=windows_data,
        )

    date_str = target_date.strftime("%Y-%m-%d")
    await query.message.edit_text(
        text=f"Thank you! Your availability for {date_str} has been updated with your selected slots.",
        reply_markup=None,
    )
    await query.answer()
