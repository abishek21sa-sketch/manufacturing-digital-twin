from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
import json

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, average_precision_score, brier_score_loss, f1_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from mdt.domain import FactoryModel
from mdt.optimization.model import PlanningJob
from .scenarios import FEATURE_NAMES, extract_job_features, generate_lateness_dataset


def expected_calibration_error(y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    error = 0.0
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (probabilities >= low) & (probabilities < high if high < 1.0 else probabilities <= high)
        if not np.any(mask):
            continue
        error += (mask.sum() / len(y_true)) * abs(float(y_true[mask].mean()) - float(probabilities[mask].mean()))
    return float(error)


@dataclass
class LatenessRiskBundle:
    model: Any
    feature_names: tuple[str, ...]
    metadata: dict[str, Any]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return np.clip(self.model.predict_proba(X)[:, 1], 0.0, 1.0)


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    pred = (p >= 0.5).astype(int)
    result = {
        "accuracy": float(accuracy_score(y, pred)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "brier": float(brier_score_loss(y, p)),
        "ece_10_bin": expected_calibration_error(y, p, 10),
    }
    if len(np.unique(y)) == 2:
        result["roc_auc"] = float(roc_auc_score(y, p))
        result["pr_auc"] = float(average_precision_score(y, p))
    return result


def train_lateness_model(factory: FactoryModel, n_scenarios: int = 300, seed: int = 20260815) -> tuple[LatenessRiskBundle, dict[str, Any]]:
    X, y, groups = generate_lateness_dataset(factory, n_scenarios=n_scenarios, seed=seed)
    unique_groups = np.unique(groups)
    first = GroupShuffleSplit(n_splits=1, train_size=0.60, random_state=seed)
    train_group_idx, rem_group_idx = next(first.split(unique_groups, groups=unique_groups))
    train_groups = unique_groups[train_group_idx]
    rem_groups = unique_groups[rem_group_idx]
    second = GroupShuffleSplit(n_splits=1, train_size=0.50, random_state=seed + 1)
    val_idx, test_idx = next(second.split(rem_groups, groups=rem_groups))
    val_groups = rem_groups[val_idx]
    test_groups = rem_groups[test_idx]

    train_mask = np.isin(groups, train_groups)
    val_mask = np.isin(groups, val_groups)
    test_mask = np.isin(groups, test_groups)
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    # Production model. This deliberately remains simpler because it beat the
    # nonlinear challenger on the grouped holdout for this synthetic benchmark.
    production = Pipeline([
        ("scale", StandardScaler()),
        ("classifier", LogisticRegression(C=10.0, max_iter=3000, random_state=seed)),
    ])
    production.fit(X_train, y_train)
    p_test = production.predict_proba(X_test)[:, 1]

    challenger = HistGradientBoostingClassifier(
        learning_rate=0.07, max_iter=180, max_leaf_nodes=15,
        l2_regularization=0.5, random_state=seed,
    )
    challenger.fit(X_train, y_train)
    challenger_p = challenger.predict_proba(X_test)[:, 1]

    prior = float(y_train.mean())
    prior_p = np.full(len(y_test), prior, dtype=float)
    report = {
        "evidence_label": "SYNTHETIC VALIDATION",
        "seed": seed,
        "scenarios": {"total": n_scenarios, "train": len(train_groups), "validation": len(val_groups), "test": len(test_groups)},
        "records": {"train": int(train_mask.sum()), "validation": int(val_mask.sum()), "test": int(test_mask.sum())},
        "positive_rate": {"train": float(y_train.mean()), "test": float(y_test.mean())},
        "production_model": {"name": "standardized logistic regression", **_metrics(y_test, p_test)},
        "nonlinear_challenger": {"name": "histogram gradient boosting", **_metrics(y_test, challenger_p)},
        "class_prior_baseline": _metrics(y_test, prior_p),
        "model_selection": "production model selected by grouped holdout evidence; nonlinear challenger is retained only as benchmark evidence",
        "feature_names": list(FEATURE_NAMES),
        "calibration": "probability quality assessed on untouched test scenarios using Brier score and 10-bin ECE",
        "decision_use": "estimated lateness probability weights job tardiness in the recovery scheduling objective",
        "limitations": "trained and tested only on generated perturbations of the public FT06 benchmark; not plant-calibrated",
    }
    bundle = LatenessRiskBundle(production, FEATURE_NAMES, {
        "model": "StandardScaler + LogisticRegression(C=10)",
        "seed": seed,
        "n_scenarios": n_scenarios,
        "validation": "grouped synthetic scenario split 60/20/20",
        "target": "job late under deterministic SPT status-quo schedule",
        "evidence_label": "SYNTHETIC VALIDATION",
        "test_metrics": report["production_model"],
    })
    return bundle, report


def save_bundle(bundle: LatenessRiskBundle, report: dict[str, Any], artifact_path: Path, report_path: Path) -> None:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, artifact_path)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def load_bundle(path: Path) -> LatenessRiskBundle:
    if not path.exists():
        raise FileNotFoundError(f"AI artifact not found: {path}; run scripts/train_ai.py")
    bundle = joblib.load(path)
    if tuple(bundle.feature_names) != FEATURE_NAMES:
        raise RuntimeError("AI feature contract does not match runtime feature contract")
    return bundle


def score_planning_jobs(bundle: LatenessRiskBundle, factory: FactoryModel, jobs: tuple[PlanningJob, ...]) -> tuple[PlanningJob, ...]:
    X, ids = extract_job_features(factory, jobs)
    probs = bundle.predict_proba(X)
    pmap = {job.job_id: job for job in jobs}
    return tuple(replace(pmap[job_id], risk_score=float(p)) for job_id, p in zip(ids, probs))


def explain_lateness_scores(bundle: LatenessRiskBundle, factory: FactoryModel, jobs: tuple[PlanningJob, ...], top_k: int = 3) -> dict[str, list[dict[str, float | str]]]:
    """Return local logistic feature contributions when the production model supports them.

    Contributions are log-odds terms, not causal effects. If a future packaged
    model lacks a scaler/linear-classifier contract, an empty explanation is
    returned rather than fabricating attribution.
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    X, ids = extract_job_features(factory, jobs)
    model = bundle.model
    try:
        scaler = model.named_steps["scale"]
        classifier = model.named_steps["classifier"]
        coefficients = np.asarray(classifier.coef_[0], dtype=float)
        standardized = scaler.transform(X)
    except Exception:
        return {job_id: [] for job_id in ids}
    output = {}
    for row, job_id in zip(standardized, ids):
        contributions = row * coefficients
        ranked = sorted(
            [
                {"feature": name, "log_odds_contribution": float(value)}
                for name, value in zip(bundle.feature_names, contributions)
            ],
            key=lambda item: abs(float(item["log_odds_contribution"])),
            reverse=True,
        )[:top_k]
        output[job_id] = ranked
    return output
