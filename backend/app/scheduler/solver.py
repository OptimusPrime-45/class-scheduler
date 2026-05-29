"""CP-SAT Solver for tuition scheduler."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, time as datetime_time
from typing import Any

from ortools.sat.python import cp_model

from app.schemas import (
    Assignment,
    CSolverStatus,
    SlotIn,
    SolverInput,
    SolverResult,
    UnfilledSlot,
)


def solve(input_data: SolverInput) -> SolverResult:
    """Solves the class scheduling problem using OR-Tools CP-SAT."""
    start_time = time.perf_counter()

    # 1. Initialize CpModel
    model = cp_model.CpModel()

    # 2. Build lookups
    teachers_dict = {t.id: t for t in input_data.teachers}
    subjects_dict = {sub.id: sub for sub in input_data.subjects}
    slots_dict = {s.id: s for s in input_data.slots}

    # Map locked assignments for fast check
    locked_keys = set()
    for la in input_data.locked_assignments:
        locked_keys.add((la.slot_id, la.subject_id, la.teacher_id))

    # Variables: x[slot_id, subject_id, teacher_id]
    x = {}

    for slot in input_data.slots:
        for demand in input_data.demands:
            if demand.batch_id != slot.batch_id:
                continue
            sub_id = demand.subject_id
            for teacher in input_data.teachers:
                # Qualification check
                if sub_id not in teacher.qualified_subject_ids:
                    continue

                # Availability check
                is_available = False
                if not teacher.windows:
                    is_available = True
                else:
                    for w in teacher.windows:
                        if w.start <= slot.start and slot.end <= w.end:
                            is_available = True
                            break

                if is_available:
                    x[(slot.id, sub_id, teacher.id)] = model.NewBoolVar(
                        f"x_{slot.id}_{sub_id}_{teacher.id}"
                    )

    # Force locked assignments to 1, creating variable if not present
    for la in input_data.locked_assignments:
        # Guard against invalid ID references in locked_assignments
        if (
            la.slot_id not in slots_dict
            or la.subject_id not in subjects_dict
            or la.teacher_id not in teachers_dict
        ):
            continue

        key = (la.slot_id, la.subject_id, la.teacher_id)
        if key not in x:
            x[key] = model.NewBoolVar(f"x_{la.slot_id}_{la.subject_id}_{la.teacher_id}")
        model.Add(x[key] == 1)

    # Hard Constraints
    # 1. One assignment per slot: sum of variables for that slot <= 1
    for slot in input_data.slots:
        vars_for_slot = [var for key, var in x.items() if key[0] == slot.id]
        model.Add(sum(vars_for_slot) <= 1)

    # 2. Teacher double booking: no overlap in time for a teacher
    # Overlapping check helper: max(start1, start2) < min(end1, end2)
    def slots_overlap(s1: SlotIn, s2: SlotIn) -> bool:
        return max(s1.start, s2.start) < min(s1.end, s2.end)

    for teacher in input_data.teachers:
        # Collect slots where this teacher could potentially be assigned
        teacher_slots = [
            slots_dict[slot_id]
            for (slot_id, _, t_id) in x.keys()
            if t_id == teacher.id
        ]
        # Keep unique slots
        teacher_slots = list({s.id: s for s in teacher_slots}.values())

        # Pairwise overlap constraints
        for i in range(len(teacher_slots)):
            for j in range(i + 1, len(teacher_slots)):
                s1 = teacher_slots[i]
                s2 = teacher_slots[j]
                if slots_overlap(s1, s2):
                    vars_s1 = [
                        var
                        for key, var in x.items()
                        if key[0] == s1.id and key[2] == teacher.id
                    ]
                    vars_s2 = [
                        var
                        for key, var in x.items()
                        if key[0] == s2.id and key[2] == teacher.id
                    ]
                    model.Add(sum(vars_s1) + sum(vars_s2) <= 1)

    # 3. Max lectures/day per teacher
    for teacher in input_data.teachers:
        vars_for_teacher = [var for key, var in x.items() if key[2] == teacher.id]
        model.Add(sum(vars_for_teacher) <= teacher.max_lectures_per_day)

    # 4. No slot overlap per batch (for validator parity)
    for batch in input_data.batches:
        batch_slots = [s for s in input_data.slots if s.batch_id == batch.id]
        for i in range(len(batch_slots)):
            for j in range(i + 1, len(batch_slots)):
                s1 = batch_slots[i]
                s2 = batch_slots[j]
                if slots_overlap(s1, s2):
                    vars_s1 = [var for key, var in x.items() if key[0] == s1.id]
                    vars_s2 = [var for key, var in x.items() if key[0] == s2.id]
                    model.Add(sum(vars_s1) + sum(vars_s2) <= 1)

    # Soft Terms (objective to maximize)
    objective_terms = []

    # A. Base reward for filled slots: +fill_slot * sum(x)
    objective_terms.extend([input_data.weights.fill_slot * var for var in x.values()])

    # B. Owner/primary teacher: +w_owner_teacher * x[s, sub, t] if t is owner
    owner_map = {}
    for demand in input_data.demands:
        if demand.owner_teacher_id is not None:
            owner_map[(demand.batch_id, demand.subject_id)] = demand.owner_teacher_id

    for (slot_id, sub_id, t_id), var in x.items():
        slot = slots_dict[slot_id]
        if owner_map.get((slot.batch_id, sub_id)) == t_id:
            objective_terms.append(input_data.weights.w_owner_teacher * var)

    # C. Preferred hours: +w_preferred_hours * x[s, sub, t] if within preferred window
    for (slot_id, _, t_id), var in x.items():
        teacher = teachers_dict[t_id]
        pref = teacher.preferred_hours
        if pref is not None:
            slot = slots_dict[slot_id]
            if slot.start >= pref.start and slot.end <= pref.end:
                objective_terms.append(input_data.weights.w_preferred_hours * var)

    # D. Workload balance: Maximize w_workload_balance * -1 * (max_load - min_load)
    if input_data.teachers:
        max_load = model.NewIntVar(0, len(input_data.slots), "max_load")
        min_load = model.NewIntVar(0, len(input_data.slots), "min_load")
        for teacher in input_data.teachers:
            vars_for_teacher = [var for key, var in x.items() if key[2] == teacher.id]
            model.Add(max_load >= sum(vars_for_teacher))
            model.Add(min_load <= sum(vars_for_teacher))
        objective_terms.append(input_data.weights.w_workload_balance * -1 * (max_load - min_load))

    # E. Avoid gaps: -w_avoid_gaps * is_gap_i
    for batch in input_data.batches:
        batch_slots = sorted(
            [s for s in input_data.slots if s.batch_id == batch.id],
            key=lambda s: s.start,
        )
        n = len(batch_slots)
        if n <= 2:
            continue

        # Define y_i for each slot (filled or not)
        y = []
        for s in batch_slots:
            y_var = model.NewBoolVar(f"y_batch_{batch.id}_slot_{s.id}")
            vars_for_slot = [var for key, var in x.items() if key[0] == s.id]
            model.Add(y_var == sum(vars_for_slot))
            y.append(y_var)

        # has_before_i = Or(has_before_{i-1}, y_{i-1})
        has_before = []
        has_before_0 = model.NewBoolVar(f"has_before_batch_{batch.id}_0")
        model.Add(has_before_0 == 0)
        has_before.append(has_before_0)

        for i in range(1, n):
            hb_var = model.NewBoolVar(f"has_before_batch_{batch.id}_{i}")
            model.AddMaxEquality(hb_var, [has_before[i - 1], y[i - 1]])
            has_before.append(hb_var)

        # has_after_i = Or(has_after_{i+1}, y_{i+1})
        has_after = [None] * n
        has_after_last = model.NewBoolVar(f"has_after_batch_{batch.id}_{n-1}")
        model.Add(has_after_last == 0)
        has_after[n - 1] = has_after_last

        for i in range(n - 2, -1, -1):
            ha_var = model.NewBoolVar(f"has_after_batch_{batch.id}_{i}")
            model.AddMaxEquality(ha_var, [has_after[i + 1], y[i + 1]])
            has_after[i] = ha_var

        # is_gap_i >= has_before_i + (1 - y_i) + has_after_i - 2
        for i in range(n):
            is_gap_var = model.NewBoolVar(f"is_gap_batch_{batch.id}_{i}")
            model.Add(
                is_gap_var >= has_before[i] + (1 - y[i]) + has_after[i] - 2
            )
            objective_terms.append(-input_data.weights.w_avoid_gaps * is_gap_var)

    # F. Difficult subject preferred window: +w_difficult_window * x[s, sub, t]
    for (slot_id, sub_id, _), var in x.items():
        subject = subjects_dict[sub_id]
        if subject.is_difficult:
            slot = slots_dict[slot_id]
            is_in_window = False
            for w in subject.preferred_windows:
                if w.start <= slot.start and slot.end <= w.end:
                    is_in_window = True
                    break
            if is_in_window:
                objective_terms.append(input_data.weights.w_difficult_window * var)

    # G. Target debt: Cap reward to remaining_target for each (batch, subject) demand
    for demand in input_data.demands:
        vars_for_demand = [
            var
            for key, var in x.items()
            if slots_dict[key[0]].batch_id == demand.batch_id
            and key[1] == demand.subject_id
        ]

        upper_bound = max(0, demand.remaining_target)
        rewarded_d = model.NewIntVar(
            0, upper_bound, f"rewarded_{demand.batch_id}_{demand.subject_id}"
        )

        model.Add(rewarded_d <= sum(vars_for_demand))
        model.Add(rewarded_d <= demand.remaining_target)

        effective_w = input_data.weights.w_remaining_target
        if demand.week_days_remaining <= 1:
            effective_w *= 2

        objective_terms.append(rewarded_d * effective_w * demand.remaining_target)

    # Configure CP-SAT Parameters
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = input_data.solver_time_limit_seconds
    solver.parameters.random_seed = input_data.random_seed
    solver.parameters.num_search_workers = input_data.num_workers

    # Maximize objective
    if objective_terms:
        model.Maximize(sum(objective_terms))

    # Solve
    status = solver.Solve(model)

    # Map solver status
    if status == cp_model.OPTIMAL:
        solver_status = CSolverStatus.OPTIMAL
    elif status == cp_model.FEASIBLE:
        solver_status = CSolverStatus.FEASIBLE
    elif status == cp_model.INFEASIBLE:
        solver_status = CSolverStatus.INFEASIBLE
    elif status == cp_model.MODEL_INVALID:
        solver_status = CSolverStatus.MODEL_INVALID
    else:
        solver_status = CSolverStatus.UNKNOWN

    assignments = []
    assigned_slot_ids = set()

    # Collect assignments if model solved successfully
    if solver_status in (CSolverStatus.OPTIMAL, CSolverStatus.FEASIBLE):
        for (slot_id, sub_id, t_id), var in x.items():
            if solver.Value(var) == 1:
                slot = slots_dict[slot_id]
                assignments.append(
                    Assignment(
                        batch_id=slot.batch_id,
                        slot_id=slot.id,
                        subject_id=sub_id,
                        teacher_id=t_id,
                        start=slot.start,
                        end=slot.end,
                    )
                )
                assigned_slot_ids.add(slot_id)

    # Determine unfilled slots and their reasons
    unfilled_slots = []
    for slot in input_data.slots:
        if slot.id not in assigned_slot_ids:
            sub_id, reason = _determine_unfilled_reason(
                slot, input_data, assignments
            )
            unfilled_slots.append(
                UnfilledSlot(
                    batch_id=slot.batch_id,
                    slot_id=slot.id,
                    subject_id=sub_id,
                    reason=reason,
                )
            )

    solve_time_ms = int((time.perf_counter() - start_time) * 1000)

    # Diagnostics information
    diagnostics = {
        "num_variables": len(model.Proto().variables),
        "num_constraints": len(model.Proto().constraints),
        "num_x_variables": len(x),
        "search_status": int(status),
    }

    objective_value = None
    if solver_status in (CSolverStatus.OPTIMAL, CSolverStatus.FEASIBLE):
        objective_value = float(solver.ObjectiveValue())

    return SolverResult(
        target_date=input_data.target_date,
        status=solver_status,
        objective_value=objective_value,
        assignments=tuple(assignments),
        unfilled_slots=tuple(unfilled_slots),
        solve_time_ms=solve_time_ms,
        diagnostics=diagnostics,
    )


def _determine_unfilled_reason(
    slot: SlotIn,
    input_data: SolverInput,
    assignments: list[Assignment],
) -> tuple[int | None, str]:
    """Helper to determine why a slot is unfilled and which subject it was for."""
    batch_demands = [d for d in input_data.demands if d.batch_id == slot.batch_id]

    if not batch_demands:
        return None, "no demand configured for batch"

    # Check if there is any remaining weekly target
    active_demands = [d for d in batch_demands if d.remaining_target > 0]
    if not active_demands:
        return None, "no remaining weekly target for batch"

    # Check which demands are unsatisfied
    unsatisfied_demands = []
    for d in active_demands:
        scheduled_count = sum(
            1
            for a in assignments
            if a.batch_id == slot.batch_id and a.subject_id == d.subject_id
        )
        if scheduled_count < d.remaining_target:
            unsatisfied_demands.append(d)

    if not unsatisfied_demands:
        return None, "all batch demands satisfied"

    # Choose the most pressing unsatisfied demand (highest remaining target)
    unsatisfied_demands.sort(key=lambda d: (-d.remaining_target, d.subject_id))
    target_demand = unsatisfied_demands[0]
    sub_id = target_demand.subject_id

    # Check for qualified teachers
    qualified_teachers = [
        t for t in input_data.teachers if sub_id in t.qualified_subject_ids
    ]
    if not qualified_teachers:
        return sub_id, "no qualified teacher available"

    # Check for available teachers at this slot time
    available_teachers = []
    for t in qualified_teachers:
        is_avail = False
        if not t.windows:
            is_avail = True
        else:
            for w in t.windows:
                if w.start <= slot.start and slot.end <= w.end:
                    is_avail = True
                    break
        if is_avail:
            available_teachers.append(t)

    if not available_teachers:
        return sub_id, "no qualified teacher available at slot time"

    # Analyze why none of the available teachers could be assigned
    all_max_lectures = True
    all_double_booked = True
    for t in available_teachers:
        t_assignments = [a for a in assignments if a.teacher_id == t.id]
        if len(t_assignments) < t.max_lectures_per_day:
            all_max_lectures = False

        is_double_booked = False
        for a in t_assignments:
            if max(slot.start, a.start) < min(slot.end, a.end):
                is_double_booked = True
                break
        if not is_double_booked:
            all_double_booked = False

    if all_max_lectures:
        return sub_id, "qualified teachers reached max lectures limit"
    if all_double_booked:
        return sub_id, "qualified teachers double-booked at this time"

    return sub_id, "resource constraint or optimization trade-off"
