from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys


def _count_tests(root: Path) -> int:
    return sum(
        len(re.findall(r"^def test_", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
        for path in (root / "tests").glob("test_*.py")
    )


def _run(args: list[str], root: Path, env: dict[str, str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=root, check=True, env=env)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    # Release tests must be independent of unrelated pytest plugins installed
    # globally on a developer machine. The repository does not require any
    # third-party pytest plugin, so disable auto-discovery for deterministic
    # Windows and clean-room behavior.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    # Solver-heavy tests are deliberately executed one file per Python process.
    # This prevents accumulated native-solver/thread-pool state from affecting
    # later tests and gives Windows deterministic resource cleanup boundaries.
    test_files = sorted((root / "tests").glob("test_*.py"))
    priority = {
        "test_constitution_closure.py": 0,
        "test_optimization.py": 1,
        "test_decision.py": 2,
        "test_stress_test.py": 3,
        "test_simulation.py": 4,
    }
    test_files.sort(key=lambda path: (priority.get(path.name, 10), path.name))
    for test_file in test_files:
        _run([sys.executable, "-m", "pytest", str(test_file.relative_to(root)), "-q", "-p", "scripts.pytest_force_exit"], root, env)

    print(f"ISOLATED_TESTS={_count_tests(root)}")
    print("ISOLATED_TEST_SUITE=PASS")


if __name__ == "__main__":
    main()
