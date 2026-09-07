from types import SimpleNamespace

from mdt.trust import TrustDecision, assess_trust


def _fixture(root):
    class M:
        machine_id = "M1"
    class O:
        operation_id = "O1"
    class J:
        job_id = "J1"
        operations = (O(),)
    factory = SimpleNamespace(machines=(M(),), jobs=(J(),))
    snapshot = SimpleNamespace(machines={"M1": 1}, jobs={"J1": 1}, operations={"O1": 1}, event_count=2, timestamp=100.0)
    return factory, snapshot


def test_authorizes_fresh_consistent_state(root):
    factory, snapshot = _fixture(root)
    result = assess_trust(snapshot=snapshot, factory_model=factory, ledger_events=[1, 2], model_evidence={"a": True, "b": True, "c": True, "d": True}, reference_time=100.0)
    assert result.decision == TrustDecision.AUTHORIZED
    assert abs(result.score - 1.0) < 1e-12


def test_aging_state_can_require_human_review(root):
    factory, snapshot = _fixture(root)
    result = assess_trust(snapshot=snapshot, factory_model=factory, ledger_events=[1, 2], model_evidence={"a": True, "b": True, "c": True, "d": True}, reference_time=150.0)
    assert result.decision == TrustDecision.HUMAN_REVIEW
    assert result.signals.freshness < 0.2


def test_ledger_mismatch_is_hard_block(root):
    factory, snapshot = _fixture(root)
    result = assess_trust(snapshot=snapshot, factory_model=factory, ledger_events=[1], model_evidence={"a": True, "b": True, "c": True, "d": True})
    assert result.decision == TrustDecision.BLOCKED
    assert "EVENT_LEDGER_MISMATCH" in result.signals.hard_stop_reasons


def test_insufficient_model_evidence_is_hard_block(root):
    factory, snapshot = _fixture(root)
    result = assess_trust(snapshot=snapshot, factory_model=factory, ledger_events=[1, 2], model_evidence={"a": True, "b": False, "c": False, "d": True})
    assert result.decision == TrustDecision.BLOCKED
    assert "MODEL_EVIDENCE_INSUFFICIENT" in result.signals.hard_stop_reasons
