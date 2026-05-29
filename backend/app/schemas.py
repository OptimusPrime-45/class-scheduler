"""The load-bearing solver contract: ``SolverInput`` -> ``SolverResult``.

This module has **zero SQLAlchemy imports**. Both the Phase-1 fixtures and the
Phase-2 DB loader construct identical ``SolverInput`` objects; the solver imports
only these models (README principle 2, contract-first). All models are frozen +
strict (``extra="forbid"``) so they are immutable, hashable/cacheable, and reject
drift. Both top-level models carry ``contract_version`` (principle 4 — versioned).

Time representation (``docs/data-model.md`` §3 B.0): all wall-clock values are
**naive IST** ``datetime.time``; the single solve day is ``target_date`` (IST civil
``date``). No timezone-bearing field reaches the solver — "UTC in, IST out" lives at
the edges, never in the algorithm.
"""

from __future__ import annotations

from datetime import date, time
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1"


class _Frozen(BaseModel):
    """Immutable, strict base for every contract model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- #
# Contract-local enums (decoupled from the ORM enums in models.py)            #
# --------------------------------------------------------------------------- #


class CBoard(str, Enum):
    SSC = "SSC"
    ICSE = "ICSE"


class CTeacherType(str, Enum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"


class CSolverStatus(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    MODEL_INVALID = "MODEL_INVALID"
    ERROR = "ERROR"


# --------------------------------------------------------------------------- #
# Leaf / shared models                                                         #
# --------------------------------------------------------------------------- #


class TimeWindow(_Frozen):
    """A naive-IST wall-clock interval (half-open at the edges for overlap math)."""

    start: time
    end: time

    @model_validator(mode="after")
    def _check_order(self) -> "TimeWindow":
        if self.end <= self.start:
            raise ValueError("window end must be after start")
        return self


class BatchIn(_Frozen):
    id: int
    name: str
    grade: int
    board: CBoard


class SubjectIn(_Frozen):
    id: int
    code: str
    name: str
    is_difficult: bool = False
    # subject_preferred_windows applicable to the target weekday (flattened by the loader)
    preferred_windows: tuple[TimeWindow, ...] = ()


class SlotIn(_Frozen):
    """One ``batch_slot`` active on the target weekday."""

    id: int  # == batch_slots.id — the stable slot/period identity echoed back verbatim
    batch_id: int
    period_index: int  # 1-based; used by the gap soft term
    start: time  # naive IST
    end: time


class TeacherIn(_Frozen):
    """An AVAILABLE teacher for the target date (UNAVAILABLE teachers are omitted)."""

    id: int
    full_name: str
    teacher_type: CTeacherType
    max_lectures_per_day: int
    qualified_subject_ids: frozenset[int]  # from teacher_subjects; O(1) candidate filter
    windows: tuple[TimeWindow, ...]  # resolved for the date; empty ⇒ available all day
    preferred_hours: TimeWindow | None = None  # soft preferred-hours band


class BatchSubjectDemand(_Frozen):
    """Per-(batch, subject) remaining weekly target + owner teacher."""

    batch_id: int
    subject_id: int
    remaining_target: int  # max(0, weekly_target − week-to-date CONDUCTED)
    weekly_target: int  # carried for diagnostics / near-week-end hardening
    week_days_remaining: int  # days left until the week_start_day boundary
    owner_teacher_id: int | None = None


# --------------------------------------------------------------------------- #
# Result leaf models (defined before SolverInput: locked_assignments uses them)#
# --------------------------------------------------------------------------- #


class Assignment(_Frozen):
    batch_id: int
    slot_id: int  # == SlotIn.id / batch_slots.id
    subject_id: int
    teacher_id: int
    start: time
    end: time


class UnfilledSlot(_Frozen):
    batch_id: int
    slot_id: int
    subject_id: int | None = None  # the demand we wanted to place but couldn't
    reason: str | None = None  # e.g. "no qualified+available teacher"


# --------------------------------------------------------------------------- #
# Soft-constraint weights (1:1 with the README's five soft terms + debt)       #
# --------------------------------------------------------------------------- #


class SolverWeights(_Frozen):
    fill_slot: int = 1000  # base reward for filling any slot (dominates soft terms)
    w_owner_teacher: int = 100  # prefer the subject's owner/primary teacher
    w_preferred_hours: int = 30  # honour teacher preferred hours
    w_workload_balance: int = 40  # balance lecture load across teachers
    w_avoid_gaps: int = 25  # minimise idle gaps between a batch's lectures
    w_difficult_window: int = 50  # place DIFFICULT subjects in their preferred windows
    w_remaining_target: int = 60  # debt-weighted: prefer filling higher-remaining demands


# --------------------------------------------------------------------------- #
# SolverInput — the load-bearing input                                         #
# --------------------------------------------------------------------------- #


class SolverInput(_Frozen):
    contract_version: str = CONTRACT_VERSION
    target_date: date  # the IST civil day being scheduled (UTC never enters here)
    weekday: int  # 0=Mon..6=Sun; validated == target_date.weekday()
    timezone: str = "Asia/Kolkata"  # informational; all times are already local
    solver_time_limit_seconds: float = 10.0
    random_seed: int = 42  # determinism (README Phase-1 gate)
    num_workers: int = 1  # single worker by default ⇒ reproducible CP-SAT

    batches: tuple[BatchIn, ...]
    subjects: tuple[SubjectIn, ...]
    slots: tuple[SlotIn, ...]  # only batch_slots active on the target weekday
    teachers: tuple[TeacherIn, ...]  # only AVAILABLE teachers (+ resolved windows)
    demands: tuple[BatchSubjectDemand, ...]  # per-(batch,subject) remaining target + owner
    weights: SolverWeights = Field(default_factory=SolverWeights)
    locked_assignments: tuple[Assignment, ...] = ()  # admin-pinned cells a re-solve must keep

    @model_validator(mode="after")
    def _weekday_matches(self) -> "SolverInput":
        if self.weekday != self.target_date.weekday():
            raise ValueError("weekday must equal target_date.weekday()")
        return self


# --------------------------------------------------------------------------- #
# SolverResult — the load-bearing output                                       #
# --------------------------------------------------------------------------- #


class SolverResult(_Frozen):
    contract_version: str = CONTRACT_VERSION
    target_date: date
    status: CSolverStatus
    objective_value: float | None = None  # None when INFEASIBLE / UNKNOWN / ERROR
    assignments: tuple[Assignment, ...]
    unfilled_slots: tuple[UnfilledSlot, ...]
    solve_time_ms: int | None = None
    # observability, e.g. {"num_booleans": .., "num_demands": ..}
    diagnostics: dict[str, int] = Field(default_factory=dict)
