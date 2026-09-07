"""Generate the reproducible, demo-safe MDT portfolio dataset.

The output is intentionally a scenario-observation table, not a claim of plant
telemetry and not a replacement for the canonical event-ledger adapter.  Each
five-row scenario exercises the five canonical event types while retaining
features useful for risk, capacity, reliability, quality, and policy demos.

Usage:
    python scripts/generate_synthetic_dataset.py
    python scripts/generate_synthetic_dataset.py --rows 150000 --seed 20260906
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_ROWS = 150_000
DEFAULT_SEED = 2_026_0906
SCHEMA_VERSION = "mdt-synthetic-scenario-v2"
DATASET_FILE = "mdt_operational_scenarios_150000.csv"

SCENARIO_CLASSES = (
    "nominal_flow",
    "high_wip",
    "tight_due_dates",
    "process_variability",
    "machine_failure",
    "machine_recovery",
    "quality_excursion",
    "material_delay",
    "capacity_bottleneck",
    "policy_tradeoff",
)
EVENT_TYPES = (
    "job_released",
    "operation_started",
    "operation_completed",
    "machine_down",
    "machine_up",
)
MACHINES = tuple(f"M{i}" for i in range(6))
PRODUCT_FAMILIES = ("Aero", "Pump", "Drive", "Valve", "Sensor")
POLICIES = ("FIFO", "SPT", "EDD", "planned")
FAILURE_MODES = ("bearing", "sensor", "tool_wear", "thermal", "material", "software")
ROUTINGS = ("ft06_jobshop", "flowline", "reentrant", "flexible_jobshop", "inspection_loop")
SHIFTS = ("A", "B", "C")
OPERATOR_TEAMS = ("TEAM-01", "TEAM-02", "TEAM-03", "TEAM-04", "TEAM-05")
SUPPLIERS = ("SUP-01", "SUP-02", "SUP-03", "SUP-04", "SUP-05", "SUP-06")
MAINTENANCE_TYPES = ("none", "preventive", "corrective", "condition_based")
DATA_QUALITY_FLAGS = ("nominal", "late_arrival", "missing_sensor", "outlier_review")

FIELDNAMES = (
    "record_id",
    "scenario_id",
    "scenario_class",
    "observed_at_utc",
    "factory_id",
    "line_id",
    "machine_id",
    "job_id",
    "operation_id",
    "event_type",
    "machine_state",
    "product_family",
    "routing_profile",
    "priority",
    "due_factor",
    "process_cv",
    "plant_mtbf_hr",
    "plant_mttr_hr",
    "machine_mtbf_hr",
    "machine_mttr_hr",
    "release_time_min",
    "due_time_min",
    "planned_start_min",
    "actual_start_min",
    "completion_time_min",
    "nominal_processing_min",
    "observed_processing_min",
    "process_deviation_pct",
    "queue_before",
    "wip_jobs",
    "conwip_cap",
    "machine_utilization_pct",
    "capacity_slack_min",
    "failure_mode",
    "repair_duration_min",
    "tool_wear_min",
    "air_temperature_c",
    "process_temperature_c",
    "vibration_rms_mm_s",
    "torque_nm",
    "energy_kwh",
    "shift_code",
    "operator_team",
    "supplier_id",
    "material_lot_id",
    "material_availability_pct",
    "material_lead_time_hr",
    "inventory_on_hand_units",
    "demand_units",
    "order_quantity_units",
    "completed_units",
    "scrap_units",
    "rework_units",
    "setup_time_min",
    "changeover_count",
    "maintenance_due_in_hr",
    "maintenance_type",
    "downtime_min",
    "energy_intensity_kwh_per_unit",
    "carbon_kg_co2e",
    "humidity_pct",
    "pressure_kpa",
    "sound_level_db",
    "sensor_completeness_pct",
    "data_quality_flag",
    "model_confidence",
    "decision_latency_min",
    "spc_z_score",
    "yield_pct",
    "quality_label",
    "lateness_min",
    "risk_score",
    "risk_label",
    "anomaly_score",
    "anomaly_flag",
    "policy_evaluated",
    "recommended_action",
    "policy_outcome",
    "evidence_label",
    "source_kind",
)


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 4)


def _risk_label(score: float) -> str:
    if score >= 0.67:
        return "high"
    if score >= 0.34:
        return "medium"
    return "low"


def _scenario_parameters(scenario_class: str, rng: random.Random) -> dict[str, float]:
    """Return correlated operating parameters for one scenario family."""

    base = {
        "due_factor": rng.uniform(1.10, 1.35),
        "process_cv": rng.uniform(0.06, 0.14),
        "machine_mtbf": rng.uniform(70.0, 180.0),
        "machine_mttr": rng.uniform(5.0, 18.0),
        "utilization": rng.uniform(0.35, 0.72),
        "wip": rng.randint(2, 8),
        "queue": rng.randint(0, 5),
        "failure_pressure": 0.08,
        "quality_pressure": 0.04,
        "material_pressure": 0.03,
    }
    overrides = {
        "nominal_flow": {"utilization": rng.uniform(0.30, 0.62), "failure_pressure": 0.03},
        "high_wip": {"utilization": rng.uniform(0.72, 0.96), "wip": rng.randint(9, 18), "queue": rng.randint(6, 14)},
        "tight_due_dates": {"due_factor": rng.uniform(1.02, 1.16), "utilization": rng.uniform(0.60, 0.90)},
        "process_variability": {"process_cv": rng.uniform(0.18, 0.42), "quality_pressure": 0.10},
        "machine_failure": {"machine_mtbf": rng.uniform(18.0, 60.0), "machine_mttr": rng.uniform(12.0, 32.0), "failure_pressure": 0.55},
        "machine_recovery": {"machine_mtbf": rng.uniform(22.0, 75.0), "machine_mttr": rng.uniform(16.0, 42.0), "failure_pressure": 0.72},
        "quality_excursion": {"process_cv": rng.uniform(0.12, 0.30), "quality_pressure": 0.58, "utilization": rng.uniform(0.55, 0.88)},
        "material_delay": {"material_pressure": 0.70, "queue": rng.randint(4, 12), "due_factor": rng.uniform(1.05, 1.25)},
        "capacity_bottleneck": {"utilization": rng.uniform(0.88, 0.995), "wip": rng.randint(10, 22), "queue": rng.randint(8, 18)},
        "policy_tradeoff": {"due_factor": rng.uniform(1.03, 1.22), "utilization": rng.uniform(0.65, 0.94), "failure_pressure": 0.22},
    }[scenario_class]
    base.update(overrides)
    return base


def _make_row(index: int, rows: int, rng: random.Random, start: datetime) -> dict[str, object]:
    class_width = max(1, rows // len(SCENARIO_CLASSES))
    scenario_class = SCENARIO_CLASSES[min(index // class_width, len(SCENARIO_CLASSES) - 1)]
    event_offset = index % len(EVENT_TYPES)
    event_type = EVENT_TYPES[event_offset]
    scenario_number = index // len(EVENT_TYPES) + 1
    scenario_id = f"SCN-{scenario_number:05d}"
    record_id = f"MDT-SYN-{index + 1:06d}"
    job_id = f"J-{scenario_number:05d}"
    operation_id = f"{job_id}-O{event_offset if event_offset < 3 else 0}"
    machine_id = MACHINES[(scenario_number * 3 + event_offset) % len(MACHINES)]
    p = _scenario_parameters(scenario_class, rng)

    nominal = rng.uniform(4.0, 32.0)
    deviation = rng.gauss(0.0, p["process_cv"] * 100.0)
    if scenario_class in {"process_variability", "quality_excursion"}:
        deviation += rng.choice((-1, 1)) * rng.uniform(8.0, 30.0)
    observed = max(1.0, nominal * (1.0 + deviation / 100.0))
    release = float(scenario_number * 30 + rng.uniform(0.0, 8.0))
    planned_start = release + p["queue"] * 2.0 + rng.uniform(1.0, 8.0)
    delay = max(0.0, p["queue"] * 1.5 + (observed - nominal) + rng.gauss(0.0, 3.0))
    actual_start = planned_start + delay
    completion = actual_start + observed
    due = release + nominal * p["due_factor"] + rng.uniform(12.0, 48.0)
    lateness = max(0.0, completion - due)

    failure_mode = "none"
    if event_type in {"machine_down", "machine_up"}:
        failure_mode = rng.choice(FAILURE_MODES)
    elif scenario_class in {"machine_failure", "machine_recovery"} and rng.random() < p["failure_pressure"]:
        failure_mode = rng.choice(FAILURE_MODES)
    repair_duration = rng.uniform(0.0, p["machine_mttr"] * 60.0) if failure_mode != "none" else 0.0
    if event_type == "machine_up":
        machine_state = "idle"
    elif event_type == "machine_down":
        machine_state = "down"
    elif event_type == "operation_started":
        machine_state = "busy"
    else:
        machine_state = "idle"

    utilization = _clamp(p["utilization"] * 100.0 + rng.gauss(0.0, 4.5), 5.0, 99.8)
    capacity_slack = max(0.0, (100.0 - utilization) * rng.uniform(0.45, 1.35))
    temp_air = rng.gauss(23.0, 2.8)
    temp_process = temp_air + rng.gauss(18.0, 1.2)
    vibration = max(0.05, rng.gauss(1.9, 0.7) + (2.3 if failure_mode == "bearing" else 0.0))
    torque = max(2.0, rng.gauss(40.0, 8.0) + (6.0 if failure_mode == "tool_wear" else 0.0))
    energy_kwh = max(0.1, observed * torque / 3600.0)
    tool_wear = max(0.0, rng.gauss(95.0, 45.0) + (55.0 if failure_mode == "tool_wear" else 0.0))
    spc_z = rng.gauss(0.0, 1.0) + (rng.choice((-1.0, 1.0)) * rng.uniform(1.5, 3.0) if scenario_class == "quality_excursion" else 0.0)
    yield_pct = _clamp(99.4 - abs(spc_z) * 2.4 - p["quality_pressure"] * 10.0 + rng.gauss(0.0, 0.9), 70.0, 100.0)
    quality_label = "scrap" if yield_pct < 88.0 else "rework" if yield_pct < 96.0 else "pass"

    shift_code = SHIFTS[(scenario_number + event_offset) % len(SHIFTS)]
    operator_team = OPERATOR_TEAMS[(scenario_number * 2 + event_offset) % len(OPERATOR_TEAMS)]
    supplier_id = SUPPLIERS[(scenario_number + (1 if p["material_pressure"] > 0.5 else 0)) % len(SUPPLIERS)]
    material_lot_id = f"LOT-{((scenario_number - 1) % 2400) + 1:04d}"
    material_availability = _clamp(99.0 - p["material_pressure"] * 74.0 + rng.gauss(0.0, 2.0), 8.0, 100.0)
    material_lead_time = max(1.0, rng.gauss(18.0 + p["material_pressure"] * 56.0, 5.0))
    demand_units = max(1, int(round(rng.gauss(48.0 + p["utilization"] * 35.0, 9.0))))
    order_quantity = max(1, int(round(demand_units * rng.uniform(0.65, 1.35))))
    inventory_on_hand = max(0, int(round(order_quantity * material_availability / 100.0 + rng.gauss(8.0, 5.0))))
    completed_units = max(0, min(order_quantity, int(round(order_quantity * yield_pct / 100.0))))
    scrap_units = max(0, int(round(order_quantity * max(0.0, 100.0 - yield_pct) / 100.0 * (0.55 if quality_label == "scrap" else 0.25))))
    rework_units = max(0, int(round(order_quantity * (0.10 if quality_label == "rework" else 0.025))))
    setup_time = max(0.5, rng.gauss(6.0, 1.8) + (2.5 if event_type == "operation_started" else 0.0))
    changeover_count = max(0, int(round(rng.gauss(1.0 + p["utilization"] * 2.0, 0.8))))
    maintenance_due = max(0.0, rng.gauss(72.0 - p["failure_pressure"] * 80.0, 18.0))
    if failure_mode != "none":
        maintenance_type = "corrective"
    elif maintenance_due < 24.0:
        maintenance_type = "preventive"
    else:
        maintenance_type = MAINTENANCE_TYPES[3] if rng.random() < 0.18 else "none"
    downtime = repair_duration if machine_state == "down" or failure_mode != "none" else max(0.0, rng.gauss(2.0, 1.2))
    energy_intensity = max(0.001, energy_kwh / max(1, completed_units))
    carbon = max(0.0, energy_kwh * 0.36 + rng.gauss(0.0, 0.04))
    humidity = _clamp(rng.gauss(48.0, 9.0) + (4.0 if scenario_class == "quality_excursion" else 0.0), 15.0, 85.0)
    pressure = _clamp(rng.gauss(101.3, 1.4) + (1.8 if failure_mode == "thermal" else 0.0), 96.0, 108.0)
    sound_level = _clamp(rng.gauss(68.0, 5.0) + (8.0 if failure_mode == "bearing" else 0.0), 45.0, 100.0)
    sensor_completeness = _clamp(99.5 - (7.0 if failure_mode == "sensor" else 0.0) - (3.0 if scenario_class == "quality_excursion" else 0.0) + rng.gauss(0.0, 0.8), 80.0, 100.0)
    if sensor_completeness < 90.0:
        data_quality_flag = "missing_sensor"
    elif abs(deviation) > 35.0:
        data_quality_flag = "outlier_review"
    elif p["material_pressure"] > 0.55 and rng.random() < 0.35:
        data_quality_flag = "late_arrival"
    else:
        data_quality_flag = "nominal"
    model_confidence = _clamp(0.98 - abs(deviation) / 180.0 - (1.0 - sensor_completeness / 100.0) * 0.55 + rng.gauss(0.0, 0.015), 0.35, 0.995)
    decision_latency = max(0.2, rng.gauss(3.0, 1.2) + (2.0 if data_quality_flag != "nominal" or event_type == "machine_down" else 0.0))

    risk_score = _clamp(
        0.22 * min(1.0, utilization / 100.0)
        + 0.18 * min(1.0, p["process_cv"] / 0.35)
        + 0.18 * min(1.0, lateness / 40.0)
        + 0.18 * min(1.0, p["failure_pressure"])
        + 0.12 * min(1.0, abs(spc_z) / 3.0)
        + 0.12 * min(1.0, p["material_pressure"]),
        0.0,
        1.0,
    )
    # Keep the tail operationally meaningful: a forced machine-down event,
    # severe reliability scenario, or near-saturated bottleneck must not be
    # diluted into a low-risk label by averaging unrelated signals.
    risk_floor = 0.0
    if event_type == "machine_down":
        risk_floor = rng.uniform(0.72, 0.92)
    elif scenario_class in {"machine_failure", "machine_recovery"}:
        risk_floor = rng.uniform(0.60, 0.84)
    elif scenario_class == "capacity_bottleneck" and utilization >= 90.0:
        risk_floor = rng.uniform(0.68, 0.86)
    elif scenario_class == "quality_excursion" and abs(spc_z) >= 2.0:
        risk_floor = rng.uniform(0.67, 0.82)
    risk_score = max(risk_score, risk_floor)
    anomaly_score = _clamp(
        0.38 * min(1.0, vibration / 6.0)
        + 0.24 * min(1.0, abs(spc_z) / 4.0)
        + 0.18 * min(1.0, abs(deviation) / 50.0)
        + 0.20 * (1.0 if failure_mode != "none" else 0.0),
        0.0,
        1.0,
    )
    anomaly_flag = anomaly_score >= 0.55 or event_type == "machine_down"

    if scenario_class in {"machine_failure", "machine_recovery"} or failure_mode != "none":
        recommended_action = "maintenance" if machine_state == "down" else "inspect"
    elif scenario_class == "capacity_bottleneck" or utilization >= 90.0:
        recommended_action = "reroute"
    elif scenario_class == "material_delay":
        recommended_action = "hold"
    elif risk_score >= 0.67:
        recommended_action = "expedite"
    else:
        recommended_action = "no_change"

    if lateness <= 0.0:
        policy_outcome = "on_time"
    elif recommended_action in {"maintenance", "reroute", "expedite"} and lateness < 25.0:
        policy_outcome = "recovered"
    elif machine_state == "down" or p["material_pressure"] > 0.6:
        policy_outcome = "blocked"
    else:
        policy_outcome = "late"

    timestamp = start + timedelta(minutes=index * 3)
    return {
        "record_id": record_id,
        "scenario_id": scenario_id,
        "scenario_class": scenario_class,
        "observed_at_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "factory_id": "DEMO-PLANT-01",
        "line_id": f"LINE-{(scenario_number % 4) + 1:02d}",
        "machine_id": machine_id,
        "job_id": job_id,
        "operation_id": operation_id,
        "event_type": event_type,
        "machine_state": machine_state,
        "product_family": PRODUCT_FAMILIES[(scenario_number + event_offset) % len(PRODUCT_FAMILIES)],
        "routing_profile": ROUTINGS[(scenario_number + event_offset) % len(ROUTINGS)],
        "priority": (scenario_number + event_offset) % 5 + 1,
        "due_factor": round(p["due_factor"], 4),
        "process_cv": round(p["process_cv"], 4),
        "plant_mtbf_hr": round(rng.uniform(90.0, 260.0), 2),
        "plant_mttr_hr": round(rng.uniform(3.0, 14.0), 2),
        "machine_mtbf_hr": round(p["machine_mtbf"], 2),
        "machine_mttr_hr": round(p["machine_mttr"], 2),
        "release_time_min": round(release, 2),
        "due_time_min": round(due, 2),
        "planned_start_min": round(planned_start, 2),
        "actual_start_min": round(actual_start, 2),
        "completion_time_min": round(completion, 2),
        "nominal_processing_min": round(nominal, 2),
        "observed_processing_min": round(observed, 2),
        "process_deviation_pct": round(deviation, 2),
        "queue_before": p["queue"],
        "wip_jobs": p["wip"],
        "conwip_cap": 3 if scenario_class in {"high_wip", "capacity_bottleneck"} else rng.choice((3, 5, 8)),
        "machine_utilization_pct": utilization,
        "capacity_slack_min": round(capacity_slack, 2),
        "failure_mode": failure_mode,
        "repair_duration_min": round(repair_duration, 2),
        "tool_wear_min": round(tool_wear, 2),
        "air_temperature_c": round(temp_air, 2),
        "process_temperature_c": round(temp_process, 2),
        "vibration_rms_mm_s": round(vibration, 3),
        "torque_nm": round(torque, 2),
        "energy_kwh": round(energy_kwh, 3),
        "shift_code": shift_code,
        "operator_team": operator_team,
        "supplier_id": supplier_id,
        "material_lot_id": material_lot_id,
        "material_availability_pct": material_availability,
        "material_lead_time_hr": round(material_lead_time, 2),
        "inventory_on_hand_units": inventory_on_hand,
        "demand_units": demand_units,
        "order_quantity_units": order_quantity,
        "completed_units": completed_units,
        "scrap_units": scrap_units,
        "rework_units": rework_units,
        "setup_time_min": round(setup_time, 2),
        "changeover_count": changeover_count,
        "maintenance_due_in_hr": round(maintenance_due, 2),
        "maintenance_type": maintenance_type,
        "downtime_min": round(downtime, 2),
        "energy_intensity_kwh_per_unit": round(energy_intensity, 4),
        "carbon_kg_co2e": round(carbon, 3),
        "humidity_pct": humidity,
        "pressure_kpa": pressure,
        "sound_level_db": sound_level,
        "sensor_completeness_pct": sensor_completeness,
        "data_quality_flag": data_quality_flag,
        "model_confidence": model_confidence,
        "decision_latency_min": round(decision_latency, 2),
        "spc_z_score": round(spc_z, 3),
        "yield_pct": yield_pct,
        "quality_label": quality_label,
        "lateness_min": round(lateness, 2),
        "risk_score": risk_score,
        "risk_label": _risk_label(risk_score),
        "anomaly_score": anomaly_score,
        "anomaly_flag": str(bool(anomaly_flag)).lower(),
        "policy_evaluated": POLICIES[(scenario_number + event_offset) % len(POLICIES)],
        "recommended_action": recommended_action,
        "policy_outcome": policy_outcome,
        "evidence_label": "synthetic_scenario_observation",
        "source_kind": "synthetic_demo",
    }


def generate(rows: int, seed: int, output_dir: Path) -> tuple[Path, Path]:
    if rows < len(SCENARIO_CLASSES):
        raise ValueError(f"rows must be at least {len(SCENARIO_CLASSES)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / DATASET_FILE
    manifest_path = output_dir / "DATASET_MANIFEST.json"
    rng = random.Random(seed)
    start = datetime(2026, 1, 5, 6, 0, tzinfo=timezone.utc)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        for index in range(rows):
            writer.writerow(_make_row(index, rows, rng, start))

    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = {
        "dataset_name": "MDT Operational Scenario Dataset",
        "file": csv_path.name,
        "rows": rows,
        "columns": len(FIELDNAMES),
        "schema_version": SCHEMA_VERSION,
        "generator": "scripts/generate_synthetic_dataset.py",
        "seed": seed,
        "sha256": digest,
        "evidence_boundary": "Synthetic, deterministic portfolio data for demonstrations, testing, and research workflows. It is not plant telemetry, a public benchmark, or a realized operational claim.",
        "coverage": {
            "scenario_classes": list(SCENARIO_CLASSES),
            "event_types": list(EVENT_TYPES),
            "machine_states": ["idle", "busy", "down"],
            "failure_modes": ["none", *FAILURE_MODES],
            "policy_outcomes": ["on_time", "late", "recovered", "blocked"],
            "quality_labels": ["pass", "rework", "scrap"],
        },
        "public_references": [
            {
                "name": "UCI AI4I 2020 Predictive Maintenance Dataset",
                "url": "https://archive.ics.uci.edu/dataset/601/ai4i",
                "use": "Publicly available 10,000-row predictive-maintenance reference; itself synthetic and not event-sourced scheduling data.",
                "license": "CC BY 4.0",
            },
            {
                "name": "UCI SECOM",
                "url": "https://archive.ics.uci.edu/dataset/179/secom",
                "use": "Public semiconductor manufacturing sensor/yield reference with 1,567 examples and 591 features.",
                "license": "CC BY 4.0",
            },
            {
                "name": "NASA Prognostics Center of Excellence data repository",
                "url": "https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/",
                "use": "Public prognostics and run-to-failure references; useful for reliability-method comparisons, not a factory event ledger.",
                "license": "Check source-specific terms before redistribution",
            },
            {
                "name": "OR-Library job-shop scheduling benchmarks",
                "url": "https://people.brunel.ac.uk/~mastjjb/jeb/orlib/jobshopinfo.html",
                "use": "Public job-shop optimization instances, including the repository's FT06 baseline.",
                "license": "Check OR-Library legal notice before redistribution",
            },
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return csv_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "synthetic")
    args = parser.parse_args()
    csv_path, manifest_path = generate(args.rows, args.seed, args.output_dir)
    print(f"generated {csv_path} ({args.rows:,} rows)")
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
