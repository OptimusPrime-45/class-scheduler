"""Deterministic mock-data seeder for development.

Two layers (so determinism is testable without a DB):
* ``build_seed_data()`` — a **pure** function returning a plain, JSON-serialisable
  spec (natural-key references only). Identical on every call, every machine.
* ``seed(session)`` — turns that spec into ORM rows in dependency order.

``python seed.py`` truncates every business table (``RESTART IDENTITY``) and re-inserts,
so the database lands in the *same known state* — including identical surrogate ids —
every run (README Phase-0 DoD).

Dataset: 1 institution-settings row, 8 subjects, 6 batches (grades 5–10, SSC/ICSE),
20 teachers (6 full-time / 14 part-time) with qualifications, weekly targets, and the
evening slot grid (Mon–Sat × 4 periods per batch).
"""

from __future__ import annotations

import asyncio
from datetime import time

from sqlalchemy import text

from app.db import Base, SessionLocal, engine
from app.models import (
    AvailabilitySource,
    Batch,
    BatchSlot,
    BatchSubject,
    Board,
    InstitutionSettings,
    SettingsScope,
    Subject,
    SubjectDifficulty,
    SubjectPreferredWindow,
    Teacher,
    TeacherStandardAvailability,
    TeacherSubject,
    TeacherType,
    Weekday,
)

# --------------------------------------------------------------------------- #
# Fixed source lists (no randomness — the dataset is fully determined by these)#
# --------------------------------------------------------------------------- #

# (code, name, difficulty)
SUBJECTS: list[tuple[str, str, SubjectDifficulty]] = [
    ("MATH", "Mathematics", SubjectDifficulty.DIFFICULT),
    ("SCI", "Science", SubjectDifficulty.DIFFICULT),
    ("ENG", "English", SubjectDifficulty.STANDARD),
    ("HIN", "Hindi", SubjectDifficulty.STANDARD),
    ("MAR", "Marathi", SubjectDifficulty.STANDARD),
    ("SST", "Social Studies", SubjectDifficulty.STANDARD),
    ("COMP", "Computer Science", SubjectDifficulty.STANDARD),
    ("SANS", "Sanskrit", SubjectDifficulty.STANDARD),
]

# (name, grade, board)
BATCHES: list[tuple[str, int, Board]] = [
    ("Grade 5 SSC", 5, Board.SSC),
    ("Grade 6 ICSE", 6, Board.ICSE),
    ("Grade 7 SSC", 7, Board.SSC),
    ("Grade 8 ICSE", 8, Board.ICSE),
    ("Grade 9 SSC", 9, Board.SSC),
    ("Grade 10 ICSE", 10, Board.ICSE),
]

TEACHER_NAMES: list[str] = [
    "Anita Deshmukh", "Bhavesh Kulkarni", "Chitra Iyer", "Deepak Joshi",
    "Esha Nair", "Farhan Shaikh", "Gauri Patil", "Harish Rao",
    "Isha Verma", "Jatin Mehta", "Kavya Reddy", "Lakshmi Menon",
    "Manish Gupta", "Neha Bhosale", "Omkar Sawant", "Priya Chauhan",
    "Rahul Pawar", "Sneha Kamath", "Tarun Bansal", "Usha Pillai",
]

# Curriculum every batch follows: (subject_code, weekly_target)
CURRICULUM: list[tuple[str, int]] = [
    ("MATH", 5),
    ("SCI", 4),
    ("ENG", 4),
    ("SST", 3),
    ("HIN", 3),
    ("COMP", 2),
]

# Evening period grid (period_index, start, end), applied Mon–Sat to every batch.
PERIODS: list[tuple[int, time, time]] = [
    (1, time(16, 0), time(17, 0)),
    (2, time(17, 0), time(18, 0)),
    (3, time(18, 0), time(19, 0)),
    (4, time(19, 0), time(20, 0)),
]

TEACHING_WEEKDAYS: list[Weekday] = [
    Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI, Weekday.SAT,
]

NUM_FULL_TIME = 6  # first six teachers are full-time


