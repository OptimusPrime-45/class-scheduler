"""Comprehensive test suite for the hard-constraint validator."""

from datetime import date, time
import pytest

from app.schemas import (
    Assignment,
    BatchIn,
    CBoard,
    CTeacherType,
    SlotIn,
    SolverInput,
    SubjectIn,
    TeacherIn,
    TimeWindow,
)
from app.scheduler.validator import validate


def _create_mock_input(
    batches=None,
    subjects=None,
    slots=None,
    teachers=None,
) -> SolverInput:
    """Helper to create a SolverInput with configurable data."""
    if batches is None:
        batches = (
            BatchIn(id=1, name="Grade 8 SSC", grade=8, board=CBoard.SSC),
            BatchIn(id=2, name="Grade 9 SSC", grade=9, board=CBoard.SSC),
        )
    if subjects is None:
        subjects = (
            SubjectIn(id=10, code="MATH", name="Mathematics"),
            SubjectIn(id=11, code="SCI", name="Science"),
        )
    if slots is None:
        slots = (
            SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
            SlotIn(id=101, batch_id=1, period_index=2, start=time(17, 0), end=time(18, 0)),
            SlotIn(id=102, batch_id=2, period_index=1, start=time(16, 0), end=time(17, 0)),
        )
    if teachers is None:
        teachers = (
            TeacherIn(
                id=200,
                full_name="Teacher A",
                teacher_type=CTeacherType.FULL_TIME,
                max_lectures_per_day=2,
                qualified_subject_ids=frozenset({10}),
                windows=(),  # Available all day
            ),
            TeacherIn(
                id=201,
                full_name="Teacher B",
                teacher_type=CTeacherType.PART_TIME,
                max_lectures_per_day=1,
                qualified_subject_ids=frozenset({10, 11}),
                windows=(TimeWindow(start=time(16, 0), end=time(17, 0)),),
            ),
        )

    return SolverInput(
        target_date=date(2026, 6, 1),  # Monday
        weekday=0,
        batches=tuple(batches),
        subjects=tuple(subjects),
        slots=tuple(slots),
        teachers=tuple(teachers),
        demands=(),
    )


def test_validator_valid_assignments():
    """Asserts that a correct schedule passes validation with no violations."""
    input_data = _create_mock_input()
    assignments = [
        Assignment(
            batch_id=1,
            slot_id=100,
            subject_id=10,
            teacher_id=200,
            start=time(16, 0),
            end=time(17, 0),
        ),
        Assignment(
            batch_id=2,
            slot_id=102,
            subject_id=11,
            teacher_id=201,
            start=time(16, 0),
            end=time(17, 0),
        ),
    ]

    result = validate(input_data, assignments)
    assert result.is_valid is True
    assert len(result.violations) == 0


def test_validator_invalid_referenced_ids():
    """Asserts that assignments referencing non-existent IDs fail validation."""
    input_data = _create_mock_input()

    # Invalid batch_id
    res_batch = validate(
        input_data,
        [
            Assignment(
                batch_id=999,  # invalid
                slot_id=100,
                subject_id=10,
                teacher_id=200,
                start=time(16, 0),
                end=time(17, 0),
            )
        ],
    )
    assert res_batch.is_valid is False
    assert len(res_batch.violations) == 1
    assert res_batch.violations[0].rule == "referenced_ids"
    assert "batch_id 999" in res_batch.violations[0].message

    # Invalid slot_id
    res_slot = validate(
        input_data,
        [
            Assignment(
                batch_id=1,
                slot_id=999,  # invalid
                subject_id=10,
                teacher_id=200,
                start=time(16, 0),
                end=time(17, 0),
            )
        ],
    )
    assert res_slot.is_valid is False
    assert len(res_slot.violations) == 1
    assert res_slot.violations[0].rule == "referenced_ids"
    assert "slot_id 999" in res_slot.violations[0].message

    # Invalid subject_id
    res_sub = validate(
        input_data,
        [
            Assignment(
                batch_id=1,
                slot_id=100,
                subject_id=999,  # invalid
                teacher_id=200,
                start=time(16, 0),
                end=time(17, 0),
            )
        ],
    )
    assert res_sub.is_valid is False
    assert len(res_sub.violations) == 1
    assert res_sub.violations[0].rule == "referenced_ids"
    assert "subject_id 999" in res_sub.violations[0].message

    # Invalid teacher_id
    res_teacher = validate(
        input_data,
        [
            Assignment(
                batch_id=1,
                slot_id=100,
                subject_id=10,
                teacher_id=999,  # invalid
                start=time(16, 0),
                end=time(17, 0),
            )
        ],
    )
    assert res_teacher.is_valid is False
    assert len(res_teacher.violations) == 1
    assert res_teacher.violations[0].rule == "referenced_ids"
    assert "teacher_id 999" in res_teacher.violations[0].message


def test_validator_batch_slot_compatibility():
    """Asserts that assignments must have batch_id matching the slot's batch_id."""
    input_data = _create_mock_input()
    assignments = [
        Assignment(
            batch_id=2,  # Mismatch: slot 100 belongs to batch 1
            slot_id=100,
            subject_id=10,
            teacher_id=200,
            start=time(16, 0),
            end=time(17, 0),
        )
    ]
    result = validate(input_data, assignments)
    assert result.is_valid is False
    assert len(result.violations) == 1
    assert result.violations[0].rule == "batch_slot_compatibility"


