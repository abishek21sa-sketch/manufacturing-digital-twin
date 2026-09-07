from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from mdt.domain import FactoryModel, ManufacturingEvent
from mdt.planning import snapshot_state_id
from mdt.twin import TwinEngine


def _status(value: Any) -> str:
    return getattr(value, "value", str(value))


def _state_changes(before: Any, after: Any) -> dict[str, Any]:
    machines = []
    for machine_id in sorted(after.machines):
        old = before.machines[machine_id]
        new = after.machines[machine_id]
        if asdict(old) != asdict(new):
            machines.append({
                "machine_id": machine_id,
                "from_status": _status(old.status),
                "to_status": _status(new.status),
                "from_active_operation": old.active_operation_id,
                "to_active_operation": new.active_operation_id,
            })
    jobs = []
    for job_id in sorted(after.jobs):
        old = before.jobs[job_id]
        new = after.jobs[job_id]
        if asdict(old) != asdict(new):
            jobs.append({"job_id": job_id, "from_status": _status(old.status), "to_status": _status(new.status)})
    operations = []
    for operation_id in sorted(after.operations):
        old = before.operations[operation_id]
        new = after.operations[operation_id]
        if asdict(old) != asdict(new):
            operations.append({
                "operation_id": operation_id,
                "from_status": _status(old.status),
                "to_status": _status(new.status),
                "started_at": new.started_at,
                "completed_at": new.completed_at,
            })
    return {
        "twin_clock": {"from": before.timestamp, "to": after.timestamp},
        "machines": machines,
        "jobs": jobs,
        "operations": operations,
        "ready_operations": list(after.ready_operations),
    }


def event_ledger(factory: FactoryModel, events: Sequence[ManufacturingEvent]) -> list[dict[str, Any]]:
    """Replay events into an auditable EVENT -> STATE CHANGE -> TWIN ledger."""
    engine = TwinEngine(factory)
    rows: list[dict[str, Any]] = []
    for sequence, event in enumerate(events, start=1):
        before = engine.snapshot()
        try:
            after = engine.apply(event)
            rows.append({
                "sequence": sequence,
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "event_type": event.event_type.value,
                "job_id": event.job_id,
                "operation_id": event.operation_id,
                "machine_id": event.machine_id,
                "source": event.payload.get("source", "event-ledger"),
                "provenance": event.payload.get("provenance", "persisted manufacturing event"),
                "accepted": True,
                "before_state_id": snapshot_state_id(before),
                "after_state_id": snapshot_state_id(after),
                "state_change": _state_changes(before, after),
            })
        except Exception as exc:  # defensive path for imported/corrupt ledgers
            rows.append({
                "sequence": sequence,
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "event_type": event.event_type.value,
                "job_id": event.job_id,
                "operation_id": event.operation_id,
                "machine_id": event.machine_id,
                "source": event.payload.get("source", "event-ledger"),
                "provenance": event.payload.get("provenance", "persisted manufacturing event"),
                "accepted": False,
                "before_state_id": snapshot_state_id(before),
                "after_state_id": snapshot_state_id(before),
                "state_change": {},
                "rejection_reason": str(exc),
            })
            break
    return rows
