"""Comprehensive test suite for the class scheduler CP-SAT solver."""

from datetime import date, time
import pytest

from app.schemas import (
    Assignment,
    BatchIn,
    BatchSubjectDemand,
    CBoard,
    CSolverStatus,
    CTeacherType,
    SlotIn,
    SolverInput,
    SolverWeights,
    SubjectIn,
    TeacherIn,
    TimeWindow,
)
from app.scheduler.solver import solve
from app.scheduler.validator import validate


def _create_base_input(
    batches=None,
    subjects=None,
    slots=None,
    teachers=None,
    demands=None,
    weights=None,
    locked_assignments=(),
) -> SolverInput:
    """Helper to construct SolverInput for tests."""
    if batches is None:
        batches = (BatchIn(id=1, name="Grade 8 SSC", grade=8, board=CBoard.SSC),)
    if subjects is None:
        subjects = (SubjectIn(id=10, code="MATH", name="Mathematics"),)
    if slots is None:
        slots = (
            SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        )
    if teachers is None:
        teachers = (
            TeacherIn(
                id=200,
                full_name="Teacher A",
                teacher_type=CTeacherType.FULL_TIME,
                max_lectures_per_day=1,
                qualified_subject_ids=frozenset({10}),
                windows=(),
            ),
        )
    if demands is None:
        demands = (
            BatchSubjectDemand(
                batch_id=1,
                subject_id=10,
                remaining_target=1,
                weekly_target=1,
                week_days_remaining=5,
                owner_teacher_id=None,
            ),
        )
    if weights is None:
        weights = SolverWeights()

    return SolverInput(
        target_date=date(2026, 6, 1),  # Monday
        weekday=0,
        batches=tuple(batches),
        subjects=tuple(subjects),
        slots=tuple(slots),
        teachers=tuple(teachers),
        demands=tuple(demands),
        weights=weights,
        locked_assignments=tuple(locked_assignments),
    )


def test_solver_basic_feasibility():
    """Asserts that a simple, satisfiable input produces an OPTIMAL/FEASIBLE solution."""
    input_data = _create_base_input()
    result = solve(input_data)

    assert result.status in (CSolverStatus.OPTIMAL, CSolverStatus.FEASIBLE)
    assert len(result.assignments) == 1
    assert len(result.unfilled_slots) == 0

    # Validator parity
    val_res = validate(input_data, result.assignments)
    assert val_res.is_valid is True


def test_hard_constraint_teacher_qualification():
    """Asserts that teachers are not scheduled for unqualified subjects."""
    # Teacher qualified only for Science (11), but demand is for Math (10)
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({11}),  # Unqualified for Math (10)
            windows=(),
        ),
    )
    input_data = _create_base_input(teachers=teachers)
    result = solve(input_data)

    assert len(result.assignments) == 0
    assert len(result.unfilled_slots) == 1
    assert result.unfilled_slots[0].reason == "no qualified teacher available"
    assert result.unfilled_slots[0].subject_id == 10


def test_hard_constraint_teacher_availability():
    """Asserts that teacher availability windows are respected."""
    # Teacher available 17:00-18:00, but slot is 16:00-17:00
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10}),
            windows=(TimeWindow(start=time(17, 0), end=time(18, 0)),),
        ),
    )
    input_data = _create_base_input(teachers=teachers)
    result = solve(input_data)

    assert len(result.assignments) == 0
    assert len(result.unfilled_slots) == 1
    assert result.unfilled_slots[0].reason == "no qualified teacher available at slot time"


def test_hard_constraint_teacher_double_booking():
    """Asserts that a teacher is never booked for two overlapping slots."""
    # Two batches with overlapping slots, only one teacher qualified for both
    batches = (
        BatchIn(id=1, name="Grade 8", grade=8, board=CBoard.SSC),
        BatchIn(id=2, name="Grade 9", grade=9, board=CBoard.SSC),
    )
    slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        SlotIn(id=101, batch_id=2, period_index=1, start=time(16, 0), end=time(17, 0)),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=1,
            weekly_target=1,
            week_days_remaining=5,
        ),
        BatchSubjectDemand(
            batch_id=2,
            subject_id=10,
            remaining_target=1,
            weekly_target=1,
            week_days_remaining=5,
        ),
    )
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=2,  # Set to 2 so they have capacity, isolating the double-booking constraint
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
    )
    input_data = _create_base_input(
        batches=batches, slots=slots, teachers=teachers, demands=demands
    )
    result = solve(input_data)

    # At most 1 assignment can be made because there's only 1 teacher
    assert len(result.assignments) <= 1
    assert len(result.assignments) + len(result.unfilled_slots) == 2

    # Check validator parity on assignments
    val_res = validate(input_data, result.assignments)
    assert val_res.is_valid is True

    # If 1 is unfilled, check the reason is double-booking or similar
    if len(result.unfilled_slots) == 1:
        assert "double-booked" in result.unfilled_slots[0].reason


