from __future__ import annotations

from mdt.audit import event_ledger
from mdt.data import load_orlib_instance
from mdt.domain import EventType, ManufacturingEvent


def test_event_ledger_exposes_replayable_state_changes(root):
    factory = load_orlib_instance(root / "data/external/orlib/jobshop1.txt", "ft06")
    events = [
        ManufacturingEvent("audit-release", EventType.JOB_RELEASED, 0.0, job_id="J0"),
        ManufacturingEvent("audit-start", EventType.OPERATION_STARTED, 0.0, job_id="J0", operation_id="J0-O0", machine_id="M2"),
        ManufacturingEvent("audit-complete", EventType.OPERATION_COMPLETED, 1.0, job_id="J0", operation_id="J0-O0", machine_id="M2"),
    ]
    rows = event_ledger(factory, events)
    assert len(rows) == 3
    assert all(row["accepted"] for row in rows)
    assert rows[0]["sequence"] == 1
    assert rows[0]["state_change"]["jobs"][0]["to_status"] == "released"
    assert rows[1]["state_change"]["operations"][0]["to_status"] == "running"
    assert rows[2]["state_change"]["operations"][0]["to_status"] == "complete"
    assert rows[0]["after_state_id"] != rows[1]["after_state_id"]
