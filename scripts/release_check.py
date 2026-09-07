from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def run(args: list[str], root: Path, env: dict[str, str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=root, check=True, env=env)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"

    # Fail-fast gates deliberately precede the expensive isolated suite.  This
    # prevents stale release artifacts or a runtime/API timeout from being
    # discovered only after the user has waited for every solver-heavy test.
    run([sys.executable, "scripts/static_gate.py"], root, env)
    run([sys.executable, "scripts/frontend_check.py"], root, env)
    run([sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"], root, env)
    run([sys.executable, "scripts/fortune50_preflight.py"], root, env)
    run([sys.executable, "scripts/public_release_check.py"], root, env)
    run([sys.executable, "scripts/runtime_smoke.py"], root, env)
    run([sys.executable, "scripts/trust_rh_evidence.py"], root, env)

    # The long deterministic release suite runs only after all fast/runtime
    # preconditions above have passed.
    run([sys.executable, "scripts/test_suite_isolated.py"], root, env)
    run([sys.executable, "scripts/v1_diagnostics.py"], root, env)
    run([sys.executable, "scripts/performance_check.py"], root, env)
    print("RELEASE_CHECK=PASS")


if __name__ == "__main__":
    main()
