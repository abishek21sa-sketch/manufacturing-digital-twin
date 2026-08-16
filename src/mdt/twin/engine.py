from __future__ import annotations

from copy import deepcopy

from mdt.domain import (
    EventType,
    FactoryModel,
    JobRuntime,
    JobStatus,
    MachineRuntime,
    MachineStatus,
    ManufacturingEvent,
    OperationRuntime,
    OperationStatus,
    TwinSnapshot,
)


class TwinStateError(ValueError):
    pass


class TwinEngine:
    def __init__(self, model: FactoryModel):
        self.model = model
        self.machines = {m.machine_id: MachineRuntime(m.machine_id) for m in model.machines}
        self.operations = {
            op.operation_id: OperationRuntime(op.operation_id)
            for job in model.jobs
            for op in job.operations
        }
        self.jobs = {job.job_id: JobRuntime(job.job_id) for job in model.jobs}
        self.timestamp = 0.0
        self.event_ids: set[str] = set()
        self.event_count = 0

    def _job_ops(self, job_id: str):
        return self.model.job(job_id).operations

    def _refresh_readiness(self, job_id: str) -> None:
        job_state = self.jobs[job_id]
        if job_state.status == JobStatus.UNRELEASED:
            return
        ops = self._job_ops(job_id)
        for idx, spec in enumerate(ops):
            runtime = self.operations[spec.operation_id]
            if runtime.status in (OperationStatus.RUNNING, OperationStatus.COMPLETE):
                continue
            previous_complete = idx == 0 or self.operations[ops[idx - 1].operation_id].status == OperationStatus.COMPLETE
            runtime.status = OperationStatus.READY if previous_complete else OperationStatus.NOT_READY

    def apply(self, event: ManufacturingEvent) -> TwinSnapshot:
        if event.event_id in self.event_ids:
            raise TwinStateError(f"duplicate event ID {event.event_id}")
        if event.timestamp < self.timestamp:
            raise TwinStateError("event timestamp moved backwards")
        if event.timestamp < 0:
            raise TwinStateError("negative event timestamp")

        handler = {
            EventType.JOB_RELEASED: self._release_job,
            EventType.OPERATION_STARTED: self._start_operation,
            EventType.OPERATION_COMPLETED: self._complete_operation,
            EventType.MACHINE_DOWN: self._machine_down,
            EventType.MACHINE_UP: self._machine_up,
        }[event.event_type]
        handler(event)
        self.timestamp = event.timestamp
        self.event_ids.add(event.event_id)
        self.event_count += 1
        return self.snapshot()

    def replay(self, events: list[ManufacturingEvent]) -> TwinSnapshot:
        for event in events:
            self.apply(event)
        return self.snapshot()

    def _release_job(self, event: ManufacturingEvent) -> None:
        if not event.job_id or event.job_id not in self.jobs:
            raise TwinStateError("job_released requires a known job_id")
        state = self.jobs[event.job_id]
        if state.status != JobStatus.UNRELEASED:
            raise TwinStateError(f"job {event.job_id} already released")
        spec = self.model.job(event.job_id)
        if event.timestamp < spec.release_time:
            raise TwinStateError(f"job {event.job_id} released before configured release time")
        state.status = JobStatus.RELEASED
        state.released_at = event.timestamp
        self._refresh_readiness(event.job_id)

    def _start_operation(self, event: ManufacturingEvent) -> None:
        if not event.operation_id or event.operation_id not in self.operations:
            raise TwinStateError("operation_started requires a known operation_id")
        spec = self.model.operation(event.operation_id)
        job_state = self.jobs[spec.job_id]
        op_state = self.operations[event.operation_id]
        machine_id = event.machine_id or spec.machine_id
        if machine_id != spec.machine_id:
            raise TwinStateError("operation assigned to incompatible machine")
        machine = self.machines[machine_id]
        if job_state.status == JobStatus.UNRELEASED:
            raise TwinStateError("cannot start operation before job release")
        self._refresh_readiness(spec.job_id)
        if op_state.status != OperationStatus.READY:
            raise TwinStateError("operation is not precedence-ready")
        if machine.status != MachineStatus.IDLE or machine.active_operation_id is not None:
            raise TwinStateError("machine is not available")
        op_state.status = OperationStatus.RUNNING
        op_state.started_at = event.timestamp
        machine.status = MachineStatus.BUSY
        machine.active_operation_id = event.operation_id
        machine.last_change_time = event.timestamp
        job_state.status = JobStatus.IN_PROCESS

    def _complete_operation(self, event: ManufacturingEvent) -> None:
        if not event.operation_id or event.operation_id not in self.operations:
            raise TwinStateError("operation_completed requires a known operation_id")
        spec = self.model.operation(event.operation_id)
        machine_id = event.machine_id or spec.machine_id
        if machine_id != spec.machine_id:
            raise TwinStateError("completion reported for incompatible machine")
        machine = self.machines[machine_id]
        op_state = self.operations[event.operation_id]
        if op_state.status != OperationStatus.RUNNING:
            raise TwinStateError("cannot complete an operation that is not running")
        if machine.active_operation_id != event.operation_id:
            raise TwinStateError("machine active operation does not match completion")
        if machine.status != MachineStatus.BUSY:
            raise TwinStateError("cannot complete while machine is not operational")
        op_state.status = OperationStatus.COMPLETE
        op_state.completed_at = event.timestamp
        machine.status = MachineStatus.IDLE
        machine.active_operation_id = None
        machine.last_change_time = event.timestamp
        job_ops = self._job_ops(spec.job_id)
        if all(self.operations[op.operation_id].status == OperationStatus.COMPLETE for op in job_ops):
            self.jobs[spec.job_id].status = JobStatus.COMPLETE
            self.jobs[spec.job_id].completed_at = event.timestamp
        else:
            self.jobs[spec.job_id].status = JobStatus.IN_PROCESS
            self._refresh_readiness(spec.job_id)

    def _machine_down(self, event: ManufacturingEvent) -> None:
        if not event.machine_id or event.machine_id not in self.machines:
            raise TwinStateError("machine_down requires a known machine_id")
        machine = self.machines[event.machine_id]
        if machine.status == MachineStatus.DOWN:
            raise TwinStateError("machine already down")
        if machine.active_operation_id is not None:
            raise TwinStateError("event-ledger state does not allow machine-down while an operation is actively running; interruption behavior is modeled by the stochastic DES")
        machine.status = MachineStatus.DOWN
        machine.down_since = event.timestamp
        machine.last_change_time = event.timestamp

    def _machine_up(self, event: ManufacturingEvent) -> None:
        if not event.machine_id or event.machine_id not in self.machines:
            raise TwinStateError("machine_up requires a known machine_id")
        machine = self.machines[event.machine_id]
        if machine.status != MachineStatus.DOWN or machine.down_since is None:
            raise TwinStateError("machine is not down")
        machine.accumulated_downtime += event.timestamp - machine.down_since
        machine.down_since = None
        machine.status = MachineStatus.IDLE
        machine.last_change_time = event.timestamp

    def snapshot(self) -> TwinSnapshot:
        wip = sum(1 for j in self.jobs.values() if j.status in (JobStatus.RELEASED, JobStatus.IN_PROCESS))
        completed = sum(1 for j in self.jobs.values() if j.status == JobStatus.COMPLETE)
        ready = sorted(op.operation_id for op in self.operations.values() if op.status == OperationStatus.READY)
        return TwinSnapshot(
            timestamp=self.timestamp,
            machines=deepcopy(self.machines),
            operations=deepcopy(self.operations),
            jobs=deepcopy(self.jobs),
            event_count=self.event_count,
            wip_jobs=wip,
            completed_jobs=completed,
            ready_operations=ready,
        )
