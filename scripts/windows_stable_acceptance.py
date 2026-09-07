from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> None:
    env = os.environ.copy()
    env.update({
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    })
    env.pop("PYTHONPATH", None)
    print("RUNNING MDT V1 stable Python 3.14 Windows acceptance", flush=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/windows_v1_acceptance.py")], cwd=ROOT, env=env, check=True)
    print("MDT_V1_STABLE_WINDOWS_ACCEPTANCE=PASS")

if __name__ == "__main__":
    main()
