from __future__ import annotations

import json
import platform
import sys

# Import the native stack in the simplest possible interpreter path.
import numpy as np
import scipy
import sklearn

EXPECTED_NUMPY = "2.3.5"

def main() -> None:
    checks = {
        "python_3_14": sys.version_info[:2] == (3, 14),
        "numpy_compatibility_pin": np.__version__ == EXPECTED_NUMPY,
        "numpy_basic_linear_algebra": bool(np.allclose(np.eye(2) @ np.ones(2), np.ones(2))),
        "scipy_import": bool(scipy.__version__),
        "sklearn_import": bool(sklearn.__version__),
    }
    payload = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "checks": checks,
    }
    print(json.dumps(payload, indent=2))
    if not all(checks.values()):
        failed = [k for k, ok in checks.items() if not ok]
        raise SystemExit(f"MDT_NATIVE_RUNTIME_SMOKE=FAIL: {failed}")
    print("MDT_NATIVE_RUNTIME_SMOKE=PASS")

if __name__ == "__main__":
    main()
