from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, IsolationForest
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import average_precision_score, mean_absolute_error, mean_squared_error, r2_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from mdt.domain import FactoryModel, MachineStatus, OperationStatus, TwinSnapshot
from mdt.ie import availability, dynamic_bottleneck
from mdt.optimization import PlanningJob, ScheduleProblem
from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, simulate
from .scenarios import extract_job_features, heuristic_dispatch, perturb_factory


@dataclass
class CycleTimeBundle:
    model: Any
    feature_names: tuple[str, ...]
    metadata: dict[str, Any]

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.maximum(0.0, np.asarray(self.model.predict(X), dtype=float))


BOTTLENECK_FEATURE_NAMES = (
    "nominal_load_share",
    "operation_count_share",
    "mean_operation_time",
    "availability",
    "processing_cv",
    "static_constraint_indicator",
)


@dataclass
class BottleneckBundle:
    model: Any
    feature_names: tuple[str, ...]
    metadata: dict[str, Any]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.clip(np.asarray(self.model.predict_proba(X)[:, 1], dtype=float), 0.0, 1.0)


ANOMALY_FEATURE_NAMES = (
    "completed_ratio",
    "mean_cycle_ratio",
    "downtime_fraction",
    "ready_queue_fraction",
    "busy_indicator",
    "load_share",
)


@dataclass
class AnomalyBundle:
    model: Any
    feature_names: tuple[str, ...]
    threshold_raw: float
    score_low: float
    score_high: float
    metadata: dict[str, Any]

    def raw_score(self, X: np.ndarray) -> np.ndarray:
        # IsolationForest score_samples is larger for normal observations.
        return -np.asarray(self.model.score_samples(X), dtype=float)

    def anomaly_index(self, X: np.ndarray) -> np.ndarray:
        raw = self.raw_score(X)
        span = max(1e-9, self.score_high - self.score_low)
        return np.clip((raw - self.score_low) / span, 0.0, 1.0)

    def is_anomaly(self, X: np.ndarray) -> np.ndarray:
        return self.raw_score(X) >= self.threshold_raw


