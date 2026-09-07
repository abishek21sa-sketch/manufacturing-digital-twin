from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from mdt.data.synthetic import synthetic_dataset_summary


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "synthetic"
CSV_PATH = DATA_DIR / "mdt_operational_scenarios_150000.csv"
MANIFEST_PATH = DATA_DIR / "DATASET_MANIFEST.json"
EXPECTED_ROWS = 150_000
EXPECTED_COLUMNS = 80


def test_synthetic_dataset_is_reproducible_and_complete() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["rows"] == EXPECTED_ROWS
    assert manifest["schema_version"] == "mdt-synthetic-scenario-v2"
    assert manifest["seed"] == 2_026_0906
    assert manifest["columns"] == EXPECTED_COLUMNS
    assert manifest["sha256"] == hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()

    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert len(reader.fieldnames or ()) == EXPECTED_COLUMNS
        required = {
            "material_availability_pct", "maintenance_type", "energy_intensity_kwh_per_unit",
            "humidity_pct", "sensor_completeness_pct", "data_quality_flag",
            "model_confidence", "decision_latency_min",
        }
        assert required.issubset(set(reader.fieldnames or ()))
        count = 0
        record_ids: set[str] = set()
        scenario_counts: Counter[str] = Counter()
        event_types: set[str] = set()
        states: set[str] = set()
        risks: set[str] = set()
        qualities: set[str] = set()
        outcomes: set[str] = set()
        source_kinds: set[str] = set()
        evidence_labels: set[str] = set()
        for row in reader:
            count += 1
            record_ids.add(row["record_id"])
            scenario_counts[row["scenario_class"]] += 1
            event_types.add(row["event_type"])
            states.add(row["machine_state"])
            risks.add(row["risk_label"])
            qualities.add(row["quality_label"])
            outcomes.add(row["policy_outcome"])
            source_kinds.add(row["source_kind"])
            evidence_labels.add(row["evidence_label"])

    assert count == EXPECTED_ROWS
    assert len(record_ids) == EXPECTED_ROWS
    assert source_kinds == {"synthetic_demo"}
    assert evidence_labels == {"synthetic_scenario_observation"}
    assert set(manifest["coverage"]["scenario_classes"]) == set(scenario_counts)
    assert event_types == set(manifest["coverage"]["event_types"])
    assert set(scenario_counts.values()) == {15_000}
    assert states == {"idle", "busy", "down"}
    assert risks == {"low", "medium", "high"}
    assert qualities == {"pass", "rework", "scrap"}
    assert outcomes == {"on_time", "late", "recovered", "blocked"}


def test_synthetic_dataset_has_consistent_event_state_labels() -> None:
    allowed_quality_flags = {"nominal", "late_arrival", "missing_sensor", "outlier_review"}
    allowed_maintenance = {"none", "preventive", "corrective", "condition_based"}
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            assert row["source_kind"] == "synthetic_demo"
            assert row["evidence_label"] == "synthetic_scenario_observation"
            assert row["anomaly_flag"] in {"true", "false"}
            assert 0.0 <= float(row["risk_score"]) <= 1.0
            assert 0.0 <= float(row["anomaly_score"]) <= 1.0
            assert 0.0 <= float(row["yield_pct"]) <= 100.0
            assert 0.0 <= float(row["material_availability_pct"]) <= 100.0
            assert 0.0 <= float(row["sensor_completeness_pct"]) <= 100.0
            assert 0.35 <= float(row["model_confidence"]) <= 0.995
            assert float(row["capacity_slack_min"]) >= 0.0
            assert float(row["downtime_min"]) >= 0.0
            assert int(row["completed_units"]) <= int(row["order_quantity_units"])
            assert row["data_quality_flag"] in allowed_quality_flags
            assert row["maintenance_type"] in allowed_maintenance
            if row["event_type"] == "machine_down":
                assert row["failure_mode"] != "none"
                assert row["machine_state"] == "down"
            if row["event_type"] == "machine_up":
                assert row["machine_state"] == "idle"


def test_synthetic_dataset_summary_is_integrity_checked() -> None:
    summary = synthetic_dataset_summary(str(ROOT))
    assert summary["rows"] == EXPECTED_ROWS
    assert summary["columns"] == EXPECTED_COLUMNS
    assert summary["source_kind"] == "synthetic_demo"
    assert summary["integrity"]["ready"] is True
    assert summary["download_url"] == "/v1/data/synthetic/download"
    assert len(summary["sample"]) == 5
    assert set(summary["distributions"]["event_types"]) == {
        "job_released",
        "operation_started",
        "operation_completed",
        "machine_down",
        "machine_up",
    }
