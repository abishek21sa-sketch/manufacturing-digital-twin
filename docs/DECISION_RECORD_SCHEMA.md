# Decision Record Schema

Every recovery or future-state stress-test run is persisted with a durable run identity and the inputs needed to reproduce its evidence packet.

```json
{
  "run_id": "uuid",
  "created_at_utc": "timestamp",
  "decision_kind": "recovery | trusted_recovery | future_state_stress_test",
  "twin_state_id": "content hash",
  "twin_timestamp": 0,
  "twin_event_count": 0,
  "model_version": "package version",
  "solver_backend": "gurobi | scipy-highs | NOT_EXECUTED",
  "data_version": "benchmark and source identity",
  "request": "validated scenario inputs",
  "result": "complete evidence packet",
  "status": "solver or policy status",
  "human_disposition": "pending | approved | deferred | rejected",
  "disposition_note": "optional review note"
}
```

The result packet keeps these objects separate:

- observed event-sourced twin state;
- predicted AI analytics with their evidence labels;
- optimized nominal, robust and Pareto schedules;
- simulated future-state metrics and policy selection;
- solver status, bound, gap, model size and feasibility checks;
- TRUST-RH authorization and human disposition.

The `/v1/twin/ledger` endpoint supplies the replay evidence, while `/v1/decisions` supplies persisted decision records. Together they allow a reviewer to answer which state was used, which solver was run, which policy was recommended, and whether an engineer approved the recommendation.
