import anyio
import httpx
import pytest
from sqlalchemy import inspect

from mdt.api.main import create_app
from mdt.config import Settings
from mdt.persistence import EventRepository
from mdt.runtime import DEFAULT_PORT


def _settings(root, db, **overrides):
    return Settings(
        database_url=f"sqlite:///{db.as_posix()}",
        benchmark_instance="ft06",
        project_root=root,
        **overrides,
    )


def test_production_settings_reject_local_sqlite_and_disabled_auth(root, tmp_path):
    settings = _settings(root, tmp_path / "production.db", environment="production", auth_mode="disabled")
    with pytest.raises(ValueError, match="production requires MDT_AUTH_MODE"):
        settings.validate_operational()


def test_production_requires_explicit_schema_migrations(root):
    settings = Settings(
        database_url="postgresql+psycopg://mdt:secret@db/mdt",
        benchmark_instance="ft06",
        project_root=root,
        environment="production",
        auth_mode="api_key",
        operator_api_key="operator-secret",
        readonly_api_key="viewer-secret",
        admin_api_key="admin-secret",
        auto_create_schema=True,
    )
    with pytest.raises(ValueError, match="AUTO_CREATE_SCHEMA=false"):
        settings.validate_operational()


def test_repository_schema_creation_can_be_disabled(tmp_path):
    repository = EventRepository(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}", create_schema=False)
    try:
        assert inspect(repository.engine).get_table_names() == []
    finally:
        repository.close()


def test_local_default_port_is_not_8000():
    assert DEFAULT_PORT == 8010


def test_api_key_roles_and_operational_endpoints(root, tmp_path):
    settings = _settings(
        root,
        tmp_path / "secure.db",
        auth_mode="api_key",
        operator_api_key="operator-secret",
        readonly_api_key="viewer-secret",
        admin_api_key="admin-secret",
    )
    app = create_app(settings)

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                assert (await client.get("/health")).status_code == 200
                health = await client.get("/health")
                assert health.headers["x-content-type-options"] == "nosniff"
                assert health.headers["cache-control"] == "no-store"
                assert (await client.get("/v1/factory")).status_code == 401
                assert (await client.get("/v1/factory", headers={"X-MDT-API-Key": "viewer-secret"})).status_code == 200
                event = {
                    "event_id": "secure-r0",
                    "event_type": "job_released",
                    "timestamp": 0,
                    "job_id": "J0",
                }
                assert (await client.post("/v1/twin/events", json=event, headers={"X-MDT-API-Key": "viewer-secret"})).status_code == 403
                assert (await client.post("/v1/twin/events", json=event, headers={"X-MDT-API-Key": "operator-secret"})).status_code == 200
                assert (await client.get("/v1/ops/schema", headers={"X-MDT-API-Key": "operator-secret"})).status_code == 403
                schema = await client.get("/v1/ops/schema", headers={"X-MDT-API-Key": "admin-secret"})
                assert schema.status_code == 200
                assert schema.json()["contract"]["version"] == "1.0.0"
                assert schema.headers["x-request-id"]
                openapi = await client.get("/openapi.json")
                assert openapi.status_code == 200
                assert "mdtApiKey" in openapi.json()["components"]["securitySchemes"]
                assert openapi.json()["paths"]["/v1/factory"]["get"]["security"]

    anyio.run(scenario)


def test_versioned_batch_ingestion_is_atomic_and_idempotent(root, tmp_path):
    app = create_app(_settings(root, tmp_path / "batch.db"))
    payload = {
        "source_system": "mes-test",
        "schema_version": "1.0.0",
        "idempotency_key": "batch-0001",
        "events": [
            {"event_id": "batch-r0", "event_type": "job_released", "timestamp": 0, "job_id": "J0"},
            {"event_id": "batch-s0", "event_type": "operation_started", "timestamp": 0, "operation_id": "J0-O0", "machine_id": "M2"},
        ],
    }

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                accepted = await client.post("/v1/ingest/events", json=payload)
                assert accepted.status_code == 200
                assert accepted.json()["accepted_count"] == 2
                assert accepted.json()["state"]["event_count"] == 2
                replayed = await client.post("/v1/ingest/events", json=payload)
                assert replayed.status_code == 200
                assert replayed.json()["replayed"] is True
                assert replayed.json()["state"]["event_count"] == 2
                conflict = {
                    **payload,
                    "events": [{**payload["events"][0], "timestamp": 1}, payload["events"][1]],
                }
                conflicted = await client.post("/v1/ingest/events", json=conflict)
                assert conflicted.status_code == 409
                assert "different request" in conflicted.json()["detail"]
                contract = await client.get("/v1/platform/contracts/events")
                assert contract.status_code == 200
                assert contract.json()["delivery"].startswith("at-least-once")
                ready = await client.get("/ready")
                assert ready.status_code == 200 and ready.json()["status"] == "ready"
                metrics = await client.get("/metrics")
                assert metrics.status_code == 200 and "mdt_http_requests_total" in metrics.text

    anyio.run(scenario)
