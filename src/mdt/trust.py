from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from math import exp
from typing import Any, Mapping, Sequence


class TrustDecision(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class TrustSignals:
    structural_consistency: float
    event_ledger_consistency: float
    model_evidence_coverage: float
    freshness: float
    event_age: float
    freshness_horizon: float
    hard_stop_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrustAssessment:
    decision: TrustDecision
    score: float
    authorize_threshold: float
    review_threshold: float
    signals: TrustSignals
    evidence_boundary: str = (
        "TRUST-RH is an engineering authorization gate over repository-observable evidence; "
        "it is not a calibrated probability that the physical plant state is correct."
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        return payload


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def structural_consistency(snapshot: Any, factory_model: Any) -> float:
    """Check that twin state references only known factory entities and has coherent counts."""
    machine_ids = {m.machine_id for m in factory_model.machines}
    operation_ids = {op.operation_id for job in factory_model.jobs for op in job.operations}
    job_ids = {j.job_id for j in factory_model.jobs}

    snap_machines = set(getattr(snapshot, "machines", {}))
    snap_operations = set(getattr(snapshot, "operations", {}))
    snap_jobs = set(getattr(snapshot, "jobs", {}))

    checks = [
        snap_machines.issubset(machine_ids),
        snap_operations.issubset(operation_ids),
        snap_jobs.issubset(job_ids),
        int(getattr(snapshot, "event_count", 0)) >= 0,
        float(getattr(snapshot, "timestamp", 0.0)) >= 0.0,
    ]
    return sum(bool(x) for x in checks) / len(checks)


def assess_trust(
    *,
    snapshot: Any,
    factory_model: Any,
    ledger_events: Sequence[Any],
    model_evidence: Mapping[str, bool],
    reference_time: float | None = None,
    freshness_horizon: float = 24.0,
    authorize_threshold: float = 0.82,
    review_threshold: float = 0.62,
) -> TrustAssessment:
    if freshness_horizon <= 0:
        raise ValueError("freshness_horizon must be positive")
    if not (0 <= review_threshold <= authorize_threshold <= 1):
        raise ValueError("thresholds must satisfy 0 <= review <= authorize <= 1")

    structural = structural_consistency(snapshot, factory_model)
    event_count = int(getattr(snapshot, "event_count", 0))
    ledger_consistency = 1.0 if event_count == len(ledger_events) else 0.0

    evidence_values = [bool(v) for v in model_evidence.values()]
    evidence_coverage = (sum(evidence_values) / len(evidence_values)) if evidence_values else 0.0

    snapshot_time = float(getattr(snapshot, "timestamp", 0.0))
    now = snapshot_time if reference_time is None else float(reference_time)
    event_age = max(0.0, now - snapshot_time)
    freshness = exp(-event_age / freshness_horizon)

    hard_stops: list[str] = []
    if structural < 1.0:
        hard_stops.append("TWIN_STRUCTURE_INCONSISTENT")
    if ledger_consistency < 1.0:
        hard_stops.append("EVENT_LEDGER_MISMATCH")
    if evidence_coverage < 0.75:
        hard_stops.append("MODEL_EVIDENCE_INSUFFICIENT")

    # Data integrity and structural consistency dominate; freshness is deliberately softer.
    score = _clip01(
        0.30 * structural
        + 0.25 * ledger_consistency
        + 0.20 * evidence_coverage
        + 0.25 * freshness
    )

    if hard_stops:
        decision = TrustDecision.BLOCKED
    elif score >= authorize_threshold:
        decision = TrustDecision.AUTHORIZED
    elif score >= review_threshold:
        decision = TrustDecision.HUMAN_REVIEW
    else:
        decision = TrustDecision.BLOCKED

    return TrustAssessment(
        decision=decision,
        score=score,
        authorize_threshold=authorize_threshold,
        review_threshold=review_threshold,
        signals=TrustSignals(
            structural_consistency=structural,
            event_ledger_consistency=ledger_consistency,
            model_evidence_coverage=evidence_coverage,
            freshness=freshness,
            event_age=event_age,
            freshness_horizon=freshness_horizon,
            hard_stop_reasons=tuple(hard_stops),
        ),
    )