def test_hard_constraint_max_lectures():
    """Asserts that max lectures per day is respected for teachers."""
    # Two slots, but teacher max lectures is 1
    slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(17, 0), end=time(18, 0)),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=2,
            weekly_target=2,
            week_days_remaining=5,
        ),
    )
    input_data = _create_base_input(slots=slots, demands=demands)
    result = solve(input_data)

    assert len(result.assignments) <= 1
    val_res = validate(input_data, result.assignments)
    assert val_res.is_valid is True

    if len(result.unfilled_slots) == 1:
        assert "max lectures limit" in result.unfilled_slots[0].reason


def test_hard_constraint_batch_overlap():
    """Asserts that overlapping slots for the same batch are not both scheduled."""
    # Two overlapping slots for batch 1, two teachers available
    slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(16, 30), end=time(17, 30)),
    )
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
        TeacherIn(
            id=201,
            full_name="Teacher B",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=2,
            weekly_target=2,
            week_days_remaining=5,
        ),
    )
    input_data = _create_base_input(slots=slots, teachers=teachers, demands=demands)
    result = solve(input_data)

    assert len(result.assignments) <= 1
    val_res = validate(input_data, result.assignments)
    assert val_res.is_valid is True


def test_locked_assignments():
    """Asserts that locked assignments are forced in the solver output."""
    # Locked assignment uses Teacher B (201)
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
        TeacherIn(
            id=201,
            full_name="Teacher B",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
    )
    locked = [
        Assignment(
            batch_id=1,
            slot_id=100,
            subject_id=10,
            teacher_id=201,
            start=time(16, 0),
            end=time(17, 0),
        )
    ]
    input_data = _create_base_input(teachers=teachers, locked_assignments=locked)
    result = solve(input_data)

    assert result.status in (CSolverStatus.OPTIMAL, CSolverStatus.FEASIBLE)
    assert len(result.assignments) == 1
    assert result.assignments[0].teacher_id == 201
    val_res = validate(input_data, result.assignments)
    assert val_res.is_valid is True


def test_infeasibility_handling():
    """Asserts that model infeasibility is correctly handled when constraints are impossible."""
    # Locked assignments that double-book the same teacher at the same time
    slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(16, 0), end=time(17, 0)),
    )
    locked = [
        Assignment(
            batch_id=1,
            slot_id=100,
            subject_id=10,
            teacher_id=200,
            start=time(16, 0),
            end=time(17, 0),
        ),
        Assignment(
            batch_id=1,
            slot_id=101,
            subject_id=10,
            teacher_id=200,
            start=time(16, 0),
            end=time(17, 0),
        ),
    ]
    input_data = _create_base_input(slots=slots, locked_assignments=locked)
    result = solve(input_data)

    assert result.status == CSolverStatus.INFEASIBLE
    assert result.objective_value is None
    assert len(result.assignments) == 0
    assert len(result.unfilled_slots) == 2


def test_opt_owner_teacher():
    """Asserts that owner teacher is preferred when weights are set in isolation."""
    # Two teachers available. Teacher A (200) is the owner. Teacher B (201) is not.
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
        TeacherIn(
            id=201,
            full_name="Teacher B",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=1,
            weekly_target=1,
            week_days_remaining=5,
            owner_teacher_id=200,  # Teacher A is the owner
        ),
    )
    weights = SolverWeights(
        fill_slot=1000,
        w_owner_teacher=500,
        w_preferred_hours=0,
        w_workload_balance=0,
        w_avoid_gaps=0,
        w_difficult_window=0,
        w_remaining_target=0,
    )
    input_data = _create_base_input(
        teachers=teachers, demands=demands, weights=weights
    )
    result = solve(input_data)

    assert len(result.assignments) == 1
    assert result.assignments[0].teacher_id == 200


