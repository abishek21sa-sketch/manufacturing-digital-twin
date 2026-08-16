from __future__ import annotations

from dataclasses import dataclass

from .model import ScheduleProblem, ScheduleResult


@dataclass(frozen=True)
class ScheduleViolation:
    kind: str
    message: str


@dataclass(frozen=True)
class ScheduleAssessment:
    """Canonical interpretation of a solver result.

    Solver *termination* and schedule *feasibility* are deliberately separate.
    A TIME_LIMIT result can contain a complete, physically feasible incumbent;
    such a solution is usable as a candidate but does not prove optimality.
    Every operational decision path should consume this assessment instead of
    hard-coding status-name sets independently.
    """

    termination_status: str
    has_incumbent: bool
    complete_incumbent: bool
    feasible: bool
    optimality_proven: bool
    quality: str
    mip_gap: float | None
    violations: tuple[ScheduleViolation, ...]


def validate_schedule(problem: ScheduleProblem, result: ScheduleResult, tolerance: float = 1e-6) -> list[ScheduleViolation]:
    violations: list[ScheduleViolation] = []
    # A solver can stop at TIME_LIMIT after finding an incumbent. That is not
    # an optimality certificate, but it can still be independently checked for
    # physical feasibility. Reject statuses that cannot represent a usable
    # incumbent; TIME_LIMIT is allowed only when operations are actually present.
    if result.evidence.status not in {"OPTIMAL", "FEASIBLE", "TIME_LIMIT"}:
        return [ScheduleViolation("solver_status", f"schedule status is {result.evidence.status}")]
    if result.evidence.status == "TIME_LIMIT" and not result.operations:
        return [ScheduleViolation("solver_status", "TIME_LIMIT reached without a feasible incumbent")]
    by_id = {op.operation_id: op for op in result.operations}
    if len(by_id) != problem.factory.operation_count:
        violations.append(ScheduleViolation("operation_count", "not every operation appears exactly once"))
        return violations

    for job in problem.factory.jobs:
        pjob = problem.planning_job(job.job_id)
        previous = None
        for spec in job.operations:
            op = by_id.get(spec.operation_id)
            if op is None:
                violations.append(ScheduleViolation("missing_operation", spec.operation_id))
                continue
            if op.machine_id != spec.machine_id:
                violations.append(ScheduleViolation("machine_eligibility", spec.operation_id))
            if abs((op.finish - op.start) - spec.processing_time) > tolerance:
                violations.append(ScheduleViolation("duration", spec.operation_id))
            if op.start + tolerance < max(problem.current_time, pjob.release_time):
                violations.append(ScheduleViolation("release", spec.operation_id))
            if op.start + tolerance < problem.machine_ready_time(spec.machine_id):
                violations.append(ScheduleViolation("machine_availability", spec.operation_id))
            if previous is not None and op.start + tolerance < previous.finish:
                violations.append(ScheduleViolation("precedence", f"{previous.operation_id}->{op.operation_id}"))
            previous = op

    by_machine: dict[str, list] = {}
    for op in result.operations:
        by_machine.setdefault(op.machine_id, []).append(op)
    for machine_id, ops in by_machine.items():
        ops.sort(key=lambda x: (x.start, x.finish, x.operation_id))
        for left, right in zip(ops, ops[1:]):
            if right.start + tolerance < left.finish:
                violations.append(ScheduleViolation("machine_overlap", f"{machine_id}:{left.operation_id}/{right.operation_id}"))

    return violations


def assess_schedule(problem: ScheduleProblem, result: ScheduleResult, tolerance: float = 1e-6) -> ScheduleAssessment:
    """Return the one canonical solution-quality interpretation used repository-wide."""

    violations = tuple(validate_schedule(problem, result, tolerance=tolerance))
    expected = problem.factory.operation_count
    unique_ids = {op.operation_id for op in result.operations}
    has_incumbent = bool(result.operations)
    complete_incumbent = has_incumbent and len(result.operations) == expected and len(unique_ids) == expected
    feasible = complete_incumbent and not violations and result.evidence.status in {"OPTIMAL", "FEASIBLE", "TIME_LIMIT"}
    optimality_proven = feasible and result.evidence.status == "OPTIMAL"
    if optimality_proven:
        quality = "OPTIMAL"
    elif feasible:
        quality = "FEASIBLE_INCUMBENT"
    elif has_incumbent:
        quality = "INVALID_INCUMBENT"
    else:
        quality = "NO_USABLE_SOLUTION"
    return ScheduleAssessment(
        termination_status=result.evidence.status,
        has_incumbent=has_incumbent,
        complete_incumbent=complete_incumbent,
        feasible=feasible,
        optimality_proven=optimality_proven,
        quality=quality,
        mip_gap=result.evidence.mip_gap,
        violations=violations,
    )
