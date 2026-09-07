# Database Operations

## Local and demo modes

SQLite remains supported for local Windows demos and deterministic acceptance. Runtime databases are disposable application state and are not production backups.

## Production mode

Production must use a server database URL such as `postgresql+psycopg://...`. The application fails fast when `MDT_ENV=production` is combined with SQLite, disabled authentication or missing admin credentials.

The repository includes a reviewed Alembic baseline in `migrations/versions/0001_rc4_hardening.py` and exposes the schema contract at authenticated `GET /v1/ops/schema`. Set `MDT_AUTO_CREATE_SCHEMA=false` in production and apply the migration explicitly:

```powershell
alembic -c alembic.ini upgrade head
```

The deployment owner must rehearse:

1. migration forward and rollback policy;
2. point-in-time backup and restore;
3. event-ledger integrity verification after restore;
4. decision-record retention and export;
5. database credential rotation;
6. idempotency-key conflict handling and event-ledger replay after migration.

The event ledger is the authoritative replay input. Do not restore a decision database without verifying the event sequence and twin reconstruction identity.