def test_opt_preferred_hours():
    """Asserts that slots within a teacher's preferred hours are chosen."""
    # Two slots. Teacher available for both, but preferred hours covers only slot 101.
    slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(17, 0), end=time(18, 0)),
    )
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,  # Can only take 1 slot
            qualified_subject_ids=frozenset({10}),
            windows=(),
            preferred_hours=TimeWindow(start=time(17, 0), end=time(18, 0)),
        ),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=1,  # Target is only 1
            weekly_target=1,
            week_days_remaining=5,
        ),
    )
    weights = SolverWeights(
        fill_slot=1000,
        w_owner_teacher=0,
        w_preferred_hours=500,
        w_workload_balance=0,
        w_avoid_gaps=0,
        w_difficult_window=0,
        w_remaining_target=0,
    )
    input_data = _create_base_input(
        slots=slots, teachers=teachers, demands=demands, weights=weights
    )
    result = solve(input_data)

    assert len(result.assignments) == 1
    assert result.assignments[0].slot_id == 101


def test_opt_workload_balance():
    """Asserts that workload is balanced across available teachers when enabled."""
    # 4 non-overlapping slots. Two teachers. Both qualified.
    # If workload balance is active, both should get 2 lectures instead of one getting 3 and other 1.
    slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(13, 0), end=time(14, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(14, 0), end=time(15, 0)),
        SlotIn(id=102, batch_id=1, period_index=3, start=time(15, 0), end=time(16, 0)),
        SlotIn(id=103, batch_id=1, period_index=4, start=time(16, 0), end=time(17, 0)),
    )
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=3,
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
        TeacherIn(
            id=201,
            full_name="Teacher B",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=3,
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=4,
            weekly_target=4,
            week_days_remaining=5,
        ),
    )
    weights = SolverWeights(
        fill_slot=1000,
        w_owner_teacher=0,
        w_preferred_hours=0,
        w_workload_balance=100,  # Balance load
        w_avoid_gaps=0,
        w_difficult_window=0,
        w_remaining_target=0,
    )
    input_data = _create_base_input(
        slots=slots, teachers=teachers, demands=demands, weights=weights
    )
    result = solve(input_data)

    assert len(result.assignments) == 4
    # Calculate loads
    loads = {200: 0, 201: 0}
    for a in result.assignments:
        loads[a.teacher_id] += 1

    assert loads[200] == 2
    assert loads[201] == 2


def test_opt_avoid_gaps():
    """Asserts that gaps in a batch's slots are avoided when scheduling lectures."""
    # 3 consecutive slots. Target = 2.
    # Solver should schedule Slot 100 & 101 or Slot 101 & 102. Avoid Slot 100 & 102.
    slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(14, 0), end=time(15, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(15, 0), end=time(16, 0)),
        SlotIn(id=102, batch_id=1, period_index=3, start=time(16, 0), end=time(17, 0)),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=2,
            weekly_target=2,
            week_days_remaining=5,
        ),
    )
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=2,  # Set to 2 to limit total slots scheduled to target of 2
            qualified_subject_ids=frozenset({10}),
            windows=(),
        ),
    )
    weights = SolverWeights(
        fill_slot=1000,
        w_owner_teacher=0,
        w_preferred_hours=0,
        w_workload_balance=0,
        w_avoid_gaps=500,  # Avoid gaps
        w_difficult_window=0,
        w_remaining_target=0,
    )
    input_data = _create_base_input(
        slots=slots, teachers=teachers, demands=demands, weights=weights
    )
    result = solve(input_data)

    assert len(result.assignments) == 2
    assigned_slots = {a.slot_id for a in result.assignments}

    # Should not be {100, 102} (which leaves a gap at 101)
    assert assigned_slots != {100, 102}
    assert assigned_slots in ({100, 101}, {101, 102})


def test_opt_difficult_subject_preferred_window():
    """Asserts that difficult subjects are placed in their preferred windows."""
    # Subject 10 is difficult, has preferred window at 17:00-18:00
    subjects = (
        SubjectIn(
            id=10,
            code="MATH",
            name="Mathematics",
            is_difficult=True,
            preferred_windows=(TimeWindow(start=time(17, 0), end=time(18, 0)),),
        ),
    )
    slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(17, 0), end=time(18, 0)),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=1,
            weekly_target=1,
            week_days_remaining=5,
        ),
    )
    weights = SolverWeights(
        fill_slot=1000,
        w_owner_teacher=0,
        w_preferred_hours=0,
        w_workload_balance=0,
        w_avoid_gaps=0,
        w_difficult_window=500,
        w_remaining_target=0,
    )
    input_data = _create_base_input(
        subjects=subjects, slots=slots, demands=demands, weights=weights
    )
    result = solve(input_data)

    assert len(result.assignments) == 1
    assert result.assignments[0].slot_id == 101


