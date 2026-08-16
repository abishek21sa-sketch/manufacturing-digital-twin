from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from mdt.domain import FactoryModel, JobSpec, OperationSpec
from .model import ObjectiveWeights, ScheduleProblem, ScheduleResult
from .solver import solve_schedule
from .validation import assess_schedule, validate_schedule


@dataclass(frozen=True)
class BoxRobustnessSpec:
    """Bounded processing-time uncertainty used by the robust counterpart.

    If operation processing time is p, the robust schedule is constructed against
    p * (1 + delta_m) on machine m. The resulting fixed schedule therefore
    remains feasible for any simultaneous realization inside those independent
    upper bounds, assuming no additional disruptions beyond those modeled bounds.
    """

    default_relative_buffer: float = 0.10
    machine_relative_buffer: dict[str, float] | None = None

    def validate(self, factory: FactoryModel) -> None:
        if self.default_relative_buffer < 0 or self.default_relative_buffer > 1.0:
            raise ValueError("default_relative_buffer must be in [0, 1]")
        override = self.machine_relative_buffer or {}
        known = {m.machine_id for m in factory.machines}
        unknown = set(override) - known
        if unknown:
            raise ValueError(f"unknown machine uncertainty buffers: {sorted(unknown)}")
        if any(value < 0 or value > 1.0 for value in override.values()):
            raise ValueError("machine uncertainty buffers must be in [0, 1]")

    def buffer_for(self, machine_id: str) -> float:
        return float((self.machine_relative_buffer or {}).get(machine_id, self.default_relative_buffer))


@dataclass(frozen=True)
class RobustScheduleEvidence:
    uncertainty_set: str
    default_relative_buffer: float
    machine_relative_buffer: dict[str, float]
    solver_status: str
    feasible_incumbent: bool
    optimality_proven: bool
    robust_violations: int


@dataclass(frozen=True)
class RobustScheduleResult:
    robust_problem: ScheduleProblem
    schedule: ScheduleResult
    evidence: RobustScheduleEvidence


def robustify_factory(factory: FactoryModel, spec: BoxRobustnessSpec) -> FactoryModel:
    spec.validate(factory)
    jobs = []
    for job in factory.jobs:
        operations = tuple(
            OperationSpec(
                operation_id=op.operation_id,
                job_id=op.job_id,
                sequence=op.sequence,
                machine_id=op.machine_id,
                processing_time=op.processing_time * (1.0 + spec.buffer_for(op.machine_id)),
            )
            for op in job.operations
        )
        jobs.append(JobSpec(job.job_id, operations, job.release_time, job.due_time))
    return FactoryModel(
        factory_id=f"{factory.factory_id}-box-robust",
        machines=factory.machines,
        jobs=tuple(jobs),
        source=factory.source,
        source_kind=f"{factory.source_kind}+box_robust_counterpart",
        metadata={**factory.metadata, "uncertainty_set": "independent processing-time box"},
    )


def solve_box_robust_schedule(
    problem: ScheduleProblem,
    robustness: BoxRobustnessSpec,
    *,
    backend: str = "auto",
    time_limit: float = 30.0,
    mip_gap: float = 0.0,
) -> RobustScheduleResult:
    robust_factory = robustify_factory(problem.factory, robustness)
    robust_problem = ScheduleProblem(
        robust_factory,
        problem.jobs,
        problem.objective,
        current_time=problem.current_time,
        machine_available_from=dict(problem.machine_available_from),
        # A nominal no-regret tardiness cap is not transferred blindly to a
        # processing-time upper-bound counterpart; uncertainty can make that
        # nominal cap physically infeasible. Robust performance is compared
        # explicitly in the decision/stress-test layer instead.
        max_total_tardiness=None,
    )
    schedule = solve_schedule(robust_problem, backend=backend, time_limit=time_limit, mip_gap=mip_gap)
    assessment = assess_schedule(robust_problem, schedule)
    violations = assessment.violations
    return RobustScheduleResult(
        robust_problem,
        schedule,
        RobustScheduleEvidence(
            uncertainty_set="box uncertainty: each processing time may increase independently up to its configured relative buffer",
            default_relative_buffer=robustness.default_relative_buffer,
            machine_relative_buffer=dict(robustness.machine_relative_buffer or {}),
            solver_status=schedule.evidence.status,
            feasible_incumbent=assessment.feasible,
            optimality_proven=assessment.optimality_proven,
            robust_violations=len(violations),
        ),
    )


