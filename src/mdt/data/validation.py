from __future__ import annotations

from mdt.domain import FactoryModel


class FactoryValidationError(ValueError):
    pass


def validate_factory_model(model: FactoryModel) -> None:
    machine_ids = [m.machine_id for m in model.machines]
    if len(machine_ids) != len(set(machine_ids)):
        raise FactoryValidationError("duplicate machine IDs")
    if not machine_ids:
        raise FactoryValidationError("factory must contain at least one machine")

    job_ids = [j.job_id for j in model.jobs]
    if len(job_ids) != len(set(job_ids)):
        raise FactoryValidationError("duplicate job IDs")
    if not job_ids:
        raise FactoryValidationError("factory must contain at least one job")

    known_machines = set(machine_ids)
    operation_ids: set[str] = set()
    for job in model.jobs:
        if job.release_time < 0:
            raise FactoryValidationError(f"negative release time for {job.job_id}")
        if job.due_time is not None and job.due_time < job.release_time:
            raise FactoryValidationError(f"due time precedes release for {job.job_id}")
        sequences = [op.sequence for op in job.operations]
        if sequences != list(range(len(job.operations))):
            raise FactoryValidationError(f"non-contiguous operation sequence for {job.job_id}")
        for op in job.operations:
            if op.operation_id in operation_ids:
                raise FactoryValidationError(f"duplicate operation ID {op.operation_id}")
            operation_ids.add(op.operation_id)
            if op.job_id != job.job_id:
                raise FactoryValidationError(f"operation/job mismatch for {op.operation_id}")
            if op.machine_id not in known_machines:
                raise FactoryValidationError(f"unknown machine {op.machine_id} for {op.operation_id}")
            if op.processing_time <= 0:
                raise FactoryValidationError(f"non-positive processing time for {op.operation_id}")