def test_validator_slot_compatibility():
    """Asserts that assignment times must match slot times exactly."""
    input_data = _create_mock_input()
    assignments = [
        Assignment(
            batch_id=1,
            slot_id=100,
            subject_id=10,
            teacher_id=200,
            start=time(16, 0),
            end=time(17, 30),  # Mismatch: slot 100 ends at 17:00
        )
    ]
    result = validate(input_data, assignments)
    assert result.is_valid is False
    assert len(result.violations) == 1
    assert result.violations[0].rule == "slot_compatibility"


def test_validator_teacher_qualification():
    """Asserts that teacher must be qualified for the subject."""
    input_data = _create_mock_input()
    assignments = [
        Assignment(
            batch_id=1,
            slot_id=100,
            subject_id=11,  # Teacher A (200) only qualified for subject 10
            teacher_id=200,
            start=time(16, 0),
            end=time(17, 0),
        )
    ]
    result = validate(input_data, assignments)
    assert result.is_valid is False
    assert len(result.violations) == 1
    assert result.violations[0].rule == "teacher_qualification"


def test_validator_teacher_availability():
    """Asserts that assignments must fall within teacher's availability windows."""
    input_data = _create_mock_input()

    # Slot 101 is 17:00 to 18:00
    # Teacher B (201) is only available 16:00 to 17:00
    assignments = [
        Assignment(
            batch_id=1,
            slot_id=101,
            subject_id=11,
            teacher_id=201,
            start=time(17, 0),
            end=time(18, 0),
        )
    ]
    result = validate(input_data, assignments)
    assert result.is_valid is False
    assert len(result.violations) == 1
    assert result.violations[0].rule == "teacher_availability"


def test_validator_single_assignment_per_slot():
    """Asserts that at most one assignment can map to a slot_id."""
    input_data = _create_mock_input()
    assignments = [
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
            slot_id=100,
            subject_id=10,
            # Assigning two different teachers (or even same) to same slot is invalid
            teacher_id=201,
            start=time(16, 0),
            end=time(17, 0),
        ),
    ]
    result = validate(input_data, assignments)
    assert result.is_valid is False
    # Might trigger other violations (like batch overlap), but must include single_assignment_per_slot
    rules = {v.rule for v in result.violations}
    assert "single_assignment_per_slot" in rules


def test_validator_no_slot_overlap_per_batch():
    """Asserts that assignments for the same batch cannot overlap in time."""
    # Create two overlapping slots for batch 1
    custom_slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(16, 30), end=time(17, 30)),
    )
    input_data = _create_mock_input(slots=custom_slots)

    assignments = [
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
            subject_id=11,
            teacher_id=201,
            start=time(16, 30),
            end=time(17, 30),
        ),
    ]
    result = validate(input_data, assignments)
    assert result.is_valid is False
    rules = {v.rule for v in result.violations}
    assert "batch_slot_overlap" in rules


def test_validator_no_double_booking_per_teacher():
    """Asserts that a teacher cannot be double booked at the same time."""
    input_data = _create_mock_input()
    assignments = [
        Assignment(
            batch_id=1,
            slot_id=100,
            subject_id=10,
            teacher_id=200,
            start=time(16, 0),
            end=time(17, 0),
        ),
        Assignment(
            batch_id=2,
            slot_id=102,
            subject_id=10,
            teacher_id=200,  # Teacher 200 assigned to two different batches at the same time
            start=time(16, 0),
            end=time(17, 0),
        ),
    ]
    result = validate(input_data, assignments)
    assert result.is_valid is False
    rules = {v.rule for v in result.violations}
    assert "teacher_double_booking" in rules


def test_validator_max_lectures_per_day():
    """Asserts that teacher assignment count cannot exceed max_lectures_per_day."""
    # Teacher B (201) has max_lectures_per_day = 1
    # Give them two assignments at different times
    custom_slots = (
        SlotIn(id=100, batch_id=1, period_index=1, start=time(16, 0), end=time(17, 0)),
        SlotIn(id=101, batch_id=1, period_index=2, start=time(17, 0), end=time(18, 0)),
    )
    custom_teachers = (
        TeacherIn(
            id=201,
            full_name="Teacher B",
            teacher_type=CTeacherType.PART_TIME,
            max_lectures_per_day=1,
            qualified_subject_ids=frozenset({10, 11}),
            windows=(),  # Available all day
        ),
    )
    input_data = _create_mock_input(slots=custom_slots, teachers=custom_teachers)

    assignments = [
        Assignment(
            batch_id=1,
            slot_id=100,
            subject_id=10,
            teacher_id=201,
            start=time(16, 0),
            end=time(17, 0),
        ),
        Assignment(
            batch_id=1,
            slot_id=101,
            subject_id=11,
            teacher_id=201,
            start=time(17, 0),
            end=time(18, 0),
        ),
    ]
    result = validate(input_data, assignments)
    assert result.is_valid is False
    rules = {v.rule for v in result.violations}
    assert "max_lectures_per_day" in rules
