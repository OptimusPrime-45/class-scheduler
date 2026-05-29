from __future__ import annotations

import pytest
from datetime import date, time, datetime, timezone
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.main import app
from app.db import Base, engine, get_session
from app.models import (
    Teacher,
    Batch,
    Subject,
    TeacherAvailability,
    AvailabilityWindow,
    Schedule,
    ScheduleEntry,
    TeacherStandardAvailability,
    TeacherSubject,
    BatchSlot,
    BatchSubject,
    SettingsScope,
    InstitutionSettings,
    Weekday,
    TeacherType,
    Board,
    SubjectDifficulty,
    AvailabilityStatus,
    AvailabilitySource,
    ScheduleStatus,
    SolverStatus,
    EntryStatus
)

# --------------------------------------------------------------------------- #
# Transactional DB Fixtures                                                  #
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


# Helper to setup minimal data for schedule generation tests
async def setup_test_data(session: AsyncSession):
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
    }


# --------------------------------------------------------------------------- #
# CRUD Endpoints Tests                                                       #
# --------------------------------------------------------------------------- #

async def test_teacher_crud(db_client: AsyncClient, session: AsyncSession):
    # 1. Create Teacher
    payload = {
        "full_name": "Test Teacher",
        "phone": "+919876543210",
        "email": "teacher@test.com",
        "teacher_type": "FULL_TIME",
        "max_lectures_per_day": 4,
        "preferred_hours_start": "09:00:00",
        "preferred_hours_end": "17:00:00",
        "notes": "Some test notes"
    }
    resp = await db_client.post("/api/teachers", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["full_name"] == "Test Teacher"
    assert body["teacher_type"] == "FULL_TIME"
    assert body["is_active"] is True
    teacher_id = body["id"]

    # 2. Get Teacher
    resp = await db_client.get(f"/api/teachers/{teacher_id}")
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Test Teacher"

    # 3. Delete Teacher
    resp = await db_client.delete(f"/api/teachers/{teacher_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await db_client.get(f"/api/teachers/{teacher_id}")
    assert resp.status_code == 404


async def test_batch_crud(db_client: AsyncClient, session: AsyncSession):
    # 1. Create Batch
    payload = {
        "name": "Class 10 ICSE",
        "grade": 10,
        "board": "ICSE"
    }
    resp = await db_client.post("/api/batches", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Class 10 ICSE"
    assert body["grade"] == 10
    assert body["board"] == "ICSE"
    batch_id = body["id"]

    # 2. Get Batch
    resp = await db_client.get(f"/api/batches/{batch_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Class 10 ICSE"

    # 3. Delete Batch
    resp = await db_client.delete(f"/api/batches/{batch_id}")
    assert resp.status_code == 204


async def test_subject_crud(db_client: AsyncClient, session: AsyncSession):
    # 1. Create Subject
    payload = {
        "name": "History & Civics",
        "code": "HIST",
        "difficulty": "STANDARD"
    }
    resp = await db_client.post("/api/subjects", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "History & Civics"
    assert body["code"] == "HIST"
    assert body["difficulty"] == "STANDARD"
    subject_id = body["id"]

    # 2. Get Subject
    resp = await db_client.get(f"/api/subjects/{subject_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "History & Civics"

    # 3. Delete Subject
    resp = await db_client.delete(f"/api/subjects/{subject_id}")
    assert resp.status_code == 204


# --------------------------------------------------------------------------- #
# Availability Endpoints Tests                                               #
# --------------------------------------------------------------------------- #

async def test_upsert_availability(db_client: AsyncClient, session: AsyncSession):
    # Create a teacher
    teacher = Teacher(
        full_name="Availability Teacher",
        teacher_type=TeacherType.PART_TIME,
        max_lectures_per_day=3
    )
    session.add(teacher)
    await session.flush()

    # 1. Upsert AVAILABLE_ALL_DAY
    payload = {
        "teacher_id": teacher.id,
        "availability_date": "2026-06-01",
        "status": "AVAILABLE_ALL_DAY",
        "windows": [],
        "notes": "Available all day notes"
    }
    resp = await db_client.post("/api/availability", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "AVAILABLE_ALL_DAY"
    assert body["is_default"] is False
    assert len(body["windows"]) == 0

    # 2. Upsert PARTIAL availability with windows
    payload = {
        "teacher_id": teacher.id,
        "availability_date": "2026-06-01",
        "status": "PARTIAL",
        "windows": [
            {"start": "09:00:00", "end": "12:00:00"},
            {"start": "14:00:00", "end": "17:00:00"}
        ],
        "notes": "Partial availability windows"
    }
    resp = await db_client.post("/api/availability", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PARTIAL"
    assert len(body["windows"]) == 2
    # Verify window format
    assert body["windows"][0]["window_start"] == "09:00:00"
    assert body["windows"][1]["window_end"] == "17:00:00"

    # 3. Change status to UNAVAILABLE (should clear windows)
    payload = {
        "teacher_id": teacher.id,
        "availability_date": "2026-06-01",
        "status": "UNAVAILABLE",
        "windows": [],
    }
    resp = await db_client.post("/api/availability", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UNAVAILABLE"
    assert len(body["windows"]) == 0

    # 4. Get availability by date
    resp = await db_client.get("/api/availability/date/2026-06-01")
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) == 1
    assert records[0]["teacher_id"] == teacher.id
    assert records[0]["status"] == "UNAVAILABLE"


# --------------------------------------------------------------------------- #
# Schedule Endpoints Tests                                                   #
# --------------------------------------------------------------------------- #

async def test_schedule_generation_and_actions(db_client: AsyncClient, session: AsyncSession):
    data = await setup_test_data(session)

    # Mock teacher availability for part time teacher so they can be scheduled
    ta_part = TeacherAvailability(
        teacher_id=data["t_part"].id,
        availability_date=date(2026, 6, 1),
        status=AvailabilityStatus.AVAILABLE_ALL_DAY
    )
    session.add(ta_part)
    await session.flush()

    # 1. POST /api/schedules/generate
    resp = await db_client.post("/api/schedules/generate?target_date=2026-06-01")
    assert resp.status_code == 201
    body = resp.json()
    assert body["schedule_date"] == "2026-06-01"
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    schedule_id = body["id"]
    assert len(body["entries"]) > 0

    # 2. GET /api/schedules/{schedule_id}
    resp = await db_client.get(f"/api/schedules/{schedule_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == schedule_id
    assert len(body["entries"]) > 0

    # 3. GET /api/schedules/date/{date}
    resp = await db_client.get("/api/schedules/date/2026-06-01")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == schedule_id
    assert body["status"] == "DRAFT"

    # 4. POST /api/schedules/{schedule_id}/approve
    resp = await db_client.post(f"/api/schedules/{schedule_id}/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "APPROVED"
    assert body["approved_at"] is not None

    # 5. POST /api/schedules/{schedule_id}/publish
    resp = await db_client.post(f"/api/schedules/{schedule_id}/publish")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PUBLISHED"
    assert body["published_at"] is not None
