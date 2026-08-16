from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MachineStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    DOWN = "down"


class OperationStatus(str, Enum):
    NOT_READY = "not_ready"
    READY = "ready"
    RUNNING = "running"
    COMPLETE = "complete"


class JobStatus(str, Enum):
    UNRELEASED = "unreleased"
    RELEASED = "released"
    IN_PROCESS = "in_process"
    COMPLETE = "complete"


class EventType(str, Enum):
    JOB_RELEASED = "job_released"
    OPERATION_STARTED = "operation_started"
    OPERATION_COMPLETED = "operation_completed"
    MACHINE_DOWN = "machine_down"
    MACHINE_UP = "machine_up"


class HumanDisposition(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class MachineSpec:
    machine_id: str
    name: str


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    job_id: str
    sequence: int
    machine_id: str
    processing_time: float


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    operations: tuple[OperationSpec, ...]
    release_time: float = 0.0
    due_time: float | None = None


@dataclass(frozen=True)
class FactoryModel:
    factory_id: str
    machines: tuple[MachineSpec, ...]
    jobs: tuple[JobSpec, ...]
    source: str
    source_kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def operation_count(self) -> int:
        return sum(len(job.operations) for job in self.jobs)

    @property
    def total_work(self) -> float:
        return sum(op.processing_time for job in self.jobs for op in job.operations)

    def machine(self, machine_id: str) -> MachineSpec:
        return next(m for m in self.machines if m.machine_id == machine_id)

    def job(self, job_id: str) -> JobSpec:
        return next(j for j in self.jobs if j.job_id == job_id)

    def operation(self, operation_id: str) -> OperationSpec:
        for job in self.jobs:
            for op in job.operations:
                if op.operation_id == operation_id:
                    return op
        raise KeyError(operation_id)


@dataclass(frozen=True)
class ManufacturingEvent:
    event_id: str
    event_type: EventType
    timestamp: float
    job_id: str | None = None
    operation_id: str | None = None
    machine_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class MachineRuntime:
    machine_id: str
    status: MachineStatus = MachineStatus.IDLE
    active_operation_id: str | None = None
    last_change_time: float = 0.0
    down_since: float | None = None
    accumulated_downtime: float = 0.0


@dataclass
class OperationRuntime:
    operation_id: str
    status: OperationStatus = OperationStatus.NOT_READY
    started_at: float | None = None
    completed_at: float | None = None


@dataclass
class JobRuntime:
    job_id: str
    status: JobStatus = JobStatus.UNRELEASED
    released_at: float | None = None
    completed_at: float | None = None


@dataclass
class TwinSnapshot:
    timestamp: float
    machines: dict[str, MachineRuntime]
    operations: dict[str, OperationRuntime]
    jobs: dict[str, JobRuntime]
    event_count: int
    wip_jobs: int
    completed_jobs: int
    ready_operations: list[str]
