# Manufacturing Event Contract v1.0.0

Contract name: `mdt.manufacturing-event`  
Endpoint: `POST /v1/ingest/events`  
Delivery: at-least-once with an idempotency key  
Ordering: source timestamp within the batch; persisted sequence is authoritative

## Batch envelope

```json
{
  "source_system": "mes-example",
  "schema_version": "1.0.0",
  "idempotency_key": "mes-example-2026-09-05-000001",
  "events": [
    {
      "event_id": "mes-123",
      "event_type": "job_released",
      "timestamp": 20.0,
      "job_id": "J0",
      "payload": {},
      "source_event_id": "MES-123"
    }
  ]
}
```

Required event fields are `event_id`, `event_type` and non-negative `timestamp`. Supported event types are exposed by `/v1/platform/contracts/events`. Job, operation and machine references are validated by deterministic twin replay.

## Operational rules

- Retrying the same `idempotency_key` is safe and returns the original accepted event IDs.
- Reusing an event ID with a different idempotency key is rejected.
- The complete batch is replay-validated before durable commit.
- Source and provenance metadata is retained under `_mdt_contract` in the event payload.
- No event is treated as plant truth beyond its declared source; clock quality, completeness and source reconciliation remain site responsibilities.
