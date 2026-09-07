from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import numpy as np

# Import the native scientific stack before coverage/sys.monitoring is initialized.
# NumPy 2.3.5 is the Windows/Python 3.14 compatibility baseline for MDT.
from coverage import Coverage


def _trust(decision: str = "authorized"):
    from mdt.trust import assess_trust

    machine = SimpleNamespace(machine_id="M1")
    op = SimpleNamespace(operation_id="O1")
    job = SimpleNamespace(job_id="J1", operations=(op,))
    factory = SimpleNamespace(machines=(machine,), jobs=(job,))
    snap = SimpleNamespace(
        machines={"M1": 1},
        jobs={"J1": 1},
        operations={"O1": 1},
        event_count=1,
        timestamp=10.0,
    )
    reference_time = 10.0 if decision == "authorized" else 100.0
    return assess_trust(
        snapshot=snap,
        factory_model=factory,
        ledger_events=[1],
        model_evidence={"a": True, "b": True, "c": True, "d": True},
        reference_time=reference_time,
    )


def main() -> None:
    # This intentionally avoids pytest-cov on Windows/Python 3.14. The native
    # scientific stack is loaded before coverage instrumentation starts.
    cov = Coverage(source=["mdt.optimization.signature_algorithm"], branch=False)
    cov.start()

    from mdt.optimization.signature_algorithm import (
        TrustRHError,
        reference_slot_problem,
        run_trust_rh_signature,
        solve_stability_assignment,
    )

    checks: dict[str, bool] = {}

    jobs = ["A", "B", "C"]
    costs, prior, cap = reference_slot_problem(jobs)
    authorized = run_trust_rh_signature(
        _trust(), jobs, costs, prior, cap, stability_penalty=2.0
    )
    checks["authorized_optimal"] = (
        authorized.status == "OPTIMAL"
        and authorized.optimizer_executed
        and set(authorized.job_to_slot) == set(jobs)
        and authorized.churn_count >= 0
    )

    blocked_jobs = ["A", "B"]
    blocked_costs, blocked_prior, blocked_cap = reference_slot_problem(blocked_jobs)
    blocked = run_trust_rh_signature(
        _trust("stale"),
        blocked_jobs,
        blocked_costs,
        blocked_prior,
        blocked_cap,
    )
    checks["untrusted_does_not_execute"] = (
        blocked.status in {"HUMAN_REVIEW", "BLOCKED"}
        and not blocked.optimizer_executed
        and blocked.job_to_slot == {}
    )

    invalid_cases = [
        lambda: solve_stability_assignment([], np.zeros((0, 0)), [], []),
        lambda: solve_stability_assignment(["A"], np.zeros((2, 1)), [0], [1]),
        lambda: solve_stability_assignment(["A"], np.zeros((1, 1)), [2], [1]),
        lambda: solve_stability_assignment(["A"], np.zeros((1, 1)), [0], [0]),
        lambda: solve_stability_assignment(
            ["A"], np.zeros((1, 1)), [0], [1], stability_penalty=-1
        ),
    ]
    invalid_ok = 0
    for fn in invalid_cases:
        try:
            fn()
        except TrustRHError:
            invalid_ok += 1
    checks["validation_edges"] = invalid_ok == len(invalid_cases)

    # Dedicated operator surface / API contract checks without pytest.
    html = (ROOT / "workspace/index.html").read_text(encoding="utf-8")
    js = (ROOT / "workspace/app.js").read_text(encoding="utf-8")
    html_tokens = [
        "TRUST-RH AUTHORIZATION GATE",
        "Should this twin be trusted enough to optimize?",
        "Freshness horizon",
        "Authorize threshold",
        "Review threshold",
        "Run trust-gated recovery",
    ]
    checks["ui_operator_surface"] = all(token in html for token in html_tokens)
    checks["ui_gated_api_contract"] = all(
        token in js
        for token in (
            "/v1/twin/trust",
            "/v1/decision/trusted-recovery",
            "optimizer_executed",
            "GATED / NOT EXECUTED",
        )
    )

    cov.stop()
    cov.save()
    coverage_percent = float(cov.report(show_missing=False))
    checks["signature_coverage_ge_90"] = coverage_percent >= 90.0

    payload = {
        "gate": "TRUST-RH Windows standalone signature acceptance",
        "coverage_percent": coverage_percent,
        "coverage_threshold_percent": 90.0,
        "checks": checks,
    }
    out = ROOT / "artifacts/trust_rh/windows_signature_acceptance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"TRUST_RH_WINDOWS_SIGNATURE_COVERAGE={coverage_percent:.2f}")
    print(f"TRUST_RH_WINDOWS_SIGNATURE_CHECKS={sum(checks.values())}/{len(checks)}")
    if not all(checks.values()):
        failed = [name for name, ok in checks.items() if not ok]
        raise SystemExit(f"TRUST_RH_WINDOWS_SIGNATURE_ACCEPTANCE=FAIL: {failed}")
    print("TRUST_RH_WINDOWS_SIGNATURE_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
