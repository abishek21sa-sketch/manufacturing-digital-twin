import anyio
import httpx

from mdt import __version__
from mdt.api.main import create_app
from mdt.config import Settings


def test_api_v1_flow_and_lifespan_cleanup(tmp_path, root, monkeypatch):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}", benchmark_instance="ft06", project_root=root)
    app = create_app(settings)
    disposed = {"called": 0}

    async def scenario():
        async with app.router.lifespan_context(app):
            service = app.state.service
            original_dispose = service.repository.engine.dispose

            def tracked_dispose(*args, **kwargs):
                disposed["called"] += 1
                return original_dispose(*args, **kwargs)

            monkeypatch.setattr(service.repository.engine, "dispose", tracked_dispose)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                health = (await client.get("/health")).json()
                assert health["version"] == __version__ and health["release"] == "V1.0"
                factory = (await client.get("/v1/factory")).json()
                assert factory["jobs"] == 6 and factory["operations"] == 36
                workspace = await client.get("/workspace")
                assert workspace.status_code == 200 and "Future-State Production" in workspace.text
                methodology = await client.get("/methodology")
                assert methodology.status_code == 200 and "Engineering Methodology" in methodology.text
                methods = (await client.get("/v1/methodology/evidence")).json()
                assert methods["version"] == __version__
                assert methods["benchmark"]["operations"] == 36
                assert methods["ai"]["lateness"]["production_model"]["roc_auc"] > 0.9
                readiness = (await client.get("/v1/data/readiness")).json()
                assert readiness["canonical_event_columns"][0] == "event_id"
                copilot = (await client.get("/v1/copilot/status")).json()
                assert copilot["provider"] == "Google Gemini"
                missing_key = await client.post("/v1/copilot/interpret-scenario", json={"request": "stress M5"})
                assert missing_key.status_code == 503
                sample_csv = (root / "data/samples/historical_events.csv").read_text(encoding="utf-8")
                valid_data = await client.post("/v1/data/validate-events", json={"csv_text": sample_csv})
                assert valid_data.status_code == 200 and valid_data.json()["report"]["ready"] is True
                replayed_data = await client.post("/v1/data/replay-events", json={"csv_text": sample_csv})
                assert replayed_data.status_code == 200 and replayed_data.json()["persisted"] is False
                risk = (await client.get("/v1/ai/lateness-risk?due_factor=1.5")).json()
                assert len(risk["jobs"]) == 6
                operational = (await client.get("/v1/ai/operational?due_factor=1.5&processing_cv=0.1&mtbf=80&mttr=5")).json()
                assert set(operational["future_bottleneck_probability"]) == {f"M{i}" for i in range(6)}
                assert operational["evidence_labels"]["anomaly"].startswith("ANOMALY SCORE")
                ie_control = (await client.get("/v1/ie/control-plan?due_factor=1.5&horizon=100&buffer_time=5&wip_limit=3")).json()
                assert ie_control["constraint"]["machine_id"] == "M5"
                assert ie_control["drum_buffer_rope"]["constraint_machine_id"] == "M5"
                opt = await client.post("/v1/optimization/schedule", json={"backend": "scipy", "due_factor": 100, "makespan_weight": 1, "tardiness_weight": 0, "risk_tardiness_weight": 0, "use_ai_risk": False})
                assert opt.status_code == 200
                assert abs(opt.json()["makespan"] - 55.0) < 1e-4
                decision = await client.post("/v1/decision/recovery", json={"backend": "scipy", "due_factor": 1.5, "time_limit_seconds": 5})
                assert decision.status_code == 200
                assert decision.json()["optimized"]["violations"] == []
                simulation = await client.post("/v1/simulation/run", json={"policy": "SPT", "due_factor": 1.5, "seed": 11, "processing_cv": 0.05, "mtbf": 80, "mttr": 5})
                assert simulation.status_code == 200
                assert simulation.json()["violations"] == []
                assert simulation.json()["evidence_label"].startswith("SIMULATED")
                stress = await client.post("/v1/decision/stress-test", json={"backend": "scipy", "due_factor": 1.5, "time_limit_seconds": 5, "replications": 4, "base_seed": 11, "processing_cv": 0.05, "mtbf": 80, "mttr": 5})
                assert stress.status_code == 200
                assert len(stress.json()["stress_test"]["summaries"]) == 4
                invalid_stress = await client.post("/v1/decision/stress-test", json={"backend": "scipy", "time_limit_seconds": 5, "replications": 4, "stressed_machine_id": "M99"})
                assert invalid_stress.status_code == 422
                response = await client.post("/v1/twin/events", json={"event_id": "r0", "event_type": "job_released", "timestamp": 0, "job_id": "J0"})
                assert response.status_code == 200
                started = await client.post("/v1/twin/events", json={"event_id": "s0", "event_type": "operation_started", "timestamp": 0, "operation_id": "J0-O0", "machine_id": "M2"})
                assert started.status_code == 200
                completed = await client.post("/v1/twin/events", json={"event_id": "c0", "event_type": "operation_completed", "timestamp": 1, "operation_id": "J0-O0", "machine_id": "M2"})
                assert completed.status_code == 200
                twin_decision = await client.post("/v1/decision/recovery", json={"backend": "scipy", "due_factor": 1.5, "time_limit_seconds": 5})
                assert twin_decision.status_code == 200
                twin_payload = twin_decision.json()
                assert twin_payload["planning_state"]["twin_event_count"] == 3
                assert all(op["operation_id"] != "J0-O0" for op in twin_payload["nominal_optimized"]["operations"])
                runs = (await client.get("/v1/decisions")).json()
                assert len(runs) >= 3
                current_run = runs[0]["run_id"]
                approved = await client.post(f"/v1/decisions/{current_run}/disposition", json={"disposition": "approved", "note": "API audit path"})
                assert approved.status_code == 200 and approved.json()["human_disposition"] == "approved"
                bad = await client.post("/v1/twin/events", json={"event_id": "bad", "event_type": "operation_started", "timestamp": 1, "operation_id": "J0-O2", "machine_id": "M1"})
                assert bad.status_code == 409

    anyio.run(scenario)
    assert disposed["called"] == 1
