from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

from mdt.ai import load_anomaly, load_bottleneck, load_bundle, load_cycle_time
from mdt.config import Settings
from mdt.decision import build_twin_future_state_stress_test
from mdt.domain import EventType, ManufacturingEvent
from mdt.service import TwinService
from mdt.trust import assess_trust


def _event(kind: EventType, timestamp: float, *, job: str | None = None, op: str | None = None, machine: str | None = None) -> ManufacturingEvent:
    key = f"mdt-demo:{kind.value}:{timestamp}:{job}:{op}:{machine}"
    return ManufacturingEvent(
        event_id=str(uuid5(NAMESPACE_URL, key)),
        event_type=kind,
        timestamp=timestamp,
        job_id=job,
        operation_id=op,
        machine_id=machine,
    )


def demo_events() -> list[ManufacturingEvent]:
    events: list[ManufacturingEvent] = []
    for job in ["J0", "J1", "J2", "J3", "J4", "J5"]:
        events.append(_event(EventType.JOB_RELEASED, 0.0, job=job))
    events += [
        _event(EventType.OPERATION_STARTED, 0.0, job="J0", op="J0-O0", machine="M2"),
        _event(EventType.OPERATION_STARTED, 0.0, job="J1", op="J1-O0", machine="M1"),
        _event(EventType.OPERATION_COMPLETED, 1.0, job="J0", op="J0-O0", machine="M2"),
        _event(EventType.OPERATION_STARTED, 1.0, job="J0", op="J0-O1", machine="M0"),
        _event(EventType.OPERATION_STARTED, 1.0, job="J2", op="J2-O0", machine="M2"),
        _event(EventType.OPERATION_COMPLETED, 4.0, job="J0", op="J0-O1", machine="M0"),
        _event(EventType.OPERATION_COMPLETED, 6.0, job="J2", op="J2-O0", machine="M2"),
        _event(EventType.OPERATION_STARTED, 6.0, job="J2", op="J2-O1", machine="M3"),
        _event(EventType.OPERATION_STARTED, 6.0, job="J4", op="J4-O0", machine="M2"),
        _event(EventType.OPERATION_COMPLETED, 8.0, job="J1", op="J1-O0", machine="M1"),
        _event(EventType.OPERATION_STARTED, 8.0, job="J3", op="J3-O0", machine="M1"),
        _event(EventType.OPERATION_COMPLETED, 10.0, job="J2", op="J2-O1", machine="M3"),
        _event(EventType.MACHINE_DOWN, 10.0, machine="M5"),
        _event(EventType.OPERATION_COMPLETED, 13.0, job="J3", op="J3-O0", machine="M1"),
        _event(EventType.OPERATION_STARTED, 13.0, job="J3", op="J3-O1", machine="M0"),
        _event(EventType.OPERATION_STARTED, 13.0, job="J5", op="J5-O0", machine="M1"),
        _event(EventType.MACHINE_UP, 14.0, machine="M5"),
        _event(EventType.OPERATION_COMPLETED, 15.0, job="J4", op="J4-O0", machine="M2"),
        _event(EventType.OPERATION_STARTED, 15.0, job="J1", op="J1-O1", machine="M2"),
        _event(EventType.OPERATION_COMPLETED, 16.0, job="J5", op="J5-O0", machine="M1"),
        _event(EventType.OPERATION_STARTED, 16.0, job="J4", op="J4-O1", machine="M1"),
        _event(EventType.OPERATION_STARTED, 16.0, job="J5", op="J5-O1", machine="M3"),
        _event(EventType.OPERATION_COMPLETED, 18.0, job="J3", op="J3-O1", machine="M0"),
        _event(EventType.OPERATION_COMPLETED, 19.0, job="J4", op="J4-O1", machine="M1"),
        _event(EventType.OPERATION_COMPLETED, 19.0, job="J5", op="J5-O1", machine="M3"),
        _event(EventType.OPERATION_STARTED, 19.0, job="J0", op="J0-O2", machine="M1"),
        _event(EventType.OPERATION_COMPLETED, 20.0, job="J1", op="J1-O1", machine="M2"),
    ]
    return events


def _sqlite_path(settings: Settings) -> Path | None:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        return None
    return Path(settings.database_url[len(prefix):])


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the deterministic MDT portfolio demo.")
    parser.add_argument("--reset", action="store_true", help="Delete the dedicated demo database before loading events.")
    parser.add_argument("--build-evidence", action="store_true", help="Run a compact stress-test workflow and write a demo evidence artifact.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault("MDT_DATABASE_URL", "sqlite:///runtime/mdt_demo.db")
    settings = Settings.from_env(root)
    db_path = _sqlite_path(settings)
    if args.reset and db_path and db_path.exists():
        db_path.unlink()

    with TwinService(settings) as service:
        if service.repository.count() == 0:
            for event in demo_events():
                service.engine.apply(event)
                service.repository.append(event)
        snapshot = service.engine.snapshot()
        trust = assess_trust(
            snapshot=snapshot,
            factory_model=service.model,
            ledger_events=service.repository.list_events(),
            model_evidence={"lateness": True, "cycle_time": True, "bottleneck": True, "anomaly": True},
            reference_time=snapshot.timestamp,
        )
        summary = {
            "mode": "DETERMINISTIC_PORTFOLIO_DEMO",
            "database": str(db_path) if db_path else settings.database_url,
            "event_count": snapshot.event_count,
            "twin_timestamp": snapshot.timestamp,
            "wip_jobs": snapshot.wip_jobs,
            "ready_operations": snapshot.ready_operations,
            "trust_decision": trust.decision.value,
            "trust_score": trust.score,
        }

        if args.build_evidence:
            artifact_dir = root / "artifacts" / "ai"
            result = build_twin_future_state_stress_test(
                service.model,
                snapshot,
                load_bundle(artifact_dir / "lateness_risk.joblib"),
                load_cycle_time(artifact_dir / "cycle_time.joblib"),
                load_bottleneck(artifact_dir / "bottleneck.joblib"),
                load_anomaly(artifact_dir / "anomaly.joblib"),
                backend="auto",
                due_factor=1.35,
                time_limit=30.0,
                replications=12,
                base_seed=20260815,
                processing_cv=0.14,
                mtbf=100.0,
                mttr=8.0,
                risk_aversion=0.45,
                stressed_machine_id="M5",
                stressed_machine_mtbf=32.0,
                stressed_machine_mttr=14.0,
            )
            summary["decision"] = {
                "run_id": result.get("run_id"),
                "recommended_policy": result.get("stress_test", {}).get("recommended_policy"),
                "rationale": result.get("stress_test", {}).get("rationale"),
                "nominal_solver": result.get("nominal_optimized", {}).get("solver", {}),
                "policy_summaries": result.get("stress_test", {}).get("summaries", []),
                "evidence_labels": result.get("evidence_labels", {}),
            }
            out = root / "artifacts" / "demo"
            out.mkdir(parents=True, exist_ok=True)
            (out / "latest_demo_evidence.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(summary, indent=2, sort_keys=True))
    print("MDT_PORTFOLIO_DEMO_PREPARED=PASS")


if __name__ == "__main__":
    main()
