from mdt.ai import load_bundle
from mdt.decision import build_recovery_decision


def test_ai_ie_or_decision_chain(ft06, root):
    bundle = load_bundle(root / "artifacts/ai/lateness_risk.joblib")
    result = build_recovery_decision(ft06, bundle, backend="scipy", due_factor=1.5)
    assert result["evidence_labels"]["risk"].startswith("PREDICTED")
    assert result["baseline"]["total_tardiness"] == 40.0
    assert result["optimized"]["total_tardiness"] <= result["baseline"]["total_tardiness"] + 1e-6
    assert result["optimized"]["solver"]["objective_value"] <= result["baseline"]["objective_value"] + 1e-6
    assert result["optimized"]["solver"]["status"] == "OPTIMAL"
    assert result["optimized"]["violations"] == []
    assert result["recommendation"]["action"] == "use optimized finite-capacity sequence"
