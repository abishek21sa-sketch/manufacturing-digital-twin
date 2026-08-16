from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from mdt.optimization.model import ScheduleProblem


DispatchRule = Literal["SPT", "EDD", "FIFO", "PLANNED"]


@dataclass(frozen=True)
class ReliabilitySpec:
    """Machine reliability inputs for synthetic future-state simulation.

    MTBF is measured in productive operating-time units. MTTR is calendar-time
    repair duration. ``None`` MTBF disables failures for the machine.
    """

    mtbf: float | None = 120.0
    mttr: float = 8.0

    def validate(self) -> None:
        if self.mtbf is not None and self.mtbf <= 0:
            raise ValueError("mtbf must be positive or None")
        if self.mttr <= 0:
            raise ValueError("mttr must be positive")


@dataclass(frozen=True)
class SimulationConfig:
    seed: int = 20260815
    processing_cv: float = 0.10
    reliability: ReliabilitySpec = field(default_factory=ReliabilitySpec)
    machine_reliability: dict[str, ReliabilitySpec] = field(default_factory=dict)
    wip_cap: int | None = None
    max_events: int = 100_000
    record_events: bool = True

    def validate(self, problem: ScheduleProblem) -> None:
        if self.processing_cv < 0 or self.processing_cv > 1.0:
            raise ValueError("processing_cv must be in [0, 1]")
        if self.max_events <= problem.factory.operation_count:
            raise ValueError("max_events is too small for the factory")
        if self.wip_cap is not None and self.wip_cap <= 0:
            raise ValueError("wip_cap must be positive or None")
        self.reliability.validate()
        known = {m.machine_id for m in problem.factory.machines}
        unknown = set(self.machine_reliability) - known
        if unknown:
            raise ValueError(f"unknown machine reliability overrides: {sorted(unknown)}")
        for spec in self.machine_reliability.values():
            spec.validate()

    def reliability_for(self, machine_id: str) -> ReliabilitySpec:
        return self.machine_reliability.get(machine_id, self.reliability)


@dataclass(frozen=True)
class PolicySpec:
    name: str
    rule: DispatchRule
    planned_start: dict[str, float] = field(default_factory=dict)

    def validate(self, problem: ScheduleProblem) -> None:
        if self.rule not in {"SPT", "EDD", "FIFO", "PLANNED"}:
            raise ValueError(f"unsupported dispatch rule {self.rule}")
        if not self.name.strip():
            raise ValueError("policy name is required")
        if self.rule == "PLANNED":
            required = {op.operation_id for job in problem.factory.jobs for op in job.operations}
            if set(self.planned_start) != required:
                raise ValueError("PLANNED policy requires a start-time priority for every operation")


@dataclass(frozen=True)
class SimulationEvent:
    time: float
    kind: str
    job_id: str | None = None
    operation_id: str | None = None
    machine_id: str | None = None
    detail: dict[str, float | str | int] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessingSegment:
    operation_id: str
    job_id: str
    machine_id: str
    start: float
    finish: float


@dataclass(frozen=True)
class DowntimeInterval:
    machine_id: str
    start: float
    finish: float
    cause: str = "stochastic_failure"


@dataclass(frozen=True)
class SimulatedOperation:
    operation_id: str
    job_id: str
    machine_id: str
    sequence: int
    nominal_processing: float
    realized_processing: float
    start: float
    finish: float
    interruptions: int


@dataclass(frozen=True)
class SimulationMetrics:
    makespan: float
    total_tardiness: float
    mean_tardiness: float
    late_jobs: int
    service_level: float
    mean_flow_time: float
    throughput_rate: float
    average_wip: float
    little_law_rhs: float
    little_law_error: float
    mean_machine_utilization: float
    total_downtime: float


@dataclass(frozen=True)
class SimulationResult:
    seed: int
    policy: str
    operations: tuple[SimulatedOperation, ...]
    processing_segments: tuple[ProcessingSegment, ...]
    downtime_intervals: tuple[DowntimeInterval, ...]
    events: tuple[SimulationEvent, ...]
    job_completion: dict[str, float]
    job_tardiness: dict[str, float]
    machine_productive_time: dict[str, float]
    machine_downtime: dict[str, float]
    metrics: SimulationMetrics


@dataclass(frozen=True)
class MonteCarloSummary:
    policy: str
    replications: int
    base_seed: int
    mean_makespan: float
    p95_makespan: float
    mean_total_tardiness: float
    p95_total_tardiness: float
    cvar95_total_tardiness: float
    mean_service_level: float
    probability_any_late: float
    mean_flow_time: float
    mean_average_wip: float
    mean_machine_utilization: float
    makespan_mean_ci95_half_width: float
    tardiness_mean_ci95_half_width: float
    robust_score: float
    seeds: tuple[int, ...]
    total_tardiness_scenarios: tuple[float, ...] = ()


@dataclass(frozen=True)
class StressTestResult:
    evidence_label: str
    objective: str
    summaries: tuple[MonteCarloSummary, ...]
    recommended_policy: str
    recommendation_rationale: str
    nominal_solver: dict[str, object]
    nominal_schedule_violations: tuple[dict[str, str], ...]
    stochastic_policy_selection: dict[str, object] = field(default_factory=dict)
