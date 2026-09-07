import anyio
import httpx

from mdt.api.main import create_app
from mdt.config import Settings


def test_api_twin_trust_and_disposition_flow(tmp_path, root):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'api-twin.db').as_posix()}", benchmark_instance="ft06", project_root=root)
    app = create_app(settings)

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for payload in [
                    {"event_id":"r0","event_type":"job_released","timestamp":0,"job_id":"J0"},
                    {"event_id":"s0","event_type":"operation_started","timestamp":0,"operation_id":"J0-O0","machine_id":"M2"},
                    {"event_id":"c0","event_type":"operation_completed","timestamp":1,"operation_id":"J0-O0","machine_id":"M2"},
                ]:
                    response = await client.post("/v1/twin/events", json=payload)
                    assert response.status_code == 200
                twin_decision = await client.post("/v1/decision/recovery", json={"backend":"scipy","due_factor":1.5,"time_limit_seconds":5})
                assert twin_decision.status_code == 200
                twin_payload = twin_decision.json()
                assert twin_payload["planning_state"]["twin_event_count"] == 3
                assert all(op["operation_id"] != "J0-O0" for op in twin_payload["nominal_optimized"]["operations"])
                trust = await client.get("/v1/twin/trust")
                assert trust.status_code == 200 and trust.json()["decision"] == "AUTHORIZED"
                review = await client.post("/v1/decision/trusted-recovery", json={"backend":"scipy","due_factor":1.5,"time_limit_seconds":5,"reference_time":200.0,"authorize_threshold":0.9,"review_threshold":0.62})
                assert review.status_code == 200 and review.json()["optimizer_executed"] is False
                assert review.json()["status"] in {"HUMAN_REVIEW","BLOCKED"}
                runs = (await client.get("/v1/decisions")).json()
                assert len(runs) >= 2
                current_run = runs[0]["run_id"]
                approved = await client.post(f"/v1/decisions/{current_run}/disposition", json={"disposition":"approved","note":"API audit path"})
                assert approved.status_code == 200 and approved.json()["human_disposition"] == "approved"
                bad = await client.post("/v1/twin/events", json={"event_id":"bad","event_type":"operation_started","timestamp":1,"operation_id":"J0-O2","machine_id":"M1"})
                assert bad.status_code == 409

    anyio.run(scenario)
