from __future__ import annotations

import pytest
from datetime import date, time, datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message

from app.main import app
from app.db import Base, engine, get_session
from app.config import settings
from app.models import (
    Teacher,
    Batch,
    BatchSlot,
    TeacherAvailability,
    AvailabilityWindow,
    Schedule,
    ScheduleEntry,
    NotificationLog,
    Weekday,
    TeacherType,
    AvailabilityStatus,
    AvailabilitySource,
    NotificationStatus,
    NotificationKind,
    EntryStatus,
    Board,
    Subject,
    SubjectDifficulty,
)
from app.bot.notify import send_schedule_notifications

# --------------------------------------------------------------------------- #
# Transactional DB Fixtures                                                  #
# --------------------------------------------------------------------------- #


@pytest.fixture
async def session():
    """Provides a transactional database session that rolls back after each test."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
            await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def db_client(session: AsyncSession) -> AsyncClient:
    """An HTTP client that uses the transactional test database session."""
    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_bot_session(monkeypatch):
    """Mocks the aiogram bot session to prevent actual Telegram API requests."""
    from app.bot import bot
    mock_session = AsyncMock()

    async def side_effect(bot, method, timeout=None):
        chat_id = getattr(method, "chat_id", 12345)
        # Default return value is a dummy Telegram Message
        return Message(
            message_id=999,
            date=datetime.now(timezone.utc),
            chat=Chat(id=chat_id, type="private"),
            text="Mocked Response",
        )

    mock_session.side_effect = side_effect
    monkeypatch.setattr(bot, "session", mock_session)
    return mock_session


@pytest.fixture(autouse=True)
def mock_session_local(monkeypatch, session):
    """Overrides SessionLocal in app.bot.polls to use the transactional test session."""
    class MockSessionLocal:
        def __init__(self):
            self.session = session
        async def __aenter__(self):
            return self.session
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("app.bot.polls.SessionLocal", MockSessionLocal)


# --------------------------------------------------------------------------- #
# Bot Tests                                                                   #
# --------------------------------------------------------------------------- #


async def test_webhook_secret_validation(db_client: AsyncClient, monkeypatch):
    """Verify that requests to the webhook are authorized with the secret token."""
    monkeypatch.setattr(settings, "telegram_webhook_secret", "secret_token_123")

    # 1. Request with missing or wrong secret
    resp = await db_client.post(
        "/api/bot/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert resp.status_code == 403

    # 2. Request with correct secret (empty update)
    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 1716960000,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "text": "/start",
            },
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret_token_123"},
    )
    assert resp.status_code == 200


async def test_start_command(db_client: AsyncClient):
    """Test start command triggers welcome message and requests contact."""
    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 1,
            "message": {
                "message_id": 100,
                "date": 1716960000,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "text": "/start",
            },
        },
    )
    assert resp.status_code == 200

    from app.bot import bot
    calls = bot.session.call_args_list
    assert len(calls) > 0
    method = calls[0][0][1]
    assert method.__class__.__name__ == "SendMessage"
    assert "verify your identity" in method.text
    assert method.reply_markup.keyboard[0][0].request_contact is True


async def test_contact_handler_success(db_client: AsyncClient, session: AsyncSession):
    """Test contact sharing updates the chat ID for a matching active teacher."""
    teacher = Teacher(
        full_name="Active Teacher",
        phone="+919876543210",
        is_active=True,
        teacher_type=TeacherType.FULL_TIME,
    )
    session.add(teacher)
    await session.commit()

    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 2,
            "message": {
                "message_id": 101,
                "date": 1716960000,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "contact": {
                    "phone_number": "919876543210",
                    "first_name": "Active",
                },
            },
        },
    )
    assert resp.status_code == 200

    # Verify database update
    await session.refresh(teacher)
    assert teacher.telegram_chat_id == 12345

    # Verify success response
    from app.bot import bot
    calls = bot.session.call_args_list
    method = calls[-1][0][1]
    assert method.__class__.__name__ == "SendMessage"
    assert "Your contact has been verified" in method.text


async def test_contact_handler_not_found(db_client: AsyncClient, session: AsyncSession):
    """Test contact sharing when no matching active teacher exists."""
    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 3,
            "message": {
                "message_id": 102,
                "date": 1716960000,
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "contact": {
                    "phone_number": "+919999999999",
                    "first_name": "Unknown",
                },
            },
        },
    )
    assert resp.status_code == 200

    from app.bot import bot
    calls = bot.session.call_args_list
    method = calls[-1][0][1]
    assert method.__class__.__name__ == "SendMessage"
    assert "could not find an active teacher account" in method.text


async def test_avail_all_callback(db_client: AsyncClient, session: AsyncSession):
    """Test Available all day callback updates availability state to AVAILABLE_ALL_DAY."""
    teacher = Teacher(
        full_name="Active Teacher",
        phone="+919876543210",
        is_active=True,
        telegram_chat_id=12345,
    )
    session.add(teacher)
    await session.commit()

    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 4,
            "callback_query": {
                "id": "q1",
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "chat_instance": "inst",
                "data": "avail:all:2026-06-01",
                "message": {
                    "message_id": 200,
                    "date": 1716960000,
                    "chat": {"id": 12345, "type": "private"},
                    "text": "Availability Poll for 2026-06-01",
                },
            },
        },
    )
    assert resp.status_code == 200

    # Verify DB state
    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher.id,
        TeacherAvailability.availability_date == date(2026, 6, 1),
    )
    res = await session.execute(stmt)
    avail = res.scalar_one()
    assert avail.status == AvailabilityStatus.AVAILABLE_ALL_DAY
    assert avail.responded_at is not None

    # Verify edit_message_text callback call
    from app.bot import bot
    calls = bot.session.call_args_list
    method = calls[-2][0][1]
    assert method.__class__.__name__ == "EditMessageText"
    assert "Available all day" in method.text


async def test_avail_none_callback(db_client: AsyncClient, session: AsyncSession):
    """Test Unavailable callback updates availability state to UNAVAILABLE."""
    teacher = Teacher(
        full_name="Active Teacher",
        phone="+919876543210",
        is_active=True,
        telegram_chat_id=12345,
    )
    session.add(teacher)
    await session.commit()

    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 5,
            "callback_query": {
                "id": "q2",
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "chat_instance": "inst",
                "data": "avail:none:2026-06-01",
                "message": {
                    "message_id": 200,
                    "date": 1716960000,
                    "chat": {"id": 12345, "type": "private"},
                    "text": "Availability Poll for 2026-06-01",
                },
            },
        },
    )
    assert resp.status_code == 200

    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher.id,
        TeacherAvailability.availability_date == date(2026, 6, 1),
    )
    res = await session.execute(stmt)
    avail = res.scalar_one()
    assert avail.status == AvailabilityStatus.UNAVAILABLE

    from app.bot import bot
    calls = bot.session.call_args_list
    method = calls[-2][0][1]
    assert method.__class__.__name__ == "EditMessageText"
    assert "Unavailable" in method.text


async def test_avail_partial_callback(db_client: AsyncClient, session: AsyncSession):
    """Test Pick slots callback queries slot times and shows toggles."""
    teacher = Teacher(
        full_name="Active Teacher",
        phone="+919876543210",
        is_active=True,
        telegram_chat_id=12345,
    )
    session.add(teacher)
    await session.flush()

    # Create Batch first
    batch = Batch(name="Grade 8 SSC", grade=8, board=Board.SSC)
    session.add(batch)
    await session.flush()

    # Create BatchSlot on Monday (2026-06-01 is Monday)
    slot1 = BatchSlot(
        batch_id=batch.id,
        weekday=Weekday.MON,
        period_index=1,
        start_time=time(16, 0),
        end_time=time(17, 0),
        is_active=True,
    )
    slot2 = BatchSlot(
        batch_id=batch.id,
        weekday=Weekday.MON,
        period_index=2,
        start_time=time(17, 0),
        end_time=time(18, 0),
        is_active=True,
    )
    session.add_all([slot1, slot2])
    await session.commit()

    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 6,
            "callback_query": {
                "id": "q3",
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "chat_instance": "inst",
                "data": "avail:partial:2026-06-01",
                "message": {
                    "message_id": 200,
                    "date": 1716960000,
                    "chat": {"id": 12345, "type": "private"},
                    "text": "Availability Poll for 2026-06-01",
                },
            },
        },
    )
    assert resp.status_code == 200

    from app.bot import bot
    calls = bot.session.call_args_list
    method = calls[-2][0][1]
    assert method.__class__.__name__ == "EditMessageText"
    assert "Select available slots" in method.text
    # 2 slot buttons + 1 Confirm button
    assert len(method.reply_markup.inline_keyboard) == 3
    assert "⬜ 16:00 - 17:00" in method.reply_markup.inline_keyboard[0][0].text
    assert "⬜ 17:00 - 18:00" in method.reply_markup.inline_keyboard[1][0].text
    assert method.reply_markup.inline_keyboard[2][0].text == "Confirm"


async def test_slot_toggle_handler(db_client: AsyncClient):
    """Test slot toggle switches state from unchecked (⬜) to checked (✅) and back."""
    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 7,
            "callback_query": {
                "id": "q4",
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "chat_instance": "inst",
                "data": "slot:toggle:16:00-17:00",
                "message": {
                    "message_id": 200,
                    "date": 1716960000,
                    "chat": {"id": 12345, "type": "private"},
                    "text": "Select available slots for 2026-06-01:",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "⬜ 16:00 - 17:00", "callback_data": "slot:toggle:16:00-17:00"}],
                            [{"text": "Confirm", "callback_data": "slot:confirm"}],
                        ]
                    },
                },
            },
        },
    )
    assert resp.status_code == 200

    from app.bot import bot
    calls = bot.session.call_args_list
    method = calls[-2][0][1]
    assert method.__class__.__name__ == "EditMessageReplyMarkup"
    assert "✅ 16:00 - 17:00" in method.reply_markup.inline_keyboard[0][0].text


async def test_slot_confirm_handler(db_client: AsyncClient, session: AsyncSession):
    """Test slot confirm processes checked slots and upserts PARTIAL availability with windows."""
    teacher = Teacher(
        full_name="Active Teacher",
        phone="+919876543210",
        is_active=True,
        telegram_chat_id=12345,
    )
    session.add(teacher)
    await session.commit()

    resp = await db_client.post(
        "/api/bot/webhook",
        json={
            "update_id": 8,
            "callback_query": {
                "id": "q5",
                "from": {"id": 12345, "is_bot": False, "first_name": "Teacher"},
                "chat_instance": "inst",
                "data": "slot:confirm",
                "message": {
                    "message_id": 200,
                    "date": 1716960000,
                    "chat": {"id": 12345, "type": "private"},
                    "text": "Select available slots for 2026-06-01:",
                    "reply_markup": {
                        "inline_keyboard": [
                            [{"text": "✅ 16:00 - 17:00", "callback_data": "slot:toggle:16:00-17:00"}],
                            [{"text": "⬜ 17:00 - 18:00", "callback_data": "slot:toggle:17:00-18:00"}],
                            [{"text": "Confirm", "callback_data": "slot:confirm"}],
                        ]
                    },
                },
            },
        },
    )
    assert resp.status_code == 200

    # Verify DB updates
    stmt = select(TeacherAvailability).where(
        TeacherAvailability.teacher_id == teacher.id,
        TeacherAvailability.availability_date == date(2026, 6, 1),
    )
    res = await session.execute(stmt)
    avail = res.scalar_one()
    assert avail.status == AvailabilityStatus.PARTIAL

    # Verify availability window
    stmt_win = select(AvailabilityWindow).where(AvailabilityWindow.availability_id == avail.id)
    res_win = await session.execute(stmt_win)
    windows = res_win.scalars().all()
    assert len(windows) == 1
    assert windows[0].window_start == time(16, 0)
    assert windows[0].window_end == time(17, 0)

    from app.bot import bot
    calls = bot.session.call_args_list
    method = calls[-2][0][1]
    assert method.__class__.__name__ == "EditMessageText"
    assert "updated with your selected slots" in method.text


# --------------------------------------------------------------------------- #
# Notification Service Tests                                                 #
# --------------------------------------------------------------------------- #


async def test_notify_success(session: AsyncSession):
    """Test send_schedule_notifications with normal flows: assignments, unassigned, skipped, and logging."""
    # 1. Setup Teachers
    t_assigned = Teacher(
        full_name="Assigned Teacher", phone="+911111111111", telegram_chat_id=50001, is_active=True
    )
    t_unassigned = Teacher(
        full_name="Unassigned Teacher", phone="+912222222222", telegram_chat_id=50002, is_active=True
    )
    t_no_chat = Teacher(
        full_name="No Chat Teacher", phone="+913333333333", telegram_chat_id=None, is_active=True
    )
    session.add_all([t_assigned, t_unassigned, t_no_chat])
    await session.flush()

    # 2. Setup Subject and Batch
    math = Subject(name="Mathematics", code="MATH", difficulty=SubjectDifficulty.DIFFICULT)
    batch = Batch(name="Grade 8 SSC", grade=8, board=Board.SSC)
    session.add_all([math, batch])
    await session.flush()

    # 3. Setup Schedule and Entry
    schedule = Schedule(schedule_date=date(2026, 6, 1))
    session.add(schedule)
    await session.flush()

    entry = ScheduleEntry(
        schedule_id=schedule.id,
        batch_id=batch.id,
        period_index=1,
        subject_id=math.id,
        teacher_id=t_assigned.id,
        status=EntryStatus.PLANNED,
        start_time=time(16, 0),
        end_time=time(17, 0),
    )
    session.add(entry)
    await session.commit()

    # 4. Mock Bot Session
    from app.bot import bot
    bot.session.reset_mock()

    # 5. Run notifications
    await send_schedule_notifications(session, schedule)

    # Verify Messages Sent
    calls = bot.session.call_args_list
    assert len(calls) == 2

    # Check messages contents
    dest_chats = {call[0][1].chat_id: call[0][1].text for call in calls}
    assert 50001 in dest_chats
    assert "Your schedule for 2026-06-01:" in dest_chats[50001]
    assert "- 16:00 - 17:00: Grade 8 SSC (Mathematics)" in dest_chats[50001]

    assert 50002 in dest_chats
    assert dest_chats[50002] == "No class scheduled for tomorrow"

    # Verify Notification Logs
    stmt = select(NotificationLog).order_by(NotificationLog.teacher_id)
    res = await session.execute(stmt)
    logs = res.scalars().all()
    assert len(logs) == 3

    # Log 1: t_assigned
    log_assigned = next(l for l in logs if l.teacher_id == t_assigned.id)
    assert log_assigned.status == NotificationStatus.SENT
    assert log_assigned.kind == NotificationKind.ASSIGNMENT
    assert log_assigned.telegram_message_id == 999

    # Log 2: t_unassigned
    log_unassigned = next(l for l in logs if l.teacher_id == t_unassigned.id)
    assert log_unassigned.status == NotificationStatus.SENT
    assert log_unassigned.kind == NotificationKind.NO_ASSIGNMENT
    assert log_unassigned.telegram_message_id == 999

    # Log 3: t_no_chat
    log_no_chat = next(l for l in logs if l.teacher_id == t_no_chat.id)
    assert log_no_chat.status == NotificationStatus.SKIPPED_NO_CHAT
    assert log_no_chat.telegram_chat_id is None


async def test_notify_duplicate(session: AsyncSession):
    """Verify send_schedule_notifications is deduplicated using dedupe_key."""
    t_assigned = Teacher(
        full_name="Assigned Teacher", phone="+911111111111", telegram_chat_id=50001, is_active=True
    )
    session.add(t_assigned)
    await session.flush()
    schedule = Schedule(schedule_date=date(2026, 6, 1))
    session.add(schedule)
    await session.commit()

    from app.bot import bot
    bot.session.reset_mock()

    # First send
    await send_schedule_notifications(session, schedule)
    assert len(bot.session.call_args_list) == 1

    # Second send -> should bypass sending message to Telegram
    bot.session.reset_mock()
    await send_schedule_notifications(session, schedule)
    assert len(bot.session.call_args_list) == 0


async def test_notify_api_failure(session: AsyncSession):
    """Verify Telegram API exceptions are caught and logged as FAILED."""
    t_assigned = Teacher(
        full_name="Assigned Teacher", phone="+911111111111", telegram_chat_id=50001, is_active=True
    )
    session.add(t_assigned)
    await session.flush()
    schedule = Schedule(schedule_date=date(2026, 6, 1))
    session.add(schedule)
    await session.commit()

    from app.bot import bot
    # Setup mock session to raise exception
    err = TelegramForbiddenError(
        method=SendMessage(chat_id=50001, text="test"), message="Forbidden: bot blocked by user"
    )
    bot.session.side_effect = err

    await send_schedule_notifications(session, schedule)

    # Verify logged status is FAILED with error detail
    stmt = select(NotificationLog).where(NotificationLog.teacher_id == t_assigned.id)
    res = await session.execute(stmt)
    log = res.scalar_one()
    assert log.status == NotificationStatus.FAILED
    assert "Forbidden" in log.error_detail
