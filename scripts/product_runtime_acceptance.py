from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

from mdt.runtime import free_port

ROOT = Path(__file__).resolve().parents[1]
OUTER = ROOT.parent


def run(*args: str, env: dict[str, str] | None = None) -> None:
    print("RUNNING:", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def launcher_case(port: int, env: dict[str, str], *, expected_success: bool = True) -> str:
    args = [sys.executable, "scripts/launch_workspace.py", "--no-browser", "--exit-after-ready", "--port", str(port)]
    print("RUNNING:", " ".join(args), flush=True)
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, timeout=90)
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", flush=True)
    if expected_success and result.returncode != 0:
        raise SystemExit(f"PRODUCT_RUNTIME_ACCEPTANCE=FAIL launcher returned {result.returncode}")
    if not expected_success and result.returncode == 0:
        raise SystemExit("PRODUCT_RUNTIME_ACCEPTANCE=FAIL occupied-port launcher unexpectedly succeeded")
    return result.stdout + result.stderr


def assert_port_released(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise SystemExit(f"PRODUCT_RUNTIME_ACCEPTANCE=FAIL port {port} was not released") from exc


def main() -> None:
    required_outer = ["RUN_APP.cmd", "RUN_DEMO.cmd", "RUN_PRODUCT_ACCEPTANCE.cmd", "RUN_ACCEPTANCE.cmd"]
    missing = [name for name in required_outer if not (OUTER / name).exists()]
    if missing:
        raise SystemExit(f"PRODUCT_RUNTIME_ACCEPTANCE=FAIL missing outer launchers: {missing}")
    required_inner = ["run_windows.bat", "run_demo_windows.bat", "scripts/portfolio_demo.py", "scripts/launch_workspace.py"]
    missing = [name for name in required_inner if not (ROOT / name).exists()]
    if missing:
        raise SystemExit(f"PRODUCT_RUNTIME_ACCEPTANCE=FAIL missing runtime files: {missing}")

    index = (ROOT / "workspace" / "index.html").read_text(encoding="utf-8")
    appjs = (ROOT / "workspace" / "app.js").read_text(encoding="utf-8")
    for token in ("demoModeBadge", "downloadEvidenceBtn", "DETERMINISTIC DEMO"):
        if token not in index + appjs:
            raise SystemExit(f"PRODUCT_RUNTIME_ACCEPTANCE=FAIL UI token missing: {token}")

    demo_db = ROOT / "runtime" / "mdt_product_acceptance.db"
    if demo_db.exists():
        demo_db.unlink()
    env = os.environ.copy()
    env["MDT_DATABASE_URL"] = "sqlite:///runtime/mdt_product_acceptance.db"
    env["PYTHONNOUSERSITE"] = "1"
    env["OMP_NUM_THREADS"] = env["OPENBLAS_NUM_THREADS"] = env["MKL_NUM_THREADS"] = "1"

    run(sys.executable, "scripts/portfolio_demo.py", "--reset", "--build-evidence", env=env)
    artifact = ROOT / "artifacts" / "demo" / "latest_demo_evidence.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    if payload.get("event_count", 0) < 20 or payload.get("trust_decision") != "AUTHORIZED":
        raise SystemExit(f"PRODUCT_RUNTIME_ACCEPTANCE=FAIL bad demo state: {payload}")
    if not payload.get("decision", {}).get("recommended_policy"):
        raise SystemExit("PRODUCT_RUNTIME_ACCEPTANCE=FAIL demo decision missing")

    requested_free_port = free_port()
    launcher_case(requested_free_port, env)
    assert_port_released(requested_free_port)
    print("REQUESTED_PORT_FREE=PASS", flush=True)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        occupied_port = int(listener.getsockname()[1])
        output = launcher_case(occupied_port, env, expected_success=False)
        if "PORT_CONFIGURATION=FAIL" not in output:
            raise SystemExit("PRODUCT_RUNTIME_ACCEPTANCE=FAIL occupied-port error was not explicit")
    print("REQUESTED_PORT_OCCUPIED=PASS", flush=True)

    automatic_output = launcher_case(0, env)
    match = re.search(r"WORKSPACE_PORT=(\d+)", automatic_output)
    if not match:
        raise SystemExit("PRODUCT_RUNTIME_ACCEPTANCE=FAIL automatic port was not reported")
    automatic_port = int(match.group(1))
    assert_port_released(automatic_port)
    print("AUTOMATIC_EPHEMERAL_PORT=PASS", flush=True)
    print("CLEAN_SHUTDOWN=PASS", flush=True)
    print("NO_ORPHAN_UVICORN=PASS", flush=True)
    run(sys.executable, "-m", "pytest", "tests/test_workspace.py", "tests/test_workspace_launcher_contract.py", "tests/test_api.py", "-q", env=env)
    print("MDT_PRODUCT_RUNTIME_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