@dataclass(frozen=True)
class ParetoPoint:
    makespan_weight: float
    tardiness_weight: float
    risk_tardiness_weight: float
    makespan: float
    total_tardiness: float
    risk_weighted_tardiness: float
    backend: str
    status: str
    objective_value: float | None
    optimality_proven: bool


def pareto_schedule_frontier(
    problem: ScheduleProblem,
    *,
    backend: str = "auto",
    weight_grid: Iterable[tuple[float, float]] = ((1.0, 0.0), (0.25, 1.0), (0.05, 1.0), (0.01, 1.0), (0.0, 1.0)),
    risk_tardiness_weight: float = 1.0,
    time_limit: float = 30.0,
) -> tuple[ParetoPoint, ...]:
    """Return validated nondominated candidate schedules from scalarized MILPs.

    A solver can legitimately stop at TIME_LIMIT with a feasible incumbent.
    Such an incumbent is useful for a decision workbench if it independently
    passes schedule validation, but it must not be mislabeled as an optimal
    Pareto point. ``status`` therefore preserves the solver termination state
    and ``optimality_proven`` is true only for OPTIMAL solves.

    Nondominance is evaluated over the three quantities the scalarizations
    actually trade: makespan, aggregate tardiness, and risk-weighted
    tardiness. The returned set is a frontier over the validated candidate
    schedules; global Pareto optimality is claimed only point-by-point when
    the underlying solve is OPTIMAL.
    """
    if time_limit <= 0:
        raise ValueError("time_limit must be positive")
    points: list[ParetoPoint] = []
    for makespan_weight, tardiness_weight in weight_grid:
        if makespan_weight < 0 or tardiness_weight < 0:
            raise ValueError("Pareto weights must be non-negative")
        if makespan_weight == 0 and tardiness_weight == 0 and risk_tardiness_weight == 0:
            raise ValueError("Pareto scalarization cannot have all-zero weights")
        candidate_problem = replace(
            problem,
            objective=ObjectiveWeights(makespan_weight, tardiness_weight, risk_tardiness_weight),
        )
        result = solve_schedule(candidate_problem, backend=backend, time_limit=time_limit, mip_gap=0.0)
        # All solver-status interpretation is centralized in assess_schedule.
        # TIME_LIMIT incumbents are admitted only when complete and physically
        # feasible; their termination status remains TIME_LIMIT.
        assessment = assess_schedule(candidate_problem, result)
        if not assessment.feasible:
            continue
        points.append(
            ParetoPoint(
                makespan_weight=float(makespan_weight),
                tardiness_weight=float(tardiness_weight),
                risk_tardiness_weight=float(risk_tardiness_weight),
                makespan=float(result.makespan or 0.0),
                total_tardiness=float(sum(result.job_tardiness.values())),
                risk_weighted_tardiness=float(result.objective_components.get("risk_weighted_tardiness", 0.0)),
                backend=result.evidence.backend,
                status=result.evidence.status,
                objective_value=result.evidence.objective_value,
                optimality_proven=assessment.optimality_proven,
            )
        )

    tolerance = 1e-7

    # Deduplicate numerically equivalent objective triples, preferring an
    # optimality-proven representative over a merely feasible incumbent.
    unique: list[ParetoPoint] = []
    for point in sorted(
        points,
        key=lambda p: (
            p.makespan,
            p.total_tardiness,
            p.risk_weighted_tardiness,
            0 if p.optimality_proven else 1,
        ),
    ):
        match = next(
            (
                other
                for other in unique
                if abs(point.makespan - other.makespan) <= tolerance
                and abs(point.total_tardiness - other.total_tardiness) <= tolerance
                and abs(point.risk_weighted_tardiness - other.risk_weighted_tardiness) <= tolerance
            ),
            None,
        )
        if match is None:
            unique.append(point)
        elif point.optimality_proven and not match.optimality_proven:
            unique[unique.index(match)] = point

    nondominated: list[ParetoPoint] = []
    for point in unique:
        dominated = any(
            other is not point
            and other.makespan <= point.makespan + tolerance
            and other.total_tardiness <= point.total_tardiness + tolerance
            and other.risk_weighted_tardiness <= point.risk_weighted_tardiness + tolerance
            and (
                other.makespan < point.makespan - tolerance
                or other.total_tardiness < point.total_tardiness - tolerance
                or other.risk_weighted_tardiness < point.risk_weighted_tardiness - tolerance
            )
            for other in unique
        )
        if not dominated:
            nondominated.append(point)
    return tuple(
        sorted(
            nondominated,
            key=lambda p: (p.makespan, p.total_tardiness, p.risk_weighted_tardiness),
        )
    )