def test_opt_target_debt():
    """Asserts that demands with higher remaining targets (higher debt) are prioritized."""
    # 1 slot, 2 demands. Demand A (Math) has remaining target = 3. Demand B (Science) has remaining target = 1.
    # Solver should select Math.
    subjects = (
        SubjectIn(id=10, code="MATH", name="Mathematics"),
        SubjectIn(id=11, code="SCI", name="Science"),
    )
    demands = (
        BatchSubjectDemand(
            batch_id=1,
            subject_id=10,
            remaining_target=3,  # Higher debt
            weekly_target=3,
            week_days_remaining=5,
        ),
        BatchSubjectDemand(
            batch_id=1,
            subject_id=11,
            remaining_target=1,
            weekly_target=1,
            week_days_remaining=5,
        ),
    )
    teachers = (
        TeacherIn(
            id=200,
            full_name="Teacher A",
            teacher_type=CTeacherType.FULL_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10, 11}),
            windows=(),
        ),
    )
    weights = SolverWeights(
        fill_slot=1000,
        w_owner_teacher=0,
        w_preferred_hours=0,
        w_workload_balance=0,
        w_avoid_gaps=0,
        w_difficult_window=0,
        w_remaining_target=100,  # Prioritize higher remaining target
    )
    input_data = _create_base_input(
        subjects=subjects, demands=demands, teachers=teachers, weights=weights
    )
    result = solve(input_data)

    assert len(result.assignments) == 1
    assert result.assignments[0].subject_id == 10  # MATH selected


def test_solver_determinism():
    """Asserts that the solver produces identical outputs when run with the same seed and single worker."""
    input_data = _create_base_input()

    res1 = solve(input_data)
    res2 = solve(input_data)
    res3 = solve(input_data)

    assert res1.assignments == res2.assignments
    assert res1.assignments == res3.assignments


def test_solver_performance():
    """Asserts that a realistic problem instance is solved in under 2.0 seconds."""
    # Let's generate a realistic problem size:
    # 6 batches, 8 subjects, 20 teachers, 4 slots per batch (24 slots total)
    batches = [
        BatchIn(id=i, name=f"Grade {i} SSC", grade=i, board=CBoard.SSC)
        for i in range(5, 11)
    ]
    subjects = [
        SubjectIn(
            id=10 + i,
            code=f"SUB{i}",
            name=f"Subject {i}",
            is_difficult=(i % 3 == 0),
            preferred_windows=(
                (TimeWindow(start=time(16, 0), end=time(18, 0)),)
                if i % 3 == 0
                else ()
            ),
        )
        for i in range(8)
    ]
    slots = []
    for b in batches:
        for idx in range(1, 5):
            slots.append(
                SlotIn(
                    id=b.id * 100 + idx,
                    batch_id=b.id,
                    period_index=idx,
                    start=time(15 + idx, 0),
                    end=time(16 + idx, 0),
                )
            )

    teachers = []
    for i in range(20):
        # assign 2-3 qualified subjects per teacher
        qualified = {10 + (i + offset) % 8 for offset in range(3)}
        teachers.append(
            TeacherIn(
                id=200 + i,
                full_name=f"Teacher {i}",
                teacher_type=CTeacherType.FULL_TIME,
                max_lectures_per_day=3,
                qualified_subject_ids=frozenset(qualified),
                windows=(),
                preferred_hours=TimeWindow(start=time(16, 0), end=time(18, 0)),
            )
        )

    demands = []
    for b in batches:
        for sub in subjects:
            demands.append(
                BatchSubjectDemand(
                    batch_id=b.id,
                    subject_id=sub.id,
                    remaining_target=2,
                    weekly_target=4,
                    week_days_remaining=4,
                    owner_teacher_id=200 + (b.id + sub.id) % 20,
                )
            )

    input_data = SolverInput(
        target_date=date(2026, 6, 1),
        weekday=0,
        batches=tuple(batches),
        subjects=tuple(subjects),
        slots=tuple(slots),
        teachers=tuple(teachers),
        demands=tuple(demands),
        weights=SolverWeights(),
    )

    import time as pytime

    start = pytime.perf_counter()
    result = solve(input_data)
    duration = pytime.perf_counter() - start

    assert duration < 2.0
    assert result.status in (CSolverStatus.OPTIMAL, CSolverStatus.FEASIBLE)
    assert len(result.assignments) > 0

    # Ensure validator approves the result
    val_res = validate(input_data, result.assignments)
    assert val_res.is_valid is True
