"""Release-test helper for deterministic native-library teardown.

Each pytest file runs in its own interpreter. Some native optimization/BLAS
libraries can keep non-daemon/native resources alive after pytest has already
finished. The release runner therefore loads this local plugin only for those
isolated child processes and terminates the interpreter immediately after
pytest has emitted its authoritative exit status.
"""
from __future__ import annotations

import os
import sys


def pytest_sessionfinish(session, exitstatus: int) -> None:  # pragma: no cover - release-process behavior
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        # pytest has completed collection/execution and supplied the canonical
        # exit status. Avoid native solver/thread-pool teardown hangs in the
        # disposable child interpreter used by scripts/test_suite_isolated.py.
        os._exit(int(exitstatus))
