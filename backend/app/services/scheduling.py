from __future__ import annotations

from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Schedule
from app.scheduler.solver import solve
from app.services.loader import load_solver_input
from app.services.persister import persist_solver_result


async def generate_schedule(session: AsyncSession, target_date: date) -> Schedule:
    """Orchestrates loading solver input, running the CP-SAT solver, and persisting
    the generated schedule in a single database transaction.
    """
    # 1. Load solver input for the target date
    solver_input = await load_solver_input(session, target_date)

    # 2. Synchronously run the CP-SAT solver
    result = solve(solver_input)

    # 3. Dump the solver input to a JSON-compatible dict snapshot
    solver_input_snapshot = solver_input.model_dump(mode="json")

    # 4. Persist the solver result in a transaction block
    if session.in_transaction():
        async with session.begin_nested():
            schedule = await persist_solver_result(session, result, solver_input_snapshot)
    else:
        async with session.begin():
            schedule = await persist_solver_result(session, result, solver_input_snapshot)

    return schedule
