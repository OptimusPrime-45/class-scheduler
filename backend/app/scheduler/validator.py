"""Hard constraint validator for tuition scheduler assignments."""

from collections import defaultdict
from typing import Iterable

from app.schemas import (
    Assignment,
    ConstraintViolation,
    SolverInput,
    ValidationResult,
)


def validate(
    input_data: SolverInput, assignments: Iterable[Assignment]
) -> ValidationResult:
    """Validates a set of assignments against hard constraints.

    Checks:
    - Validity of referenced IDs (slot_id, teacher_id, subject_id, batch_id exist)
    - Entry-to-slot batch compatibility (assignment batch_id == slot batch_id)
    - Slot compatibility (assignment's start/end times match slot's times)
    - Teacher qualification (teacher qualified for subject)
    - Availability windows (assignment within teacher availability windows)
    - Single assignment per slot (at most one assignment per slot_id)
    - No slot overlap per batch (no two assignments for same batch overlap in time)
    - No double booking per teacher (no two assignments for same teacher overlap in time)
    - Max lectures per day (teacher assignments count <= max_lectures_per_day)

    Returns a ValidationResult containing any ConstraintViolations.
    """
    violations = []
    assignments_list = list(assignments)

    # 1. Build lookup dictionaries for speed and existence checks
    batches_dict = {b.id: b for b in input_data.batches}
    slots_dict = {s.id: s for s in input_data.slots}
    subjects_dict = {sub.id: sub for sub in input_data.subjects}
    teachers_dict = {t.id: t for t in input_data.teachers}

    # Grouping lists for multi-assignment validation checks
    slot_assignments = defaultdict(list)
    batch_assignments = defaultdict(list)
    teacher_assignments = defaultdict(list)

    # Single-assignment level checks
    for idx, assignment in enumerate(assignments_list):
        batch_exists = assignment.batch_id in batches_dict
        slot_exists = assignment.slot_id in slots_dict
        subject_exists = assignment.subject_id in subjects_dict
        teacher_exists = assignment.teacher_id in teachers_dict

        # Rule: Validity of referenced IDs
        if not (batch_exists and slot_exists and subject_exists and teacher_exists):
            missing = []
            if not batch_exists:
                missing.append(f"batch_id {assignment.batch_id}")
            if not slot_exists:
                missing.append(f"slot_id {assignment.slot_id}")
            if not subject_exists:
                missing.append(f"subject_id {assignment.subject_id}")
            if not teacher_exists:
                missing.append(f"teacher_id {assignment.teacher_id}")

            violations.append(
                ConstraintViolation(
                    rule="referenced_ids",
                    message=f"Assignment {idx} references non-existent ID(s): {', '.join(missing)}.",
                    details={
                        "assignment_index": idx,
                        "batch_id": assignment.batch_id,
                        "slot_id": assignment.slot_id,
                        "subject_id": assignment.subject_id,
                        "teacher_id": assignment.teacher_id,
                        "batch_exists": batch_exists,
                        "slot_exists": slot_exists,
                        "subject_exists": subject_exists,
                        "teacher_exists": teacher_exists,
                    },
                )
            )
            # Skip subsequent validation checks for this invalid assignment
            continue

        slot = slots_dict[assignment.slot_id]
        teacher = teachers_dict[assignment.teacher_id]

        # Rule: Entry-to-slot batch compatibility
        if assignment.batch_id != slot.batch_id:
            violations.append(
                ConstraintViolation(
                    rule="batch_slot_compatibility",
                    message=(
                        f"Assignment {idx} batch_id ({assignment.batch_id}) does not match "
                        f"slot {slot.id} batch_id ({slot.batch_id})."
                    ),
                    details={
                        "assignment_index": idx,
                        "assignment_batch_id": assignment.batch_id,
                        "slot_batch_id": slot.batch_id,
                        "slot_id": slot.id,
                    },
                )
            )

        # Rule: Slot compatibility
        if assignment.start != slot.start or assignment.end != slot.end:
            violations.append(
                ConstraintViolation(
                    rule="slot_compatibility",
                    message=(
                        f"Assignment {idx} times ({assignment.start}-{assignment.end}) "
                        f"do not match slot {slot.id} times ({slot.start}-{slot.end})."
                    ),
                    details={
                        "assignment_index": idx,
                        "assignment_start": str(assignment.start),
                        "assignment_end": str(assignment.end),
                        "slot_start": str(slot.start),
                        "slot_end": str(slot.end),
                        "slot_id": slot.id,
                    },
                )
            )

        # Rule: Qualification check
        if assignment.subject_id not in teacher.qualified_subject_ids:
            violations.append(
                ConstraintViolation(
                    rule="teacher_qualification",
                    message=(
                        f"Teacher {teacher.full_name} (ID {teacher.id}) is not qualified "
                        f"for subject ID {assignment.subject_id}."
                    ),
                    details={
                        "assignment_index": idx,
                        "teacher_id": teacher.id,
                        "subject_id": assignment.subject_id,
                        "qualified_subject_ids": list(teacher.qualified_subject_ids),
                    },
                )
            )

        # Rule: Availability windows
        if teacher.windows:
            is_available = False
            for w in teacher.windows:
                if w.start <= assignment.start and assignment.end <= w.end:
                    is_available = True
                    break
            if not is_available:
                violations.append(
                    ConstraintViolation(
                        rule="teacher_availability",
                        message=(
                            f"Assignment {idx} time ({assignment.start}-{assignment.end}) "
                            f"is outside availability windows for teacher {teacher.full_name}."
                        ),
                        details={
                            "assignment_index": idx,
                            "teacher_id": teacher.id,
                            "assignment_start": str(assignment.start),
                            "assignment_end": str(assignment.end),
                            "windows": [
                                {"start": str(w.start), "end": str(w.end)}
                                for w in teacher.windows
                            ],
                        },
                    )
                )

        # Record valid assignments for group-level validation checks
        slot_assignments[assignment.slot_id].append((idx, assignment))
        batch_assignments[assignment.batch_id].append((idx, assignment))
        teacher_assignments[assignment.teacher_id].append((idx, assignment))

    # Rule: Single assignment per slot
    for slot_id, group in slot_assignments.items():
        if len(group) > 1:
            violations.append(
                ConstraintViolation(
                    rule="single_assignment_per_slot",
                    message=f"Slot ID {slot_id} has {len(group)} assignments.",
                    details={
                        "slot_id": slot_id,
                        "assignment_indices": [g[0] for g in group],
                    },
                )
            )

    # Helper function to check overlap between two assignments
    def overlaps(a1: Assignment, a2: Assignment) -> bool:
        # half-open overlap: max(start1, start2) < min(end1, end2)
        return a1.start < a2.end and a2.start < a1.end

    # Rule: No slot overlap per batch
    for batch_id, group in batch_assignments.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                idx1, a1 = group[i]
                idx2, a2 = group[j]
                if overlaps(a1, a2):
                    violations.append(
                        ConstraintViolation(
                            rule="batch_slot_overlap",
                            message=(
                                f"Assignments {idx1} and {idx2} for batch ID {batch_id} "
                                f"overlap in time ({a1.start}-{a1.end} vs {a2.start}-{a2.end})."
                            ),
                            details={
                                "batch_id": batch_id,
                                "assignment1": {
                                    "index": idx1,
                                    "slot_id": a1.slot_id,
                                    "start": str(a1.start),
                                    "end": str(a1.end),
                                },
                                "assignment2": {
                                    "index": idx2,
                                    "slot_id": a2.slot_id,
                                    "start": str(a2.start),
                                    "end": str(a2.end),
                                },
                            },
                        )
                    )

    # Rule: No double booking per teacher
    for teacher_id, group in teacher_assignments.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                idx1, a1 = group[i]
                idx2, a2 = group[j]
                if overlaps(a1, a2):
                    violations.append(
                        ConstraintViolation(
                            rule="teacher_double_booking",
                            message=(
                                f"Assignments {idx1} and {idx2} for teacher ID {teacher_id} "
                                f"overlap in time ({a1.start}-{a1.end} vs {a2.start}-{a2.end})."
                            ),
                            details={
                                "teacher_id": teacher_id,
                                "assignment1": {
                                    "index": idx1,
                                    "slot_id": a1.slot_id,
                                    "start": str(a1.start),
                                    "end": str(a1.end),
                                },
                                "assignment2": {
                                    "index": idx2,
                                    "slot_id": a2.slot_id,
                                    "start": str(a2.start),
                                    "end": str(a2.end),
                                },
                            },
                        )
                    )

    # Rule: Max lectures per day
    for teacher_id, group in teacher_assignments.items():
        teacher = teachers_dict[teacher_id]
        if len(group) > teacher.max_lectures_per_day:
            violations.append(
                ConstraintViolation(
                    rule="max_lectures_per_day",
                    message=(
                        f"Teacher {teacher.full_name} (ID {teacher_id}) has {len(group)} assignments, "
                        f"exceeding max of {teacher.max_lectures_per_day} per day."
                    ),
                    details={
                        "teacher_id": teacher_id,
                        "assigned_count": len(group),
                        "max_lectures_per_day": teacher.max_lectures_per_day,
                        "assignment_indices": [g[0] for g in group],
                    },
                )
            )

    is_valid = len(violations) == 0
    return ValidationResult(is_valid=is_valid, violations=tuple(violations))
