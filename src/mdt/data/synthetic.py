from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path


DATASET_FILE = "mdt_operational_scenarios_150000.csv"
MANIFEST_FILE = "DATASET_MANIFEST.json"
SAMPLE_FIELDS = (
    "record_id",
    "scenario_id",
    "scenario_class",
    "event_type",
    "machine_id",
    "machine_state",
    "risk_label",
    "recommended_action",
    "policy_outcome",
)


def _dataset_paths(project_root: Path) -> tuple[Path, Path]:
    directory = project_root / "data" / "synthetic"
    return directory / DATASET_FILE, directory / MANIFEST_FILE


@lru_cache(maxsize=4)
def synthetic_dataset_summary(project_root: str) -> dict:
    """Summarize the governed synthetic dataset for the workbench.

    The table is intentionally not replayed into the canonical twin: it is a
    scenario-observation dataset, not one valid chronological event history for
    the FT06 factory model.
    """

    csv_path, manifest_path = _dataset_paths(Path(project_root))
    if not csv_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("synthetic dataset package is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    scenario_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    policy_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()
    anomaly_count = 0
    utilization_total = 0.0
    risk_total = 0.0
    lateness_total = 0.0
    row_count = 0
    all_rows_labeled_synthetic = True
    sample: list[dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        column_count = len(reader.fieldnames or ())
        for row in reader:
            row_count += 1
            scenario_counts[row["scenario_class"]] += 1
            event_counts[row["event_type"]] += 1
            state_counts[row["machine_state"]] += 1
            risk_counts[row["risk_label"]] += 1
            policy_counts[row["policy_outcome"]] += 1
            quality_counts[row["quality_label"]] += 1
            all_rows_labeled_synthetic = all_rows_labeled_synthetic and row["source_kind"] == "synthetic_demo" and row["evidence_label"] == "synthetic_scenario_observation"
            anomaly_count += row["anomaly_flag"] == "true"
            utilization_total += float(row["machine_utilization_pct"])
            risk_total += float(row["risk_score"])
            lateness_total += float(row["lateness_min"])
            if len(sample) < 5:
                sample.append({field: row[field] for field in SAMPLE_FIELDS})

    integrity = {
        "file_present": True,
        "manifest_present": True,
        "row_count_matches_manifest": row_count == int(manifest.get("rows", -1)),
        "column_count_matches_manifest": column_count == int(manifest.get("columns", -1)),
        "sha256_matches_manifest": digest == str(manifest.get("sha256", "")).lower(),
        "all_rows_labeled_synthetic": all_rows_labeled_synthetic,
    }
    integrity["ready"] = all(integrity.values())
    return {
        "dataset_name": manifest["dataset_name"],
        "file": DATASET_FILE,
        "download_url": "/v1/data/synthetic/download",
        "rows": row_count,
        "columns": column_count,
        "schema_version": manifest["schema_version"],
        "seed": manifest["seed"],
        "sha256": digest,
        "source_kind": "synthetic_demo",
        "evidence_label": "SYNTHETIC / REPRODUCIBLE / DEMO-ONLY",
        "dataset_role": "Scenario analytics and research demonstration; not canonical live plant telemetry.",
        "evidence_boundary": manifest["evidence_boundary"],
        "coverage": manifest["coverage"],
        "distributions": {
            "scenario_classes": dict(sorted(scenario_counts.items())),
            "event_types": dict(sorted(event_counts.items())),
            "machine_states": dict(sorted(state_counts.items())),
            "risk_labels": dict(sorted(risk_counts.items())),
            "policy_outcomes": dict(sorted(policy_counts.items())),
            "quality_labels": dict(sorted(quality_counts.items())),
        },
        "metrics": {
            "anomaly_rate": round(anomaly_count / row_count, 4) if row_count else 0.0,
            "mean_machine_utilization_pct": round(utilization_total / row_count, 2) if row_count else 0.0,
            "mean_risk_score": round(risk_total / row_count, 4) if row_count else 0.0,
            "mean_lateness_min": round(lateness_total / row_count, 2) if row_count else 0.0,
        },
        "sample": sample,
        "public_references": manifest.get("public_references", []),
        "integrity": integrity,
    }
