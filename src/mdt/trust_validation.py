from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from mdt.trust import TrustDecision, assess_trust


@dataclass(frozen=True)
class _Machine:
    machine_id: str


@dataclass(frozen=True)
class _Operation:
    operation_id: str


@dataclass(frozen=True)
class _Job:
    job_id: str
    operations: tuple[_Operation, ...]


@dataclass(frozen=True)
class _Factory:
    machines: tuple[_Machine, ...]
    jobs: tuple[_Job, ...]


def _fixture():
    factory = _Factory((_Machine("M1"),), (_Job("J1", (_Operation("O1"),)),))
    snapshot = SimpleNamespace(
        machines={"M1": object()}, jobs={"J1": object()}, operations={"O1": object()},
        event_count=2, timestamp=100.0,
    )
    ledger = [object(), object()]
    evidence = {"lateness": True, "cycle": True, "bottleneck": True, "anomaly": True}
    return factory, snapshot, ledger, evidence


def canonical_experiments() -> list[dict]:
    factory, snapshot, ledger, evidence = _fixture()
    partial_evidence = {"lateness": True, "cycle": True, "bottleneck": False, "anomaly": False}
    specs = [
        ("fresh_complete", 100.0, ledger, evidence, 0.82, 0.62, TrustDecision.AUTHORIZED),
        ("moderately_aged", 124.0, ledger, evidence, 0.82, 0.62, TrustDecision.AUTHORIZED),
        ("aging_review", 150.0, ledger, evidence, 0.82, 0.62, TrustDecision.HUMAN_REVIEW),
        ("strict_policy_review", 124.0, ledger, evidence, 0.90, 0.62, TrustDecision.HUMAN_REVIEW),
        ("ledger_mismatch", 100.0, ledger[:1], evidence, 0.82, 0.62, TrustDecision.BLOCKED),
        ("evidence_gap", 100.0, ledger, partial_evidence, 0.82, 0.62, TrustDecision.BLOCKED),
        ("stale_strict_block", 220.0, ledger, evidence, 0.90, 0.80, TrustDecision.BLOCKED),
    ]
    rows = []
    for name, ref, event_rows, model_evidence, auth_threshold, review_threshold, expected in specs:
        result = assess_trust(
            snapshot=snapshot,
            factory_model=factory,
            ledger_events=event_rows,
            model_evidence=model_evidence,
            reference_time=ref,
            freshness_horizon=24.0,
            authorize_threshold=auth_threshold,
            review_threshold=review_threshold,
        )
        rows.append({"name": name, "expected": expected.value, "actual": result.decision.value, "passed": result.decision == expected, "score": result.score})
    return rows


def sensitivity_grid() -> list[dict]:
    factory, snapshot, ledger, evidence = _fixture()
    partial_evidence = {"lateness": True, "cycle": True, "bottleneck": False, "anomaly": False}
    rows = []
    # 4 ages x 3 authorization thresholds x 4 review thresholds x 2 evidence modes = 96 cases.
    for age in (0, 24, 48, 96):
        for auth in (0.80, 0.85, 0.90):
            for review in (0.55, 0.62, 0.70, 0.76):
                for evidence_mode, model_evidence in (("complete", evidence), ("insufficient", partial_evidence)):
                    result = assess_trust(
                        snapshot=snapshot,
                        factory_model=factory,
                        ledger_events=ledger,
                        model_evidence=model_evidence,
                        reference_time=100.0 + age,
                        freshness_horizon=24.0,
                        authorize_threshold=auth,
                        review_threshold=review,
                    )
                    rows.append({
                        "age": age,
                        "authorize_threshold": auth,
                        "review_threshold": review,
                        "evidence_mode": evidence_mode,
                        "score": result.score,
                        "decision": result.decision.value,
                    })
    return rows


def validation_report() -> dict:
    canonical = canonical_experiments()
    sensitivity = sensitivity_grid()
    return {
        "algorithm": "TRUST-RH",
        "canonical": canonical,
        "canonical_passed": sum(row["passed"] for row in canonical),
        "canonical_total": len(canonical),
        "sensitivity_cases": len(sensitivity),
        "decision_counts": {name: sum(row["decision"] == name for row in sensitivity) for name in ("AUTHORIZED", "HUMAN_REVIEW", "BLOCKED")},
        "evidence_boundary": "Synthetic deterministic gate validation; no claim of calibrated plant-state correctness probability.",
    }
