from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json

from mdt.domain import (
    FactoryModel,
    JobSpec,
    MachineStatus,
    OperationSpec,
    OperationStatus,
    TwinSnapshot,
)
from mdt.optimization.model import PlanningJob, ScheduledOperation


class PlanningStateNotReady(ValueError):
    """Raised when the synchronized twin lacks information required for a defensible plan."""


@dataclass(frozen=True)
class TwinPlanningState:
    current_time: float
    residual_factory: FactoryModel
    planning_jobs: tuple[PlanningJob, ...]
    machine_available_from: dict[str, float]
    frozen_operations: tuple[ScheduledOperation, ...] = ()
    projected_frozen_job_completion: dict[str, float] = field(default_factory=dict)
    completed_operation_ids: tuple[str, ...] = ()
    completed_job_ids: tuple[str, ...] = ()
    source_event_count: int = 0
    source_state_id: str = ""
    assumptions: tuple[str, ...] = ()

    @property
    def schedulable_jobs(self) -> int:
        return len(self.residual_factory.jobs)

    @property
    def schedulable_operations(self) -> int:
        return self.residual_factory.operation_count


def _state_id(snapshot: TwinSnapshot) -> str:
    payload = {
        "timestamp": snapshot.timestamp,
        "event_count": snapshot.event_count,
        "machines": {
            key: {
                "status": value.status.value,
                "active_operation_id": value.active_operation_id,
                "down_since": value.down_since,
                "accumulated_downtime": value.accumulated_downtime,
            }
            for key, value in sorted(snapshot.machines.items())
        },
        "operations": {
            key: {
                "status": value.status.value,
                "started_at": value.started_at,
                "completed_at": value.completed_at,
            }
            for key, value in sorted(snapshot.operations.items())
        },
        "jobs": {
            key: {
                "status": value.status.value,
                "released_at": value.released_at,
                "completed_at": value.completed_at,
            }
            for key, value in sorted(snapshot.jobs.items())
        },
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def planning_state_from_twin(
    factory: FactoryModel,
    snapshot: TwinSnapshot,
    *,
    due_factor: float = 1.5,
    down_machine_recovery: dict[str, float] | None = None,
) -> TwinPlanningState:
    """Translate the synchronized event-sourced twin into a residual scheduling state.

    Completed operations are removed from the residual problem. Operations already
    running are frozen at their observed start and projected to finish after their
    remaining nominal processing time. Their machine is unavailable until that
    projected finish. A machine that is currently DOWN requires an explicit
    recovery timestamp; the planner refuses to silently invent one.
    """

    if due_factor <= 0:
        raise ValueError("due_factor must be positive")
    recovery = down_machine_recovery or {}
    known_machines = {m.machine_id for m in factory.machines}
    unknown = set(recovery) - known_machines
    if unknown:
        raise ValueError(f"unknown down-machine recovery assumptions: {sorted(unknown)}")

    current = float(snapshot.timestamp)
    machine_available = {machine_id: current for machine_id in known_machines}
    assumptions: list[str] = []
    frozen: list[ScheduledOperation] = []
    projected_completion: dict[str, float] = {}
    completed_ops: list[str] = []
    completed_jobs: list[str] = []

    # First, account for current resource state.
    for machine_id, runtime in snapshot.machines.items():
        if runtime.status == MachineStatus.DOWN:
            if machine_id not in recovery:
                raise PlanningStateNotReady(
                    f"machine {machine_id} is DOWN at twin time {current}; provide an explicit recovery timestamp"
                )
            recovery_time = float(recovery[machine_id])
            if recovery_time < current:
                raise PlanningStateNotReady(f"recovery timestamp for {machine_id} is before current twin time")
            machine_available[machine_id] = recovery_time
            assumptions.append(f"{machine_id} assumed available at t={recovery_time:g} from explicit recovery input")

    residual_jobs: list[JobSpec] = []
    planning_jobs: list[PlanningJob] = []

    for job in factory.jobs:
        runtime_job = snapshot.jobs[job.job_id]
        if runtime_job.completed_at is not None:
            completed_jobs.append(job.job_id)

        remaining_ops: list[OperationSpec] = []
        predecessor_ready = current
        running_projection: float | None = None

        for op in job.operations:
            runtime_op = snapshot.operations[op.operation_id]
            if runtime_op.status == OperationStatus.COMPLETE:
                completed_ops.append(op.operation_id)
                predecessor_ready = max(predecessor_ready, float(runtime_op.completed_at or current))
                continue

            if runtime_op.status == OperationStatus.RUNNING:
                if runtime_op.started_at is None:
                    raise PlanningStateNotReady(f"running operation {op.operation_id} has no observed start time")
                nominal_finish = float(runtime_op.started_at + op.processing_time)
                if nominal_finish + 1e-9 < current:
                    raise PlanningStateNotReady(
                        f"running operation {op.operation_id} exceeded nominal finish t={nominal_finish:g} without a completion event"
                    )
                frozen.append(
                    ScheduledOperation(
                        operation_id=op.operation_id,
                        job_id=op.job_id,
                        machine_id=op.machine_id,
                        sequence=op.sequence,
                        start=float(runtime_op.started_at),
                        finish=nominal_finish,
                    )
                )
                machine_available[op.machine_id] = max(machine_available[op.machine_id], nominal_finish)
                predecessor_ready = max(predecessor_ready, nominal_finish)
                running_projection = nominal_finish
                continue

            # NOT_READY/READY work remains a decision variable.
            remaining_ops.append(op)

        if not remaining_ops:
            if running_projection is not None:
                projected_completion[job.job_id] = running_projection
            continue

        residual_jobs.append(
            JobSpec(
                job_id=job.job_id,
                operations=tuple(remaining_ops),
                release_time=max(current, job.release_time, predecessor_ready),
                due_time=job.due_time,
            )
        )
        original_work = sum(op.processing_time for op in job.operations)
        due = float(job.due_time) if job.due_time is not None else float(job.release_time + due_factor * original_work)
        planning_jobs.append(
            PlanningJob(
                job_id=job.job_id,
                release_time=max(current, job.release_time, predecessor_ready),
                due_time=due,
            )
        )

    residual = FactoryModel(
        factory_id=f"{factory.factory_id}-residual-{_state_id(snapshot)}",
        machines=factory.machines,
        jobs=tuple(residual_jobs),
        source=factory.source,
        source_kind=f"{factory.source_kind}+synchronized_twin_residual",
        metadata={
            **factory.metadata,
            "twin_timestamp": current,
            "twin_event_count": snapshot.event_count,
            "twin_state_id": _state_id(snapshot),
        },
    )
    assumptions.append("running operations use nominal remaining processing time until plant-calibrated remaining-time estimates are available")
    return TwinPlanningState(
        current_time=current,
        residual_factory=residual,
        planning_jobs=tuple(planning_jobs),
        machine_available_from=machine_available,
        frozen_operations=tuple(frozen),
        projected_frozen_job_completion=projected_completion,
        completed_operation_ids=tuple(sorted(completed_ops)),
        completed_job_ids=tuple(sorted(completed_jobs)),
        source_event_count=snapshot.event_count,
        source_state_id=_state_id(snapshot),
        assumptions=tuple(assumptions),
    )
