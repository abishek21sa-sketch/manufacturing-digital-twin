import anyio
import httpx

from mdt.api.main import create_app
from mdt.config import Settings


def test_api_solver_simulation_and_stress_flow(tmp_path, root):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'api-solver.db').as_posix()}", benchmark_instance="ft06", project_root=root)
    app = create_app(settings)

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                opt = await client.post("/v1/optimization/schedule", json={"backend":"scipy","due_factor":100,"makespan_weight":1,"tardiness_weight":0,"risk_tardiness_weight":0,"use_ai_risk":False})
                assert opt.status_code == 200 and abs(opt.json()["makespan"] - 55.0) < 1e-4
                decision = await client.post("/v1/decision/recovery", json={"backend":"scipy","due_factor":1.5,"time_limit_seconds":5})
                assert decision.status_code == 200 and decision.json()["optimized"]["violations"] == []
                simulation = await client.post("/v1/simulation/run", json={"policy":"SPT","due_factor":1.5,"seed":11,"processing_cv":0.05,"mtbf":80,"mttr":5})
                assert simulation.status_code == 200
                assert simulation.json()["violations"] == []
                assert simulation.json()["evidence_label"].startswith("SIMULATED")
                stress = await client.post("/v1/decision/stress-test", json={"backend":"scipy","due_factor":1.5,"time_limit_seconds":5,"replications":4,"base_seed":11,"processing_cv":0.05,"mtbf":80,"mttr":5})
                assert stress.status_code == 200 and len(stress.json()["stress_test"]["summaries"]) == 4
                invalid = await client.post("/v1/decision/stress-test", json={"backend":"scipy","time_limit_seconds":5,"replications":4,"stressed_machine_id":"M99"})
                assert invalid.status_code == 422

    anyio.run(scenario)
