"""SQLAlchemy 2.0 (async) ORM models — the full Tuition Scheduler schema.

Implements the canonical data model in ``docs/data-model.md``. Key conventions
(see §0 of that doc):

* ``Base`` (with the constraint-naming convention) is imported from ``app.db``.
* Timestamps that are *instants* are ``DateTime(timezone=True)`` storing **UTC**.
  Calendar days are ``Date`` (IST civil date); wall-clock times are ``Time`` (IST,
  naive). UTC never reaches the solver — "UTC in, IST out".
* Native PostgreSQL enums (one shared ``Enum`` instance per type → one ``CREATE TYPE``).
* Master data is soft-deleted via ``is_active``; FK delete policy is per §0.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# --------------------------------------------------------------------------- #
# Enums (§1)                                                                   #
# --------------------------------------------------------------------------- #


class Board(str, enum.Enum):
    SSC = "SSC"
    ICSE = "ICSE"


class Weekday(enum.IntEnum):
    """Mon=0 .. Sun=6 — aligned with Python ``date.weekday()``."""

    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6


class TeacherType(str, enum.Enum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"


class SubjectDifficulty(str, enum.Enum):
    STANDARD = "STANDARD"
    DIFFICULT = "DIFFICULT"


class AvailabilityStatus(str, enum.Enum):
    AVAILABLE_ALL_DAY = "AVAILABLE_ALL_DAY"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class AvailabilitySource(str, enum.Enum):
    TELEGRAM = "TELEGRAM"
    ADMIN = "ADMIN"
    DEFAULT = "DEFAULT"


class SettingsScope(str, enum.Enum):
    GLOBAL = "GLOBAL"
    BATCH = "BATCH"


class ScheduleStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class SolverStatus(str, enum.Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    MODEL_INVALID = "MODEL_INVALID"
    ERROR = "ERROR"


class EntryStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    CONDUCTED = "CONDUCTED"
    CANCELLED = "CANCELLED"


class NotificationKind(str, enum.Enum):
    POLL_OPEN = "POLL_OPEN"
    REMINDER = "REMINDER"
    CUTOFF_DEFAULT = "CUTOFF_DEFAULT"
    ASSIGNMENT = "ASSIGNMENT"
    NO_ASSIGNMENT = "NO_ASSIGNMENT"
    SCHEDULE_PUBLISHED = "SCHEDULE_PUBLISHED"
    ONBOARDING = "ONBOARDING"


class NotificationStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED_NO_CHAT = "SKIPPED_NO_CHAT"


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    VIEWER = "VIEWER"


# One shared Enum *instance* per type so only a single CREATE TYPE is emitted.
BOARD = SAEnum(Board, name="board")
WEEKDAY = SAEnum(Weekday, name="weekday")
TEACHER_TYPE = SAEnum(TeacherType, name="teacher_type")
SUBJECT_DIFFICULTY = SAEnum(SubjectDifficulty, name="subject_difficulty")
AVAILABILITY_STATUS = SAEnum(AvailabilityStatus, name="availability_status")
AVAILABILITY_SOURCE = SAEnum(AvailabilitySource, name="availability_source")
SETTINGS_SCOPE = SAEnum(SettingsScope, name="settings_scope")
SCHEDULE_STATUS = SAEnum(ScheduleStatus, name="schedule_status")
SOLVER_STATUS = SAEnum(SolverStatus, name="solver_status")
ENTRY_STATUS = SAEnum(EntryStatus, name="entry_status")
NOTIFICATION_KIND = SAEnum(NotificationKind, name="notification_kind")
NOTIFICATION_STATUS = SAEnum(NotificationStatus, name="notification_status")
USER_ROLE = SAEnum(UserRole, name="user_role")


# --------------------------------------------------------------------------- #
# Mixin                                                                        #
# --------------------------------------------------------------------------- #


class TimestampMixin:
    """UTC audit timestamps present on every table (§0)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------- #
# 2.1 institution_settings                                                     #
# --------------------------------------------------------------------------- #


