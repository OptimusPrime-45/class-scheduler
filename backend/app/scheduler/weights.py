"""Tunable soft-constraint weights for the solver."""

from app.schemas import SolverWeights

# A default instance of the weights schema
DEFAULT_WEIGHTS = SolverWeights()

# Individual default weight constants for convenience
FILL_SLOT = DEFAULT_WEIGHTS.fill_slot
W_OWNER_TEACHER = DEFAULT_WEIGHTS.w_owner_teacher
W_PREFERRED_HOURS = DEFAULT_WEIGHTS.w_preferred_hours
W_WORKLOAD_BALANCE = DEFAULT_WEIGHTS.w_workload_balance
W_AVOID_GAPS = DEFAULT_WEIGHTS.w_avoid_gaps
W_DIFFICULT_WINDOW = DEFAULT_WEIGHTS.w_difficult_window
W_REMAINING_TARGET = DEFAULT_WEIGHTS.w_remaining_target