def _qualified_subject_codes(i: int) -> list[str]:
    """Deterministic 3-subject qualification per teacher (offsets 0,3,5 → distinct)."""
    n = len(SUBJECTS)
    return [SUBJECTS[(i + off) % n][0] for off in (0, 3, 5)]


def _iso(t: time) -> str:
    return t.strftime("%H:%M")


def build_seed_data() -> dict:
    """Pure, deterministic dataset spec. No DB, no randomness, no clock."""
    subjects = [
        {
            "code": code,
            "name": name,
            "difficulty": difficulty.value,
            # difficult subjects prefer the fresher early-evening band
            "preferred_windows": (
                [{"weekday": None, "start": _iso(time(16, 0)), "end": _iso(time(18, 30))}]
                if difficulty is SubjectDifficulty.DIFFICULT
                else []
            ),
        }
        for code, name, difficulty in SUBJECTS
    ]

    batches = [{"name": name, "grade": grade, "board": board.value} for name, grade, board in BATCHES]

    teachers = []
    for i, full_name in enumerate(TEACHER_NAMES):
        is_full = i < NUM_FULL_TIME
        # preferred-hours band cycles in 3s; every third teacher has none
        pref = {0: (time(16, 0), time(19, 0)), 1: (time(17, 0), time(20, 0))}.get(i % 3)
        teachers.append(
            {
                "full_name": full_name,
                "email": f"teacher{i:02d}@example.com",
                "phone": f"+91-90000000{i:02d}",
                "teacher_type": (TeacherType.FULL_TIME if is_full else TeacherType.PART_TIME).value,
                # last three teachers are intentionally not-yet-onboarded (no chat id)
                "telegram_chat_id": None if i >= len(TEACHER_NAMES) - 3 else 500_000_000 + i,
                "max_lectures_per_day": 6 if is_full else (4 if i % 2 else 3),
                "preferred_hours": (
                    {"start": _iso(pref[0]), "end": _iso(pref[1])} if pref else None
                ),
                "qualifications": _qualified_subject_codes(i),
                # full-timers carry a recurring weekly availability template
                "standard_availability": (
                    [
                        {"weekday": int(wd), "start": _iso(time(16, 0)), "end": _iso(time(20, 0))}
                        for wd in TEACHING_WEEKDAYS
                    ]
                    if is_full
                    else []
                ),
            }
        )

    # owner of a (batch, subject) = the lowest-index teacher qualified for that subject
    def first_qualified(code: str) -> str:
        for i, name in enumerate(TEACHER_NAMES):
            if code in _qualified_subject_codes(i):
                return name
        raise AssertionError(f"no teacher qualified for {code}")  # coverage guard

    batch_subjects = [
        {
            "batch_name": b["name"],
            "subject_code": code,
            "weekly_target": target,
            "owner_teacher_name": first_qualified(code),
        }
        for b in batches
        for code, target in CURRICULUM
    ]

    batch_slots = [
        {
            "batch_name": b["name"],
            "weekday": int(wd),
            "period_index": p_idx,
            "start": _iso(start),
            "end": _iso(end),
        }
        for b in batches
        for wd in TEACHING_WEEKDAYS
        for p_idx, start, end in PERIODS
    ]

    settings = {
        "name": "default",
        "scope": SettingsScope.GLOBAL.value,
        "timezone": "Asia/Kolkata",
        "week_start_day": int(Weekday.MON),
        "poll_open_time": _iso(time(19, 0)),
        "reminder_offsets_minutes": [60, 120],
        "cutoff_time": _iso(time(22, 0)),
        "solve_time": _iso(time(22, 15)),
        "target_offset_days": 1,
    }

    return {
        "settings": settings,
        "subjects": subjects,
        "batches": batches,
        "teachers": teachers,
        "batch_subjects": batch_subjects,
        "batch_slots": batch_slots,
    }


