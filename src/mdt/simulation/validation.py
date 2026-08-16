from __future__ import annotations

from dataclasses import dataclass

from mdt.optimization.model import ScheduleProblem
from .model import SimulationResult


@dataclass(frozen=True)
class SimulationViolation:
    kind: str
    message: str


def _overlap(a_start: float, a_finish: float, b_start: float, b_finish: float, tol: float) -> bool:
    return a_start < b_finish - tol and b_start < a_finish - tol


def validate_simulation(problem: ScheduleProblem, result: SimulationResult, tolerance: float = 1e-6) -> list[SimulationViolation]:
    violations: list[SimulationViolation] = []
    by_id = {op.operation_id: op for op in result.operations}
    if len(by_id) != problem.factory.operation_count:
        violations.append(SimulationViolation("operation_count", "not every operation completed exactly once"))
        return violations

    segments_by_op: dict[str, list] = {}
    segments_by_machine: dict[str, list] = {}
    for segment in result.processing_segments:
        segments_by_op.setdefault(segment.operation_id, []).append(segment)
        segments_by_machine.setdefault(segment.machine_id, []).append(segment)
        if segment.finish + tolerance < segment.start:
            violations.append(SimulationViolation("segment_duration", segment.operation_id))

    for job in problem.factory.jobs:
        previous_finish = None
        for spec in job.operations:
            op = by_id[spec.operation_id]
            if op.machine_id != spec.machine_id:
                violations.append(SimulationViolation("machine_eligibility", spec.operation_id))
            if op.start + tolerance < problem.planning_job(job.job_id).release_time:
                violations.append(SimulationViolation("release", spec.operation_id))
            if previous_finish is not None and op.start + tolerance < previous_finish:
                violations.append(SimulationViolation("precedence", spec.operation_id))
            previous_finish = op.finish
            processed = sum(s.finish - s.start for s in segments_by_op.get(spec.operation_id, []))
            if abs(processed - op.realized_processing) > max(tolerance, tolerance * max(1.0, op.realized_processing)):
                violations.append(SimulationViolation("work_conservation", spec.operation_id))
            if op.finish + tolerance < op.start:
                violations.append(SimulationViolation("operation_duration", spec.operation_id))

    for machine_id, segments in segments_by_machine.items():
        ordered = sorted(segments, key=lambda s: (s.start, s.finish, s.operation_id))
        for left, right in zip(ordered, ordered[1:]):
            if _overlap(left.start, left.finish, right.start, right.finish, tolerance):
                violations.append(SimulationViolation("machine_overlap", f"{machine_id}: {left.operation_id}/{right.operation_id}"))
        for segment in ordered:
            for down in result.downtime_intervals:
                if down.machine_id == machine_id and _overlap(segment.start, segment.finish, down.start, down.finish, tolerance):
                    violations.append(SimulationViolation("processing_during_downtime", f"{machine_id}: {segment.operation_id}"))

    if result.metrics.little_law_error > 1e-8:
        violations.append(SimulationViolation("little_law", f"closure error {result.metrics.little_law_error}"))
    if abs(sum(result.job_tardiness.values()) - result.metrics.total_tardiness) > tolerance:
        violations.append(SimulationViolation("tardiness_accounting", "job tardiness does not close"))
    if set(result.job_completion) != {j.job_id for j in problem.factory.jobs}:
        violations.append(SimulationViolation("job_completion", "not every job completed"))
    return violations
