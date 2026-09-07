import anyio
import httpx

from mdt import __version__
from mdt.api.main import create_app
from mdt.config import Settings


def test_api_v1_system_data_ai_flow_and_lifespan_cleanup(tmp_path, root, monkeypatch):
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'api-system.db').as_posix()}", benchmark_instance="ft06", project_root=root)
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
                assert "SYNTHETIC DATA PACK" in workspace.text
                methodology = await client.get("/methodology")
                assert methodology.status_code == 200 and "Engineering Methodology" in methodology.text
                methods = (await client.get("/v1/methodology/evidence")).json()
                assert methods["version"] == __version__ and methods["benchmark"]["operations"] == 36
                assert methods["ai"]["lateness"]["production_model"]["roc_auc"] > 0.9
                readiness = (await client.get("/v1/data/readiness")).json()
                assert readiness["canonical_event_columns"][0] == "event_id"
                assert "SYNTHETIC_SCENARIO_ANALYTICS" in readiness["supported_modes"]
                synthetic = await client.get("/v1/data/synthetic")
                assert synthetic.status_code == 200
                assert synthetic.json()["rows"] == 150_000
                assert synthetic.json()["columns"] == 80
                assert synthetic.json()["integrity"]["ready"] is True
                synthetic_download = await client.get("/v1/data/synthetic/download")
                assert synthetic_download.status_code == 200
                assert synthetic_download.headers["content-type"].startswith("text/csv")
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

    anyio.run(scenario)
    assert disposed["called"] == 1