def _group_split(groups: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    unique = np.unique(groups)
    first = GroupShuffleSplit(n_splits=1, train_size=0.60, random_state=seed)
    train_idx, rem_idx = next(first.split(unique, groups=unique))
    train_groups = unique[train_idx]
    rem = unique[rem_idx]
    second = GroupShuffleSplit(n_splits=1, train_size=0.50, random_state=seed + 1)
    val_idx, test_idx = next(second.split(rem, groups=rem))
    return train_groups, rem[val_idx], rem[test_idx]


def generate_cycle_time_dataset(factory: FactoryModel, n_scenarios: int = 240, seed: int = 20260815) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if n_scenarios < 30:
        raise ValueError("at least 30 scenarios are required")
    rng = np.random.default_rng(seed)
    rows: list[np.ndarray] = []
    targets: list[float] = []
    groups: list[int] = []
    for scenario_id in range(n_scenarios):
        scenario = perturb_factory(factory, rng)
        planning = []
        for job in scenario.jobs:
            release = float(rng.uniform(0.0, 18.0))
            total = sum(op.processing_time for op in job.operations)
            factor = float(rng.uniform(1.0, 3.0))
            planning.append(PlanningJob(job.job_id, release, release + factor * total))
        planning_tuple = tuple(planning)
        problem = ScheduleProblem(scenario, planning_tuple)
        baseline = heuristic_dispatch(problem, "SPT")
        X, ids = extract_job_features(scenario, planning_tuple)
        pmap = {j.job_id: j for j in planning_tuple}
        for row, job_id in zip(X, ids):
            rows.append(row)
            targets.append(float(baseline.completion[job_id] - pmap[job_id].release_time))
            groups.append(scenario_id)
    return np.vstack(rows), np.asarray(targets, dtype=float), np.asarray(groups, dtype=int)


def train_cycle_time_model(factory: FactoryModel, n_scenarios: int = 240, seed: int = 20260815) -> tuple[CycleTimeBundle, dict[str, Any]]:
    from .scenarios import FEATURE_NAMES

    X, y, groups = generate_cycle_time_dataset(factory, n_scenarios, seed)
    train_groups, val_groups, test_groups = _group_split(groups, seed)
    train = np.isin(groups, train_groups)
    test = np.isin(groups, test_groups)
    X_train, y_train = X[train], y[train]
    X_test, y_test = X[test], y[test]

    ridge = Pipeline([("scale", StandardScaler()), ("regressor", Ridge(alpha=1.0))])
    ridge.fit(X_train, y_train)
    p_ridge = ridge.predict(X_test)
    # Naive engineering baseline: assume flow time equals pure touch/work time,
    # thereby ignoring queueing and resource contention.
    p_naive = X_test[:, 2]

    challenger = HistGradientBoostingRegressor(max_iter=220, learning_rate=0.06, max_leaf_nodes=15, l2_regularization=0.5, random_state=seed)
    challenger.fit(X_train, y_train)
    p_challenger = challenger.predict(X_test)

    def metrics(pred: np.ndarray) -> dict[str, float]:
        return {
            "mae": float(mean_absolute_error(y_test, pred)),
            "rmse": float(mean_squared_error(y_test, pred) ** 0.5),
            "r2": float(r2_score(y_test, pred)),
        }

    naive_metrics = metrics(p_naive)
    ridge_metrics = metrics(p_ridge)
    challenger_metrics = metrics(p_challenger)
    if challenger_metrics["mae"] < ridge_metrics["mae"]:
        selected, selected_name, selected_metrics = challenger, "histogram gradient boosting regressor", challenger_metrics
    else:
        selected, selected_name, selected_metrics = ridge, "standardized ridge regression", ridge_metrics

    report = {
        "evidence_label": "SYNTHETIC VALIDATION",
        "task": "job cycle-time / remaining flow-time regression under generated benchmark scenarios",
        "seed": seed,
        "scenarios": {"total": n_scenarios, "train": len(train_groups), "validation": len(val_groups), "test": len(test_groups)},
        "production_model": {"name": selected_name, **selected_metrics},
        "touch_time_baseline": {"name": "total remaining work as flow-time estimate", **naive_metrics},
        "ridge_candidate": {"name": "standardized ridge regression", **ridge_metrics},
        "gradient_boosting_challenger": {"name": "histogram gradient boosting regressor", **challenger_metrics},
        "feature_names": list(FEATURE_NAMES),
        "decision_use": "provides expected remaining-flow-time consequence and horizon guidance for synchronized-twin rescheduling",
        "limitations": "synthetic benchmark scenarios only; no plant-calibrated cycle-time distribution",
    }
    bundle = CycleTimeBundle(selected, FEATURE_NAMES, {"model": selected_name, "seed": seed, "test_metrics": selected_metrics, "evidence_label": "SYNTHETIC VALIDATION"})
    return bundle, report


def _machine_feature_rows(factory: FactoryModel, config: SimulationConfig) -> tuple[np.ndarray, list[str]]:
    loads = {m.machine_id: 0.0 for m in factory.machines}
    counts = {m.machine_id: 0 for m in factory.machines}
    durations = {m.machine_id: [] for m in factory.machines}
    for job in factory.jobs:
        for op in job.operations:
            loads[op.machine_id] += op.processing_time
            counts[op.machine_id] += 1
            durations[op.machine_id].append(op.processing_time)
    total_load = max(1e-12, sum(loads.values()))
    total_count = max(1, sum(counts.values()))
    static_constraint = max(loads, key=loads.get)
    rows = []
    ids = []
    for machine in factory.machines:
        rel = config.reliability_for(machine.machine_id)
        a = 1.0 if rel.mtbf is None else availability(rel.mtbf, rel.mttr)
        rows.append([
            loads[machine.machine_id] / total_load,
            counts[machine.machine_id] / total_count,
            float(np.mean(durations[machine.machine_id])) if durations[machine.machine_id] else 0.0,
            a,
            config.processing_cv,
            1.0 if machine.machine_id == static_constraint else 0.0,
        ])
        ids.append(machine.machine_id)
    return np.asarray(rows, dtype=float), ids


def generate_bottleneck_dataset(factory: FactoryModel, n_scenarios: int = 120, seed: int = 20260815) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if n_scenarios < 30:
        raise ValueError("at least 30 scenarios are required")
    rng = np.random.default_rng(seed)
    X_rows: list[np.ndarray] = []
    y_rows: list[int] = []
    groups: list[int] = []
    baseline_positive: list[int] = []
    for scenario_id in range(n_scenarios):
        scenario = perturb_factory(factory, rng)
        planning = tuple(
            PlanningJob(job.job_id, 0.0, 3.0 * sum(op.processing_time for op in job.operations))
            for job in scenario.jobs
        )
        problem = ScheduleProblem(scenario, planning)
        processing_cv = float(rng.uniform(0.03, 0.25))
        base_mtbf = float(rng.uniform(70.0, 170.0))
        base_mttr = float(rng.uniform(3.0, 10.0))
        overrides = {}
        if rng.random() < 0.80:
            stressed = str(rng.choice([m.machine_id for m in scenario.machines]))
            overrides[stressed] = ReliabilitySpec(float(rng.uniform(15.0, 60.0)), float(rng.uniform(8.0, 20.0)))
        config = SimulationConfig(
            seed=seed + scenario_id,
            processing_cv=processing_cv,
            reliability=ReliabilitySpec(base_mtbf, base_mttr),
            machine_reliability=overrides,
            record_events=False,
        )
        result = simulate(problem, PolicySpec("SPT", "SPT"), config)
        horizon = max(result.metrics.makespan - problem.current_time, 1e-9)
        target_machine = dynamic_bottleneck(result.machine_productive_time, result.machine_downtime, horizon).machine_id
        X, ids = _machine_feature_rows(scenario, config)
        static_machine = max(
            ids,
            key=lambda mid: sum(op.processing_time for job in scenario.jobs for op in job.operations if op.machine_id == mid),
        )
        for row, machine_id in zip(X, ids):
            X_rows.append(row)
            y_rows.append(int(machine_id == target_machine))
            groups.append(scenario_id)
            baseline_positive.append(int(machine_id == static_machine))
    return np.vstack(X_rows), np.asarray(y_rows, dtype=int), np.asarray(groups, dtype=int), np.asarray(baseline_positive, dtype=int)


def _scenario_top1(groups: np.ndarray, y: np.ndarray, probabilities: np.ndarray) -> float:
    correct = 0
    unique = np.unique(groups)
    for group in unique:
        mask = groups == group
        true_idx = int(np.argmax(y[mask]))
        pred_idx = int(np.argmax(probabilities[mask]))
        correct += int(true_idx == pred_idx)
    return correct / len(unique)


def train_bottleneck_model(factory: FactoryModel, n_scenarios: int = 120, seed: int = 20260815) -> tuple[BottleneckBundle, dict[str, Any]]:
    X, y, groups, baseline = generate_bottleneck_dataset(factory, n_scenarios, seed)
    train_groups, val_groups, test_groups = _group_split(groups, seed)
    train = np.isin(groups, train_groups)
    test = np.isin(groups, test_groups)
    X_train, y_train = X[train], y[train]
    X_test, y_test, g_test = X[test], y[test], groups[test]

    linear = Pipeline([("scale", StandardScaler()), ("classifier", LogisticRegression(C=2.0, max_iter=2000, class_weight="balanced", random_state=seed))])
    linear.fit(X_train, y_train)
    p_linear = linear.predict_proba(X_test)[:, 1]
    nonlinear = HistGradientBoostingClassifier(max_iter=180, learning_rate=0.07, max_leaf_nodes=15, l2_regularization=0.5, random_state=seed)
    nonlinear.fit(X_train, y_train)
    p_nonlin = nonlinear.predict_proba(X_test)[:, 1]

    def metrics(p: np.ndarray) -> dict[str, float]:
        return {
            "top1_accuracy": float(_scenario_top1(g_test, y_test, p)),
            "roc_auc": float(roc_auc_score(y_test, p)),
            "pr_auc": float(average_precision_score(y_test, p)),
        }

    linear_metrics = metrics(p_linear)
    nonlinear_metrics = metrics(p_nonlin)
    baseline_test = baseline[test].astype(float)
    baseline_top1 = _scenario_top1(g_test, y_test, baseline_test)
    if nonlinear_metrics["top1_accuracy"] > linear_metrics["top1_accuracy"] or (
        nonlinear_metrics["top1_accuracy"] == linear_metrics["top1_accuracy"] and nonlinear_metrics["pr_auc"] > linear_metrics["pr_auc"]
    ):
        selected, selected_name, selected_metrics = nonlinear, "histogram gradient boosting classifier", nonlinear_metrics
    else:
        selected, selected_name, selected_metrics = linear, "standardized logistic classifier", linear_metrics

    report = {
        "evidence_label": "SYNTHETIC VALIDATION",
        "task": "predict the next dynamic machine bottleneck under processing/reliability uncertainty",
        "seed": seed,
        "scenarios": {"total": n_scenarios, "train": len(train_groups), "validation": len(val_groups), "test": len(test_groups)},
        "production_model": {"name": selected_name, **selected_metrics},
        "static_workload_baseline": {"top1_accuracy": float(baseline_top1)},
        "linear_candidate": {"name": "standardized logistic classifier", **linear_metrics},
        "nonlinear_candidate": {"name": "histogram gradient boosting classifier", **nonlinear_metrics},
        "feature_names": list(BOTTLENECK_FEATURE_NAMES),
        "target": "machine with maximum simulated productive-utilization + downtime pressure index",
        "decision_use": "selects the machine to stress by default during robust future-state evaluation when no operator override is supplied",
        "limitations": "target is derived from seeded benchmark simulation, not measured congestion in a real plant",
    }
    return BottleneckBundle(selected, BOTTLENECK_FEATURE_NAMES, {"model": selected_name, "seed": seed, "test_metrics": selected_metrics, "evidence_label": "SYNTHETIC VALIDATION"}), report


def train_anomaly_model(n_normal: int = 1200, n_anomaly: int = 360, seed: int = 20260815) -> tuple[AnomalyBundle, dict[str, Any]]:
    rng = np.random.default_rng(seed)
    normal = np.column_stack([
        rng.uniform(0.0, 1.0, n_normal),
        np.clip(rng.lognormal(mean=-0.5 * 0.10**2, sigma=0.10, size=n_normal), 0.65, 1.45),
        np.clip(rng.beta(1.5, 24.0, n_normal), 0.0, 0.35),
        np.clip(rng.beta(1.5, 8.0, n_normal), 0.0, 0.75),
        rng.binomial(1, 0.55, n_normal),
        np.clip(rng.normal(1 / 6, 0.035, n_normal), 0.05, 0.35),
    ])
    anomalies = normal[rng.integers(0, n_normal, n_anomaly)].copy()
    modes = rng.integers(0, 3, n_anomaly)
    for idx, mode in enumerate(modes):
        if mode == 0:
            anomalies[idx, 1] = rng.uniform(1.8, 3.5)  # cycle-time excursion
        elif mode == 1:
            anomalies[idx, 2] = rng.uniform(0.45, 0.90)  # excessive downtime
        else:
            anomalies[idx, 3] = rng.uniform(0.82, 1.0)  # severe queue pressure

    train = normal[: int(0.70 * n_normal)]
    test_normal = normal[int(0.70 * n_normal):]
    X_test = np.vstack([test_normal, anomalies])
    y_test = np.concatenate([np.zeros(len(test_normal), dtype=int), np.ones(len(anomalies), dtype=int)])

    model = IsolationForest(n_estimators=240, contamination=0.025, random_state=seed)
    model.fit(train)
    raw_train = -model.score_samples(train)
    raw_test = -model.score_samples(X_test)
    threshold = float(np.quantile(raw_train, 0.975))
    # Simple operations-rule baseline: a single obvious limit breach. This is
    # intentionally much simpler than the multivariate detector and reflects
    # the kind of threshold logic it is meant to improve upon.
    baseline_flag = (X_test[:, 2] > 0.30).astype(float)
    report = {
        "evidence_label": "SYNTHETIC VALIDATION",
        "task": "unsupervised machine-state anomaly detection with injected synthetic anomalies used only for evaluation",
        "training": {"normal_records": len(train), "contamination_assumption": 0.025},
        "test": {"normal_records": len(test_normal), "injected_anomaly_records": len(anomalies)},
        "production_model": {
            "name": "Isolation Forest",
            "roc_auc": float(roc_auc_score(y_test, raw_test)),
            "pr_auc": float(average_precision_score(y_test, raw_test)),
        },
        "downtime_threshold_baseline": {
            "roc_auc": float(roc_auc_score(y_test, baseline_flag)),
            "pr_auc": float(average_precision_score(y_test, baseline_flag)),
        },
        "feature_names": list(ANOMALY_FEATURE_NAMES),
        "decision_use": "anomalous synchronized-twin machine states force human review and are prioritized for future-state stress testing",
        "limitations": "unsupervised model trained on generated normal envelopes; anomaly index is not a probability",
    }
    bundle = AnomalyBundle(
        model,
        ANOMALY_FEATURE_NAMES,
        threshold,
        float(np.quantile(raw_train, 0.01)),
        float(max(np.quantile(raw_test, 0.995), threshold + 1e-6)),
        {"model": "Isolation Forest", "seed": seed, "evidence_label": "SYNTHETIC VALIDATION", "threshold_quantile": 0.975},
    )
    return bundle, report


def score_cycle_time(bundle: CycleTimeBundle, factory: FactoryModel, jobs: tuple[PlanningJob, ...]) -> dict[str, float]:
    X, ids = extract_job_features(factory, jobs)
    prediction = bundle.predict(X)
    return {job_id: float(value) for job_id, value in zip(ids, prediction)}


def score_bottleneck(bundle: BottleneckBundle, factory: FactoryModel, config: SimulationConfig) -> dict[str, float]:
    X, ids = _machine_feature_rows(factory, config)
    probabilities = bundle.predict_proba(X)
    total = float(probabilities.sum())
    if total > 1e-12:
        probabilities = probabilities / total
    return {machine_id: float(value) for machine_id, value in zip(ids, probabilities)}


def snapshot_anomaly_features(factory: FactoryModel, snapshot: TwinSnapshot) -> tuple[np.ndarray, list[str]]:
    total_ops_by_machine = {m.machine_id: 0 for m in factory.machines}
    completed_by_machine = {m.machine_id: 0 for m in factory.machines}
    cycle_ratios = {m.machine_id: [] for m in factory.machines}
    loads = {m.machine_id: 0.0 for m in factory.machines}
    ready_counts = {m.machine_id: 0 for m in factory.machines}
    for job in factory.jobs:
        for op in job.operations:
            total_ops_by_machine[op.machine_id] += 1
            loads[op.machine_id] += op.processing_time
            runtime = snapshot.operations[op.operation_id]
            if runtime.status == OperationStatus.COMPLETE and runtime.started_at is not None and runtime.completed_at is not None:
                completed_by_machine[op.machine_id] += 1
                elapsed = max(0.0, runtime.completed_at - runtime.started_at)
                cycle_ratios[op.machine_id].append(elapsed / op.processing_time if op.processing_time > 0 else 1.0)
            elif runtime.status == OperationStatus.READY:
                ready_counts[op.machine_id] += 1
    total_load = max(1e-12, sum(loads.values()))
    rows = []
    ids = []
    for machine in factory.machines:
        mid = machine.machine_id
        runtime = snapshot.machines[mid]
        completed_ratio = completed_by_machine[mid] / max(1, total_ops_by_machine[mid])
        mean_cycle_ratio = float(np.mean(cycle_ratios[mid])) if cycle_ratios[mid] else 1.0
        downtime_fraction = runtime.accumulated_downtime / max(snapshot.timestamp, 1.0)
        ready_fraction = ready_counts[mid] / max(1, len(factory.jobs))
        busy = 1.0 if runtime.status == MachineStatus.BUSY else 0.0
        rows.append([completed_ratio, mean_cycle_ratio, downtime_fraction, ready_fraction, busy, loads[mid] / total_load])
        ids.append(mid)
    return np.asarray(rows, dtype=float), ids


def score_snapshot_anomalies(bundle: AnomalyBundle, factory: FactoryModel, snapshot: TwinSnapshot) -> dict[str, dict[str, float | bool]]:
    X, ids = snapshot_anomaly_features(factory, snapshot)
    index = bundle.anomaly_index(X)
    flags = bundle.is_anomaly(X)
    raw = bundle.raw_score(X)
    return {
        machine_id: {"anomaly_index": float(score), "raw_score": float(raw_score), "is_anomaly": bool(flag)}
        for machine_id, score, raw_score, flag in zip(ids, index, raw, flags)
    }


def save_operational_ai(
    cycle: CycleTimeBundle,
    cycle_report: dict[str, Any],
    bottleneck: BottleneckBundle,
    bottleneck_report: dict[str, Any],
    anomaly: AnomalyBundle,
    anomaly_report: dict[str, Any],
    artifact_dir: Path,
    report_path: Path,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(cycle, artifact_dir / "cycle_time.joblib")
    joblib.dump(bottleneck, artifact_dir / "bottleneck.joblib")
    joblib.dump(anomaly, artifact_dir / "anomaly.joblib")
    report_path.write_text(json.dumps({"cycle_time": cycle_report, "bottleneck": bottleneck_report, "anomaly": anomaly_report}, indent=2), encoding="utf-8")


def load_cycle_time(path: Path) -> CycleTimeBundle:
    bundle = joblib.load(path)
    return bundle


def load_bottleneck(path: Path) -> BottleneckBundle:
    bundle = joblib.load(path)
    return bundle


def load_anomaly(path: Path) -> AnomalyBundle:
    bundle = joblib.load(path)
    return bundle