class InstitutionSettings(TimestampMixin, Base):
    __tablename__ = "institution_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, server_default="default")
    scope: Mapped[SettingsScope] = mapped_column(
        SETTINGS_SCOPE, nullable=False, server_default=SettingsScope.GLOBAL.value
    )
    batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="CASCADE"), nullable=True
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Asia/Kolkata"
    )
    week_start_day: Mapped[Weekday] = mapped_column(
        WEEKDAY, nullable=False, server_default=Weekday.MON.name
    )
    poll_open_time: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'19:00:00'")
    )
    reminder_offsets_minutes: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, server_default=text("'{60,120}'::smallint[]")
    )
    cutoff_time: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'22:00:00'")
    )
    solve_time: Mapped[time | None] = mapped_column(
        Time, nullable=True, server_default=text("'22:15:00'")
    )
    target_offset_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1"
    )
    default_lecture_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="60"
    )
    solver_time_limit_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="10.0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    batch: Mapped["Batch | None"] = relationship(back_populates="settings_override")

    __table_args__ = (
        Index(
            "uq_institution_settings_global",
            "scope",
            unique=True,
            postgresql_where=text("scope = 'GLOBAL'"),
        ),
        Index(
            "uq_institution_settings_batch_id",
            "batch_id",
            unique=True,
            postgresql_where=text("batch_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(scope = 'GLOBAL') = (batch_id IS NULL)", name="scope_batch"
        ),
    )


# --------------------------------------------------------------------------- #
# 2.2 subjects + 2.2a subject_preferred_windows                                #
# --------------------------------------------------------------------------- #


class Subject(TimestampMixin, Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    difficulty: Mapped[SubjectDifficulty] = mapped_column(
        SUBJECT_DIFFICULTY, nullable=False, server_default=SubjectDifficulty.STANDARD.value
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), index=True
    )

    teacher_links: Mapped[list["TeacherSubject"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )
    teachers: Mapped[list["Teacher"]] = relationship(
        secondary="teacher_subjects", viewonly=True
    )
    batch_subjects: Mapped[list["BatchSubject"]] = relationship(back_populates="subject")
    preferred_windows: Mapped[list["SubjectPreferredWindow"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )


class SubjectPreferredWindow(TimestampMixin, Base):
    __tablename__ = "subject_preferred_windows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weekday: Mapped[Weekday | None] = mapped_column(WEEKDAY, nullable=True)
    window_start: Mapped[time] = mapped_column(Time, nullable=False)
    window_end: Mapped[time] = mapped_column(Time, nullable=False)

    subject: Mapped["Subject"] = relationship(back_populates="preferred_windows")

    __table_args__ = (
        CheckConstraint("window_end > window_start", name="window_order"),
    )


# --------------------------------------------------------------------------- #
# 2.3 batches                                                                  #
# --------------------------------------------------------------------------- #


class Batch(TimestampMixin, Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    grade: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    board: Mapped[Board] = mapped_column(BOARD, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), index=True
    )

    slots: Mapped[list["BatchSlot"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    batch_subjects: Mapped[list["BatchSubject"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    settings_override: Mapped["InstitutionSettings | None"] = relationship(
        back_populates="batch", uselist=False
    )
    schedule_entries: Mapped[list["ScheduleEntry"]] = relationship(back_populates="batch")

    __table_args__ = (
        CheckConstraint("grade BETWEEN 5 AND 10", name="grade_range"),
        Index("ix_batches_grade_board", "grade", "board"),
    )


# --------------------------------------------------------------------------- #
# 2.4 teachers                                                                 #
# --------------------------------------------------------------------------- #


class Teacher(TimestampMixin, Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    teacher_type: Mapped[TeacherType] = mapped_column(
        TEACHER_TYPE, nullable=False, server_default=TeacherType.PART_TIME.value, index=True
    )
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    max_lectures_per_day: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="6"
    )
    preferred_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    preferred_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    subject_links: Mapped[list["TeacherSubject"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    subjects: Mapped[list["Subject"]] = relationship(
        secondary="teacher_subjects", viewonly=True
    )
    standard_availability: Mapped[list["TeacherStandardAvailability"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    availabilities: Mapped[list["TeacherAvailability"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    owned_batch_subjects: Mapped[list["BatchSubject"]] = relationship(
        back_populates="owner_teacher", foreign_keys="BatchSubject.owner_teacher_id"
    )
    schedule_entries: Mapped[list["ScheduleEntry"]] = relationship(back_populates="teacher")
    notifications: Mapped[list["NotificationLog"]] = relationship(back_populates="teacher")

    __table_args__ = (
        CheckConstraint("max_lectures_per_day >= 0", name="max_lectures_non_negative"),
        CheckConstraint(
            "preferred_hours_end > preferred_hours_start", name="preferred_hours_order"
        ),
        Index(
            "uq_teachers_email", "email", unique=True, postgresql_where=text("email IS NOT NULL")
        ),
        Index(
            "uq_teachers_telegram_chat_id",
            "telegram_chat_id",
            unique=True,
            postgresql_where=text("telegram_chat_id IS NOT NULL"),
        ),
    )


# --------------------------------------------------------------------------- #
# 2.5 teacher_standard_availability                                            #
# --------------------------------------------------------------------------- #


class TeacherStandardAvailability(TimestampMixin, Base):
    __tablename__ = "teacher_standard_availability"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[Weekday] = mapped_column(WEEKDAY, nullable=False)
    window_start: Mapped[time] = mapped_column(Time, nullable=False)
    window_end: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    teacher: Mapped["Teacher"] = relationship(back_populates="standard_availability")

    __table_args__ = (
        CheckConstraint("window_end > window_start", name="window_order"),
        Index(
            "ix_teacher_standard_availability_teacher_id_weekday", "teacher_id", "weekday"
        ),
    )


# --------------------------------------------------------------------------- #
# 2.6 teacher_subjects (association object)                                    #
# --------------------------------------------------------------------------- #


class TeacherSubject(TimestampMixin, Base):
    __tablename__ = "teacher_subjects"

    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teachers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("subjects.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    proficiency: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="3"
    )

    teacher: Mapped["Teacher"] = relationship(back_populates="subject_links")
    subject: Mapped["Subject"] = relationship(back_populates="teacher_links")

    __table_args__ = (
        CheckConstraint("proficiency BETWEEN 1 AND 5", name="proficiency_range"),
    )


# --------------------------------------------------------------------------- #
# 2.7 batch_subjects                                                           #
# --------------------------------------------------------------------------- #


class BatchSubject(TimestampMixin, Base):
    __tablename__ = "batch_subjects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    weekly_target: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    owner_teacher_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    batch: Mapped["Batch"] = relationship(back_populates="batch_subjects")
    subject: Mapped["Subject"] = relationship(back_populates="batch_subjects")
    owner_teacher: Mapped["Teacher | None"] = relationship(
        back_populates="owned_batch_subjects", foreign_keys=[owner_teacher_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "batch_id", "subject_id", name="uq_batch_subjects_batch_id_subject_id"
        ),
        CheckConstraint("weekly_target >= 0", name="weekly_target_non_negative"),
    )


# --------------------------------------------------------------------------- #
# 2.8 batch_slots                                                              #
# --------------------------------------------------------------------------- #


class BatchSlot(TimestampMixin, Base):
    __tablename__ = "batch_slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[Weekday] = mapped_column(WEEKDAY, nullable=False)
    period_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    batch: Mapped["Batch"] = relationship(back_populates="slots")

    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "weekday",
            "period_index",
            name="uq_batch_slots_batch_id_weekday_period_index",
        ),
        CheckConstraint("period_index >= 1", name="period_index_positive"),
        CheckConstraint("end_time > start_time", name="slot_time_order"),
        Index("ix_batch_slots_batch_id_weekday", "batch_id", "weekday"),
    )


# --------------------------------------------------------------------------- #
# 2.9 teacher_availability + 2.10 availability_windows                         #
# --------------------------------------------------------------------------- #


class TeacherAvailability(TimestampMixin, Base):
    __tablename__ = "teacher_availability"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False
    )
    availability_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AvailabilityStatus] = mapped_column(AVAILABILITY_STATUS, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), index=True
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[AvailabilitySource] = mapped_column(
        AVAILABILITY_SOURCE, nullable=False, server_default=AvailabilitySource.TELEGRAM.value
    )
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    teacher: Mapped["Teacher"] = relationship(back_populates="availabilities")
    windows: Mapped[list["AvailabilityWindow"]] = relationship(
        back_populates="availability", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "availability_date",
            name="uq_teacher_availability_teacher_id_availability_date",
        ),
        Index("ix_teacher_availability_date_status", "availability_date", "status"),
    )


class AvailabilityWindow(TimestampMixin, Base):
    __tablename__ = "availability_windows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    availability_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teacher_availability.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    window_start: Mapped[time] = mapped_column(Time, nullable=False)
    window_end: Mapped[time] = mapped_column(Time, nullable=False)

    availability: Mapped["TeacherAvailability"] = relationship(back_populates="windows")

    __table_args__ = (
        CheckConstraint("window_end > window_start", name="window_order"),
    )


# --------------------------------------------------------------------------- #
# 2.11 schedules + 2.12 schedule_entries                                       #
# --------------------------------------------------------------------------- #


class Schedule(TimestampMixin, Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    schedule_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    status: Mapped[ScheduleStatus] = mapped_column(
        SCHEDULE_STATUS, nullable=False, server_default=ScheduleStatus.DRAFT.value, index=True
    )
    solver_status: Mapped[SolverStatus] = mapped_column(
        SOLVER_STATUS, nullable=False, server_default=SolverStatus.UNKNOWN.value
    )
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    solve_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_unfilled: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    solver_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_version: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="1"
    )
    solver_input_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    input_size: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    entries: Mapped[list["ScheduleEntry"]] = relationship(
        back_populates="schedule", cascade="all, delete-orphan"
    )
    approved_by: Mapped["User | None"] = relationship(
        back_populates="approved_schedules", foreign_keys=[approved_by_user_id]
    )
    published_by: Mapped["User | None"] = relationship(
        back_populates="published_schedules", foreign_keys=[published_by_user_id]
    )

    __table_args__ = (
        UniqueConstraint("schedule_date", "version", name="uq_schedules_date_version"),
    )


class ScheduleEntry(TimestampMixin, Base):
    __tablename__ = "schedule_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batches.id", ondelete="RESTRICT"), nullable=False
    )
    batch_slot_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("batch_slots.id", ondelete="SET NULL"), nullable=True
    )
    period_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    teacher_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[EntryStatus] = mapped_column(
        ENTRY_STATUS, nullable=False, server_default=EntryStatus.PLANNED.value, index=True
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    conducted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    schedule: Mapped["Schedule"] = relationship(back_populates="entries")
    batch: Mapped["Batch"] = relationship(back_populates="schedule_entries")
    subject: Mapped["Subject"] = relationship()
    teacher: Mapped["Teacher | None"] = relationship(back_populates="schedule_entries")
    batch_slot: Mapped["BatchSlot | None"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "batch_slot_id", name="uq_schedule_entries_schedule_id_batch_slot_id"
        ),
        UniqueConstraint(
            "schedule_id",
            "batch_id",
            "period_index",
            name="uq_schedule_entries_schedule_id_batch_id_period_index",
        ),
        Index("ix_schedule_entries_debt", "batch_id", "subject_id", "status"),
    )


# --------------------------------------------------------------------------- #
# 2.13 notification_log                                                        #
# --------------------------------------------------------------------------- #


class NotificationLog(TimestampMixin, Base):
    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    teacher_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    schedule_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    availability_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("teacher_availability.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[NotificationKind] = mapped_column(NOTIFICATION_KIND, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        NOTIFICATION_STATUS, nullable=False, server_default=NotificationStatus.QUEUED.value
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    teacher: Mapped["Teacher | None"] = relationship(back_populates="notifications")
    schedule: Mapped["Schedule | None"] = relationship()
    availability: Mapped["TeacherAvailability | None"] = relationship()

    __table_args__ = (
        Index("ix_notification_log_kind_status", "kind", "status"),
    )


# --------------------------------------------------------------------------- #
# 2.14 users                                                                   #
# --------------------------------------------------------------------------- #


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        USER_ROLE, nullable=False, server_default=UserRole.MANAGER.value
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    approved_schedules: Mapped[list["Schedule"]] = relationship(
        back_populates="approved_by", foreign_keys="Schedule.approved_by_user_id"
    )
    published_schedules: Mapped[list["Schedule"]] = relationship(
        back_populates="published_by", foreign_keys="Schedule.published_by_user_id"
    )
