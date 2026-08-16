from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from typing import Iterable

from mdt.domain import EventType, FactoryModel, ManufacturingEvent
from mdt.twin import TwinEngine, TwinStateError


CANONICAL_EVENT_COLUMNS = (
    "event_id",
    "event_type",
    "timestamp",
    "job_id",
    "operation_id",
    "machine_id",
    "payload_json",
)


@dataclass(frozen=True)
class EventDataIssue:
    row: int
    severity: str
    code: str
    message: str


@dataclass(frozen=True)
class EventReadinessReport:
    ready: bool
    rows_seen: int
    events_parsed: int
    errors: int
    warnings: int
    issues: tuple[EventDataIssue, ...]
    required_columns: tuple[str, ...] = CANONICAL_EVENT_COLUMNS

    def to_dict(self) -> dict:
        result = asdict(self)
        result["required_columns"] = list(self.required_columns)
        result["issues"] = [asdict(issue) for issue in self.issues]
        return result


class EventCsvError(ValueError):
    def __init__(self, report: EventReadinessReport):
        self.report = report
        super().__init__("event CSV is not ready for replay")


def _cell(row: dict[str, str | None], key: str) -> str:
    return (row.get(key) or "").strip()


def _semantic_reference_issues(factory: FactoryModel, event: ManufacturingEvent, row_number: int) -> list[EventDataIssue]:
    issues: list[EventDataIssue] = []
    job_ids = {j.job_id for j in factory.jobs}
    machine_ids = {m.machine_id for m in factory.machines}
    operation_ids = {op.operation_id for j in factory.jobs for op in j.operations}
    if event.job_id and event.job_id not in job_ids:
        issues.append(EventDataIssue(row_number, "ERROR", "UNKNOWN_JOB", f"unknown job_id {event.job_id}"))
    if event.machine_id and event.machine_id not in machine_ids:
        issues.append(EventDataIssue(row_number, "ERROR", "UNKNOWN_MACHINE", f"unknown machine_id {event.machine_id}"))
    if event.operation_id and event.operation_id not in operation_ids:
        issues.append(EventDataIssue(row_number, "ERROR", "UNKNOWN_OPERATION", f"unknown operation_id {event.operation_id}"))
    return issues


def inspect_event_csv(csv_text: str, factory: FactoryModel) -> tuple[EventReadinessReport, tuple[ManufacturingEvent, ...]]:
    """Parse and validate a canonical historical event CSV without mutating the live twin.

    Validation is intentionally two-layered:
    1. schema/type/reference checks;
    2. replay through a fresh TwinEngine, which catches precedence, machine-state,
       duplicate-ID and chronology violations using the same state semantics as the live twin.
    """
    issues: list[EventDataIssue] = []
    events: list[ManufacturingEvent] = []
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    fieldnames = tuple(reader.fieldnames or ())
    missing = [column for column in CANONICAL_EVENT_COLUMNS if column not in fieldnames]
    if missing:
        issues.append(EventDataIssue(1, "ERROR", "MISSING_COLUMNS", f"missing required columns: {', '.join(missing)}"))
        report = EventReadinessReport(False, 0, 0, 1, 0, tuple(issues))
        return report, tuple()

    seen_ids: set[str] = set()
    rows_seen = 0
    for row_number, row in enumerate(reader, start=2):
        rows_seen += 1
        event_id = _cell(row, "event_id")
        event_type_raw = _cell(row, "event_type")
        timestamp_raw = _cell(row, "timestamp")
        if not event_id:
            issues.append(EventDataIssue(row_number, "ERROR", "MISSING_EVENT_ID", "event_id is required"))
            continue
        if event_id in seen_ids:
            issues.append(EventDataIssue(row_number, "ERROR", "DUPLICATE_EVENT_ID", f"duplicate event_id {event_id}"))
            continue
        seen_ids.add(event_id)
        try:
            event_type = EventType(event_type_raw)
        except ValueError:
            allowed = ", ".join(item.value for item in EventType)
            issues.append(EventDataIssue(row_number, "ERROR", "INVALID_EVENT_TYPE", f"event_type must be one of: {allowed}"))
            continue
        try:
            timestamp = float(timestamp_raw)
        except ValueError:
            issues.append(EventDataIssue(row_number, "ERROR", "INVALID_TIMESTAMP", "timestamp must be numeric"))
            continue
        if timestamp < 0:
            issues.append(EventDataIssue(row_number, "ERROR", "NEGATIVE_TIMESTAMP", "timestamp must be non-negative"))
            continue
        payload_raw = _cell(row, "payload_json")
        if payload_raw:
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError as exc:
                issues.append(EventDataIssue(row_number, "ERROR", "INVALID_PAYLOAD_JSON", f"payload_json is invalid JSON: {exc.msg}"))
                continue
            if not isinstance(payload, dict):
                issues.append(EventDataIssue(row_number, "ERROR", "INVALID_PAYLOAD_TYPE", "payload_json must decode to an object"))
                continue
        else:
            payload = {}
        event = ManufacturingEvent(
            event_id=event_id,
            event_type=event_type,
            timestamp=timestamp,
            job_id=_cell(row, "job_id") or None,
            operation_id=_cell(row, "operation_id") or None,
            machine_id=_cell(row, "machine_id") or None,
            payload=payload,
        )
        ref_issues = _semantic_reference_issues(factory, event, row_number)
        issues.extend(ref_issues)
        if not ref_issues:
            events.append(event)

    # Replay only if all row-level parsing/reference checks passed. This avoids
    # confusing downstream state errors caused by a malformed earlier row.
    if not any(issue.severity == "ERROR" for issue in issues):
        engine = TwinEngine(factory)
        for idx, event in enumerate(events, start=2):
            try:
                engine.apply(event)
            except TwinStateError as exc:
                issues.append(EventDataIssue(idx, "ERROR", "TWIN_STATE_REJECTED", str(exc)))
                break

    errors = sum(issue.severity == "ERROR" for issue in issues)
    warnings = sum(issue.severity == "WARNING" for issue in issues)
    report = EventReadinessReport(
        ready=errors == 0 and bool(events),
        rows_seen=rows_seen,
        events_parsed=len(events),
        errors=errors,
        warnings=warnings,
        issues=tuple(issues),
    )
    return report, tuple(events)


def replay_events(factory: FactoryModel, events: Iterable[ManufacturingEvent]) -> dict:
    engine = TwinEngine(factory)
    snapshot = engine.replay(list(events))
    return {
        "timestamp": snapshot.timestamp,
        "event_count": snapshot.event_count,
        "wip_jobs": snapshot.wip_jobs,
        "completed_jobs": snapshot.completed_jobs,
        "ready_operations": snapshot.ready_operations,
        "machines": {key: asdict(value) for key, value in snapshot.machines.items()},
        "jobs": {key: asdict(value) for key, value in snapshot.jobs.items()},
        "operations": {key: asdict(value) for key, value in snapshot.operations.items()},
    }
