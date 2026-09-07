# Production Readiness Foundation

This release adds the platform controls required before a named plant deployment. It does not claim that a plant connector, plant calibration or site acceptance has happened.

## Included in the foundation

- Environment-aware settings with a production fail-fast policy: production requires a server database, API-key authentication and an admin key.
- Role boundaries: `viewer` may read versioned APIs, `operator` may submit events and decisions, and `admin` may inspect operational schema metadata.
- `X-MDT-API-Key` and `Authorization: Bearer` support with constant-time key comparison. Keys are never emitted in logs or responses.
- Request correlation through `X-Request-ID`, dependency-free Prometheus text metrics at `/metrics`, liveness at `/health`, and dependency readiness at `/ready`.
- Versioned event contract at `/v1/platform/contracts/events`.
- At-least-once batch event ingestion at `/v1/ingest/events` with atomic replay validation and idempotency keys.
- PostgreSQL-ready SQLAlchemy configuration, production dependency manifest and Docker Compose deployment shape.
- Reviewed Alembic baseline at `migrations/versions/0001_rc4_hardening.py`; production schema creation is disabled unless explicitly enabled for a local compatibility run.

## Production environment contract

Required values:

```text
MDT_ENV=production
MDT_DATABASE_URL=postgresql+psycopg://...
MDT_AUTH_MODE=api_key
MDT_API_KEY=...
MDT_READONLY_API_KEY=...
MDT_ADMIN_API_KEY=...
MDT_ALLOWED_HOSTS=...
```

Optional values include `MDT_CORS_ORIGINS`, `MDT_INSTANCE_ID`, `MDT_SCHEMA_REVISION`, `MDT_EVENT_CONTRACT_VERSION` and `MDT_COPILOT_ENABLED`.
Production deployments must set `MDT_AUTO_CREATE_SCHEMA=false` and apply `alembic upgrade head` as a controlled migration step before starting application replicas.

## Event ingestion contract

The accepted contract is `mdt.manufacturing-event` version `1.0.0`. Send a batch with a unique `idempotency_key` and a stable `event_id` for every source event. Replaying a previously accepted idempotency key returns the original acceptance result without duplicating events. A batch is replay-validated before commit so a contradictory event cannot partially mutate the live twin.

The connector boundary is intentionally generic. Site-specific MES/ERP/SCADA/IIoT adapters still require an approved mapping, source ownership, replay/backfill policy, clock-quality policy and site acceptance evidence. Reusing an idempotency key with a different request fingerprint is rejected.

## Deployment controls still required outside this repository

- Secret-manager injection and rotation rather than environment files in production.
- TLS termination, enterprise SSO or a managed API gateway, network policy and tenant/site isolation.
- PostgreSQL migration execution (`alembic upgrade head`) and a backup/restore rehearsal using the reviewed baseline.
- Central logs, metrics, traces, alert routing and on-call ownership.
- Plant-calibrated model baselines, drift thresholds and controlled site acceptance.
- Approval to connect a released recommendation to a real execution system.
