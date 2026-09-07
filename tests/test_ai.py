from pathlib import Path

import numpy as np

from mdt.ai import generate_lateness_dataset, load_bundle, score_planning_jobs
from mdt.optimization import default_planning_jobs


def test_synthetic_dataset_is_seed_reproducible(ft06):
    a = generate_lateness_dataset(ft06, n_scenarios=30, seed=123)
    b = generate_lateness_dataset(ft06, n_scenarios=30, seed=123)
    for left, right in zip(a, b):
        assert np.array_equal(left, right)
    assert 0 < a[1].mean() < 1


def test_packaged_ai_artifact_and_probability_contract(ft06, root):
    bundle = load_bundle(root / "artifacts/ai/lateness_risk.joblib")
    jobs = score_planning_jobs(bundle, ft06, default_planning_jobs(ft06, 1.5))
    assert len(jobs) == 6
    assert all(0.0 <= j.risk_score <= 1.0 for j in jobs)
    assert max(j.risk_score for j in jobs) > min(j.risk_score for j in jobs)


def test_ai_validation_beats_naive_baseline(root):
    import json
    report = json.loads((root / "docs/evidence/AI_VALIDATION.json").read_text(encoding='utf-8'))
    prod = report["production_model"]
    naive = report["class_prior_baseline"]
    challenger = report["nonlinear_challenger"]
    assert report["evidence_label"] == "SYNTHETIC VALIDATION"
    assert prod["roc_auc"] > 0.90
    assert prod["pr_auc"] > 0.80
    assert prod["brier"] < naive["brier"]
    assert prod["brier"] < challenger["brier"]
