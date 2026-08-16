from __future__ import annotations

import json
from pathlib import Path

from mdt.ai import (
    save_bundle,
    save_operational_ai,
    train_anomaly_model,
    train_bottleneck_model,
    train_cycle_time_model,
    train_lateness_model,
)
from mdt.config import Settings
from mdt.data import load_orlib_instance


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings.from_env(root)
    model = load_orlib_instance(root / "data" / "external" / "orlib" / "jobshop1.txt", settings.benchmark_instance)

    lateness, lateness_report = train_lateness_model(model)
    save_bundle(
        lateness,
        lateness_report,
        root / "artifacts" / "ai" / "lateness_risk.joblib",
        root / "docs" / "evidence" / "AI_VALIDATION.json",
    )

    cycle, cycle_report = train_cycle_time_model(model, n_scenarios=300)
    bottleneck, bottleneck_report = train_bottleneck_model(model, n_scenarios=120)
    anomaly, anomaly_report = train_anomaly_model()
    save_operational_ai(
        cycle,
        cycle_report,
        bottleneck,
        bottleneck_report,
        anomaly,
        anomaly_report,
        root / "artifacts" / "ai",
        root / "docs" / "evidence" / "OPERATIONAL_AI_VALIDATION.json",
    )

    report = {
        "lateness": lateness_report,
        "cycle_time": cycle_report,
        "bottleneck": bottleneck_report,
        "anomaly": anomaly_report,
    }
    print(json.dumps(report, indent=2))
    print("AI_TRAINING=PASS")


if __name__ == "__main__":
    main()
