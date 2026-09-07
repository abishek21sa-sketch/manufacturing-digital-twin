import anyio
import httpx

from mdt.api.main import create_app
from mdt.config import Settings


def test_authorized_trusted_recovery_executes_in_fresh_process(tmp_path, root):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'trusted_authorized.db').as_posix()}",
        benchmark_instance="ft06",
        project_root=root,
    )
    app = create_app(settings)

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for event in (
                    {"event_id": "r0", "event_type": "job_released", "timestamp": 0, "job_id": "J0"},
                    {"event_id": "s0", "event_type": "operation_started", "timestamp": 0, "operation_id": "J0-O0", "machine_id": "M2"},
                    {"event_id": "c0", "event_type": "operation_completed", "timestamp": 1, "operation_id": "J0-O0", "machine_id": "M2"},
                ):
                    response = await client.post("/v1/twin/events", json=event)
                    assert response.status_code == 200
                trusted = await client.post(
                    "/v1/decision/trusted-recovery",
                    json={"backend": "scipy", "due_factor": 1.5, "time_limit_seconds": 5},
                )
                assert trusted.status_code == 200
                payload = trusted.json()
                assert payload["optimizer_executed"] is True
                assert payload["trust"]["decision"] == "AUTHORIZED"
                assert payload["algorithm"] == "TRUST-RH"

    anyio.run(scenario)
