from __future__ import annotations

from .gurobi_solver import GurobiUnavailable, gurobi_available, solve_with_gurobi
from .model import ScheduleProblem, ScheduleResult
from .scipy_solver import solve_with_scipy


def solve_schedule(problem: ScheduleProblem, backend: str = "auto", time_limit: float = 30.0, mip_gap: float = 0.0) -> ScheduleResult:
    key = backend.lower()
    if key not in {"auto", "gurobi", "scipy"}:
        raise ValueError("backend must be auto, gurobi, or scipy")
    if key == "gurobi":
        return solve_with_gurobi(problem, time_limit=time_limit, mip_gap=mip_gap)
    if key == "scipy":
        return solve_with_scipy(problem, time_limit=time_limit, mip_gap=mip_gap)
    if gurobi_available():
        try:
            return solve_with_gurobi(problem, time_limit=time_limit, mip_gap=mip_gap)
        except GurobiUnavailable:
            pass
    return solve_with_scipy(problem, time_limit=time_limit, mip_gap=mip_gap)
