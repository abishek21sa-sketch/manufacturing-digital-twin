import anyio
import httpx

from mdt.api.main import create_app
from mdt.config import Settings


def test_trust_api_and_non_authorized_recovery_gate(tmp_path, root):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'trust_api.db').as_posix()}",
        benchmark_instance="ft06",
        project_root=root,
    )
    app = create_app(settings)

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                trust = await client.get("/v1/twin/trust")
                assert trust.status_code == 200
                payload = trust.json()
                assert payload["decision"] in {"AUTHORIZED", "HUMAN_REVIEW", "BLOCKED"}
                assert 0.0 <= payload["score"] <= 1.0

                # Force stale evidence so the trust gate must stop the optimizer.
                guarded = await client.post(
                    "/v1/decision/trusted-recovery",
                    json={
                        "backend": "scipy",
                        "due_factor": 1.5,
                        "time_limit_seconds": 5,
                        "reference_time": 500.0,
                        "authorize_threshold": 0.95,
                        "review_threshold": 0.80,
                    },
                )
                assert guarded.status_code == 200
                result = guarded.json()
                assert result["optimizer_executed"] is False
                assert result["status"] in {"HUMAN_REVIEW", "BLOCKED"}
                assert result["solver"]["backend"] == "NOT_EXECUTED"

    anyio.run(scenario)

