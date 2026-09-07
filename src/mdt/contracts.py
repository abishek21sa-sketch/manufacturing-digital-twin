from __future__ import annotations

from mdt.domain import EventType


EVENT_CONTRACT_NAME = "mdt.manufacturing-event"
EVENT_CONTRACT_VERSION = "1.0.0"


def event_contract(version: str = EVENT_CONTRACT_VERSION) -> dict:
    if version != EVENT_CONTRACT_VERSION:
        raise ValueError(f"unsupported event contract version {version!r}")
    return {
        "name": EVENT_CONTRACT_NAME,
        "version": EVENT_CONTRACT_VERSION,
        "delivery": "at-least-once with idempotency-key support",
        "ordering": "timestamp order within an accepted batch; persisted sequence is authoritative",
        "required_fields": ["event_id", "event_type", "timestamp"],
        "optional_fields": ["job_id", "operation_id", "machine_id", "payload", "source_system", "source_event_id"],
        "event_types": [item.value for item in EventType],
        "evidence_boundary": "ingested event data is observed source evidence; it is not independently plant-validated",
    }
