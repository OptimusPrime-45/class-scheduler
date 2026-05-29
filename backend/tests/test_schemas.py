"""Contract tests for the load-bearing SolverInput / SolverResult models."""

from __future__ import annotations

from datetime import date, time

import pytest
from pydantic import ValidationError

from app.schemas import (
    CONTRACT_VERSION,
    Assignment,
    BatchIn,
    BatchSubjectDemand,
    CBoard,
    CSolverStatus,
    CTeacherType,
    SlotIn,
    SolverInput,
    SolverResult,
    SolverWeights,
    SubjectIn,
    TeacherIn,
    TimeWindow,
)


def _minimal_input(**overrides) -> SolverInput:
    base = dict(
        target_date=date(2026, 6, 1),  # a Monday
        weekday=0,
        batches=(BatchIn(id=1, name="Grade 8 ICSE", grade=8, board=CBoard.ICSE),),
        subjects=(SubjectIn(id=1, code="MATH", name="Mathematics", is_difficult=True),),
        slots=(SlotIn(id=1, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),),
        teachers=(
            TeacherIn(
                id=1,
                full_name="Anita",
                teacher_type=CTeacherType.FULL_TIME,
                max_lectures_per_day=6,
                qualified_subject_ids=frozenset({1}),
                windows=(),
            ),
        ),
        demands=(
            BatchSubjectDemand(
                batch_id=1, subject_id=1, remaining_target=3, weekly_target=5, week_days_remaining=4
            ),
        ),
    )
    base.update(overrides)
    return SolverInput(**base)


def test_solver_input_builds_and_defaults():
    si = _minimal_input()
    assert si.contract_version == CONTRACT_VERSION
    assert si.weights.fill_slot == 1000
    assert si.num_workers == 1  # deterministic default
    assert si.random_seed == 42


def test_weekday_must_match_target_date():
    # 2026-06-01 is a Monday (weekday 0); claiming Tuesday must fail.
    with pytest.raises(ValidationError):
        _minimal_input(weekday=1)


def test_timewindow_rejects_non_positive_span():
    with pytest.raises(ValidationError):
        TimeWindow(start=time(18, 0), end=time(18, 0))
    with pytest.raises(ValidationError):
        TimeWindow(start=time(19, 0), end=time(18, 0))


def test_models_are_frozen_and_strict():
    si = _minimal_input()
    with pytest.raises(ValidationError):
        si.target_date = date(2026, 6, 2)  # frozen
    with pytest.raises(ValidationError):
        BatchIn(id=1, name="x", grade=8, board=CBoard.ICSE, bogus=1)  # extra="forbid"


def test_solver_input_is_hashable_and_cacheable():
    a = _minimal_input()
    b = _minimal_input()
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1  # usable as a cache key


def test_solver_result_partition_shape():
    r = SolverResult(
        target_date=date(2026, 6, 1),
        status=CSolverStatus.OPTIMAL,
        objective_value=1234.0,
        assignments=(
            Assignment(
                batch_id=1, slot_id=1, subject_id=1, teacher_id=1, start=time(16, 0), end=time(17, 0)
            ),
        ),
        unfilled_slots=(),
    )
    assert r.contract_version == CONTRACT_VERSION
    assert r.status is CSolverStatus.OPTIMAL
    assert len(r.assignments) == 1


def test_infeasible_result_allows_null_objective():
    r = SolverResult(
        target_date=date(2026, 6, 1),
        status=CSolverStatus.INFEASIBLE,
        assignments=(),
        unfilled_slots=(),
    )
    assert r.objective_value is None


def test_weights_defaults_are_separated_by_magnitude():
    w = SolverWeights()
    # fill_slot must dominate any single soft term so terms can be tested in isolation.
    softs = [w.w_owner_teacher, w.w_preferred_hours, w.w_workload_balance,
             w.w_avoid_gaps, w.w_difficult_window, w.w_remaining_target]
    assert w.fill_slot > sum(softs)