def _parse_time(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


async def _truncate_all(session) -> None:
    """Reset every business table + sequences so ids are identical each run."""
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


async def seed(session) -> dict:
    """Insert the deterministic dataset. Returns row counts for reporting/tests."""
    data = build_seed_data()
    await _truncate_all(session)

    # Subjects (+ preferred windows)
    subjects_by_code: dict[str, Subject] = {}
    for s in data["subjects"]:
        subj = Subject(
            code=s["code"],
            name=s["name"],
            difficulty=SubjectDifficulty(s["difficulty"]),
            preferred_windows=[
                SubjectPreferredWindow(
                    weekday=None if w["weekday"] is None else Weekday(w["weekday"]),
                    window_start=_parse_time(w["start"]),
                    window_end=_parse_time(w["end"]),
                )
                for w in s["preferred_windows"]
            ],
        )
        subjects_by_code[s["code"]] = subj
        session.add(subj)

    # Teachers (+ qualifications + standard availability)
    teachers_by_name: dict[str, Teacher] = {}
    for t in data["teachers"]:
        pref = t["preferred_hours"]
        teacher = Teacher(
            full_name=t["full_name"],
            email=t["email"],
            phone=t["phone"],
            teacher_type=TeacherType(t["teacher_type"]),
            telegram_chat_id=t["telegram_chat_id"],
            max_lectures_per_day=t["max_lectures_per_day"],
            preferred_hours_start=_parse_time(pref["start"]) if pref else None,
            preferred_hours_end=_parse_time(pref["end"]) if pref else None,
            subject_links=[
                TeacherSubject(subject=subjects_by_code[code]) for code in t["qualifications"]
            ],
            standard_availability=[
                TeacherStandardAvailability(
                    weekday=Weekday(a["weekday"]),
                    window_start=_parse_time(a["start"]),
                    window_end=_parse_time(a["end"]),
                )
                for a in t["standard_availability"]
            ],
        )
        teachers_by_name[t["full_name"]] = teacher
        session.add(teacher)

    # Batches
    batches_by_name: dict[str, Batch] = {}
    for b in data["batches"]:
        batch = Batch(name=b["name"], grade=b["grade"], board=Board(b["board"]))
        batches_by_name[b["name"]] = batch
        session.add(batch)

    # Batch subjects (weekly target + owner teacher)
    for bs in data["batch_subjects"]:
        session.add(
            BatchSubject(
                batch=batches_by_name[bs["batch_name"]],
                subject=subjects_by_code[bs["subject_code"]],
                weekly_target=bs["weekly_target"],
                owner_teacher=teachers_by_name[bs["owner_teacher_name"]],
            )
        )

    # Batch slots (the period grid)
    for sl in data["batch_slots"]:
        session.add(
            BatchSlot(
                batch=batches_by_name[sl["batch_name"]],
                weekday=Weekday(sl["weekday"]),
                period_index=sl["period_index"],
                start_time=_parse_time(sl["start"]),
                end_time=_parse_time(sl["end"]),
            )
        )

    # Institution settings (one GLOBAL row)
    st = data["settings"]
    session.add(
        InstitutionSettings(
            name=st["name"],
            scope=SettingsScope(st["scope"]),
            timezone=st["timezone"],
            week_start_day=Weekday(st["week_start_day"]),
            poll_open_time=_parse_time(st["poll_open_time"]),
            reminder_offsets_minutes=st["reminder_offsets_minutes"],
            cutoff_time=_parse_time(st["cutoff_time"]),
            solve_time=_parse_time(st["solve_time"]),
            target_offset_days=st["target_offset_days"],
        )
    )

    await session.commit()

    return {
        "settings": 1,
        "subjects": len(data["subjects"]),
        "batches": len(data["batches"]),
        "teachers": len(data["teachers"]),
        "qualifications": sum(len(t["qualifications"]) for t in data["teachers"]),
        "batch_subjects": len(data["batch_subjects"]),
        "batch_slots": len(data["batch_slots"]),
        "standard_availability": sum(len(t["standard_availability"]) for t in data["teachers"]),
    }


async def main() -> None:
    async with SessionLocal() as session:
        counts = await seed(session)
    await engine.dispose()
    print("Seeded deterministic dataset:")
    for k, v in counts.items():
        print(f"  {k:>22}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
