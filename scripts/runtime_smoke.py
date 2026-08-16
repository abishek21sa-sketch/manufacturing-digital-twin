from __future__ import annotations

import gc
import shutil
from pathlib import Path
import tempfile
import threading
import time

import httpx
import uvicorn

from mdt.api.main import create_app
from mdt.config import Settings


# The recovery/stress endpoints can execute several MILPs per HTTP request
# (nominal + robust + Pareto scalarizations). ``time_limit_seconds`` is a
# per-solve budget, not a whole-request deadline. Runtime smoke validates the
# integrated API path; dedicated Gurobi/HiGHS acceptance scripts validate
# solver-specific correctness. Use the production ``auto`` backend here and
# give the client a request budget that cannot expire before the server's
# legitimate internal solve budget.
SMOKE_SOLVER_BACKEND = "auto"
SMOKE_SOLVE_LIMIT_SECONDS = 5.0
DECISION_HTTP_TIMEOUT_SECONDS = 60.0
STRESS_HTTP_TIMEOUT_SECONDS = 90.0
SERVER_SHUTDOWN_TIMEOUT_SECONDS = 60.0


def _timed_request(client: httpx.Client, label: str, method: str, url: str, *, timeout: float, **kwargs) -> httpx.Response:
    started = time.monotonic()
    print(f"RUNTIME_SMOKE_STEP={label}:START", flush=True)
    try:
        response = client.request(method, url, timeout=timeout, **kwargs)
    except Exception:
        elapsed = time.monotonic() - started
        print(f"RUNTIME_SMOKE_STEP={label}:FAIL elapsed_seconds={elapsed:.3f}", flush=True)
        raise
    elapsed = time.monotonic() - started
    print(f"RUNTIME_SMOKE_STEP={label}:PASS elapsed_seconds={elapsed:.3f} status={response.status_code}", flush=True)
    return response


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def remove_tree_with_retry(path: Path, *, attempts: int = 40, delay_seconds: float = 0.1) -> None:
    """Remove a directory while making Windows handle-release timing explicit.

    This does not ignore persistent locks. It only tolerates the brief interval
    Windows can require after orderly server/database shutdown. If the lock is
    still present after the retry budget, the release gate fails.
    """
    last_error: PermissionError | None = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            gc.collect()
            if attempt + 1 < attempts:
                time.sleep(delay_seconds)
    raise RuntimeError(f"Windows-safe cleanup failed for {path}") from last_error


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    port = free_port()
    temp_root = Path(tempfile.mkdtemp(prefix="mdt-runtime-smoke-"))
    db_path = temp_root / "smoke.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        benchmark_instance="ft06",
        project_root=root,
    )
    application = create_app(settings)
    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    server_errors: list[BaseException] = []

    def run_server() -> None:
        try:
            server.run()
        except BaseException as exc:  # surfaced in the controlling thread below
            server_errors.append(exc)

    thread = threading.Thread(target=run_server, name="mdt-runtime-smoke-server", daemon=False)
    thread.start()

    try:
        base = f"http://127.0.0.1:{port}"
        # Localhost release acceptance must be independent of developer/user
        # proxy environment variables, and connection reuse reduces Windows
        # socket churn during the multi-request smoke flow.
        client = httpx.Client(base_url=base, trust_env=False)
        for _ in range(100):
            if server_errors:
                raise RuntimeError("API server failed during startup") from server_errors[0]
            if not thread.is_alive():
                raise RuntimeError("API server exited before becoming ready")
            try:
                health = client.get("/health", timeout=0.5)
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise RuntimeError("API failed to become ready")

        workspace = client.get("/workspace", timeout=2.0)
        workspace.raise_for_status()
        assert "Future-State Production" in workspace.text
        methodology = client.get("/methodology", timeout=2.0)
        methodology.raise_for_status()
        assert "Engineering Methodology" in methodology.text
        methods = client.get("/v1/methodology/evidence", timeout=2.0)
        methods.raise_for_status()
        assert methods.json()["benchmark"]["operations"] == 36
        asset = client.get("/workspace/assets/app.js", timeout=2.0)
        asset.raise_for_status()
        assert "/v1/decision/stress-test" in asset.text

        factory = client.get("/v1/factory", timeout=2.0)
        factory.raise_for_status()
        assert factory.json()["operations"] == 36
        readiness = client.get("/v1/data/readiness", timeout=2.0)
        readiness.raise_for_status()
        assert "event_id" in readiness.json()["canonical_event_columns"]
        copilot = client.get("/v1/copilot/status", timeout=2.0)
        copilot.raise_for_status()
        assert copilot.json()["provider"] == "Google Gemini"

        risk = client.get("/v1/ai/lateness-risk?due_factor=1.5", timeout=5.0)
        risk.raise_for_status()
        assert len(risk.json()["jobs"]) == 6
        operational = client.get("/v1/ai/operational?due_factor=1.5&processing_cv=0.1&mtbf=80&mttr=5", timeout=5.0)
        operational.raise_for_status()
        assert len(operational.json()["future_bottleneck_probability"]) == 6
        ie_control = client.get("/v1/ie/control-plan?due_factor=1.5&horizon=100&buffer_time=5&wip_limit=3", timeout=5.0)
        ie_control.raise_for_status()
        assert ie_control.json()["constraint"]["machine_id"] == "M5"

        decision = _timed_request(
            client,
            "decision_recovery_zero_state",
            "POST",
            "/v1/decision/recovery",
            json={"backend": SMOKE_SOLVER_BACKEND, "due_factor": 1.5, "time_limit_seconds": SMOKE_SOLVE_LIMIT_SECONDS},
            timeout=DECISION_HTTP_TIMEOUT_SECONDS,
        )
        decision.raise_for_status()
        assert decision.json()["optimized"]["violations"] == []

        simulation = client.post(
            "/v1/simulation/run",
            json={"policy": "SPT", "backend": SMOKE_SOLVER_BACKEND, "due_factor": 1.5, "seed": 77, "processing_cv": 0.05, "mtbf": 80, "mttr": 5, "stressed_machine_id": "M5", "stressed_machine_mtbf": 35, "stressed_machine_mttr": 12, "time_limit_seconds": SMOKE_SOLVE_LIMIT_SECONDS},
            timeout=15.0,
        )
        simulation.raise_for_status()
        assert simulation.json()["violations"] == []
        assert simulation.json()["evidence_label"].startswith("SIMULATED")

        stress = _timed_request(
            client,
            "decision_stress_test",
            "POST",
            "/v1/decision/stress-test",
            json={"backend": SMOKE_SOLVER_BACKEND, "due_factor": 1.5, "replications": 4, "base_seed": 77, "processing_cv": 0.05, "mtbf": 80, "mttr": 5, "stressed_machine_id": "M5", "stressed_machine_mtbf": 35, "stressed_machine_mttr": 12, "time_limit_seconds": SMOKE_SOLVE_LIMIT_SECONDS},
            timeout=STRESS_HTTP_TIMEOUT_SECONDS,
        )
        stress.raise_for_status()
        assert len(stress.json()["stress_test"]["summaries"]) == 4
        assert stress.json()["stress_test"]["stochastic_policy_selection"]["solver"]["status"] == "OPTIMAL"

        sample_csv = (root / "data" / "samples" / "historical_events.csv").read_text(encoding="utf-8")
        data_check = client.post("/v1/data/validate-events", json={"csv_text": sample_csv}, timeout=3.0)
        data_check.raise_for_status()
        assert data_check.json()["report"]["ready"] is True
        replay = client.post("/v1/data/replay-events", json={"csv_text": sample_csv}, timeout=3.0)
        replay.raise_for_status()
        assert replay.json()["persisted"] is False
        assert replay.json()["state"]["event_count"] == 3

        release = client.post(
            "/v1/twin/events",
            json={
                "event_id": "runtime-smoke-release",
                "event_type": "job_released",
                "timestamp": 0,
                "job_id": "J0",
            },
            timeout=2.0,
        )
        release.raise_for_status()
        assert "J0-O0" in release.json()["state"]["ready_operations"]
        started = client.post("/v1/twin/events", json={"event_id": "runtime-smoke-start", "event_type": "operation_started", "timestamp": 0, "operation_id": "J0-O0", "machine_id": "M2"}, timeout=2.0)
        started.raise_for_status()
        completed = client.post("/v1/twin/events", json={"event_id": "runtime-smoke-complete", "event_type": "operation_completed", "timestamp": 1, "operation_id": "J0-O0", "machine_id": "M2"}, timeout=2.0)
        completed.raise_for_status()
        live_decision = _timed_request(
            client,
            "decision_recovery_live_twin",
            "POST",
            "/v1/decision/recovery",
            json={"backend": SMOKE_SOLVER_BACKEND, "due_factor": 1.5, "time_limit_seconds": SMOKE_SOLVE_LIMIT_SECONDS},
            timeout=DECISION_HTTP_TIMEOUT_SECONDS,
        )
        live_decision.raise_for_status()
        assert live_decision.json()["planning_state"]["twin_event_count"] == 3
        assert all(op["operation_id"] != "J0-O0" for op in live_decision.json()["nominal_optimized"]["operations"])
        runs = client.get("/v1/decisions", timeout=2.0)
        runs.raise_for_status()
        assert len(runs.json()) >= 3

        illegal = client.post(
            "/v1/twin/events",
            json={
                "event_id": "runtime-smoke-illegal",
                "event_type": "operation_started",
                "timestamp": 1,
                "operation_id": "J0-O2",
                "machine_id": "M1",
            },
            timeout=2.0,
        )
        assert illegal.status_code == 409

        if server_errors or not thread.is_alive():
            raise RuntimeError("API server did not survive the asserted smoke flow")
    finally:
        if "client" in locals():
            client.close()
        # Graceful Uvicorn shutdown runs FastAPI lifespan teardown, which closes
        # TwinService -> EventRepository -> SQLAlchemy engine before cleanup.
        server.should_exit = True
        thread.join(timeout=SERVER_SHUTDOWN_TIMEOUT_SECONDS)
        if thread.is_alive():
            raise RuntimeError(f"API server did not stop gracefully within {SERVER_SHUTDOWN_TIMEOUT_SECONDS:g} seconds")
        if server_errors:
            raise RuntimeError("API server raised during runtime smoke") from server_errors[0]
        remove_tree_with_retry(temp_root)

    if temp_root.exists():
        raise RuntimeError("Runtime smoke temporary directory still exists after cleanup")
    print("RUNTIME_SMOKE=PASS")


if __name__ == "__main__":
    main()
