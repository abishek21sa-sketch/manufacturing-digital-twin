from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from mdt.domain import FactoryModel


@dataclass(frozen=True)
class PlanningJob:
    job_id: str
    release_time: float
    due_time: float
    priority_weight: float = 1.0
    risk_score: float = 0.0


@dataclass(frozen=True)
class ObjectiveWeights:
    makespan: float = 1.0
    tardiness: float = 0.0
    risk_tardiness: float = 0.0

    def validate(self) -> None:
        if self.makespan < 0 or self.tardiness < 0 or self.risk_tardiness < 0:
            raise ValueError("objective weights must be non-negative")
        if self.makespan + self.tardiness + self.risk_tardiness <= 0:
            raise ValueError("at least one objective weight must be positive")


@dataclass(frozen=True)
class ScheduleProblem:
    factory: FactoryModel
    jobs: tuple[PlanningJob, ...]
    objective: ObjectiveWeights = field(default_factory=ObjectiveWeights)
    current_time: float = 0.0
    machine_available_from: dict[str, float] = field(default_factory=dict)
    max_total_tardiness: float | None = None

    def validate(self) -> None:
        self.objective.validate()
        ids = {j.job_id for j in self.factory.jobs}
        planning_ids = {j.job_id for j in self.jobs}
        if ids != planning_ids:
            raise ValueError("planning jobs must match factory jobs exactly")
        if self.current_time < 0:
            raise ValueError("current_time must be non-negative")
        known_machines = {m.machine_id for m in self.factory.machines}
        unknown_machine_availability = set(self.machine_available_from) - known_machines
        if unknown_machine_availability:
            raise ValueError(f"unknown machine availability entries: {sorted(unknown_machine_availability)}")
        for machine_id, available_from in self.machine_available_from.items():
            if available_from < self.current_time:
                raise ValueError(f"machine {machine_id} availability precedes current_time")
        if self.max_total_tardiness is not None and self.max_total_tardiness < 0:
            raise ValueError("max_total_tardiness must be non-negative when provided")
        for job in self.jobs:
            if job.release_time < 0 or job.due_time < job.release_time:
                raise ValueError(f"invalid planning times for {job.job_id}")
            if job.priority_weight <= 0:
                raise ValueError("priority weights must be positive")
            if not 0 <= job.risk_score <= 1:
                raise ValueError("risk_score must be in [0, 1]")

    def planning_job(self, job_id: str) -> PlanningJob:
        return next(j for j in self.jobs if j.job_id == job_id)

    def machine_ready_time(self, machine_id: str) -> float:
        return max(self.current_time, float(self.machine_available_from.get(machine_id, self.current_time)))


@dataclass(frozen=True)
class ScheduledOperation:
    operation_id: str
    job_id: str
    machine_id: str
    sequence: int
    start: float
    finish: float


@dataclass(frozen=True)
class SolverEvidence:
    backend: str
    status: Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNBOUNDED", "TIME_LIMIT", "ERROR"]
    objective_value: float | None
    best_bound: float | None
    mip_gap: float | None
    solve_time_seconds: float
    raw_status: str


@dataclass(frozen=True)
class ScheduleResult:
    operations: tuple[ScheduledOperation, ...]
    job_completion: dict[str, float]
    job_tardiness: dict[str, float]
    makespan: float | None
    evidence: SolverEvidence
    objective_components: dict[str, float]


def default_planning_jobs(factory: FactoryModel, due_factor: float = 3.0) -> tuple[PlanningJob, ...]:
    if due_factor <= 0:
        raise ValueError("due_factor must be positive")
    jobs: list[PlanningJob] = []
    for spec in factory.jobs:
        work = sum(op.processing_time for op in spec.operations)
        release = max(0.0, spec.release_time)
        jobs.append(PlanningJob(spec.job_id, release, release + due_factor * work))
    return tuple(jobs)
