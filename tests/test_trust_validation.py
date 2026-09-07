from mdt.trust_validation import canonical_experiments, sensitivity_grid, validation_report


def test_canonical_trust_experiments_pass():
    rows = canonical_experiments()
    assert rows and all(row["passed"] for row in rows)


def test_sensitivity_grid_covers_all_decision_classes():
    rows = sensitivity_grid()
    decisions = {row["decision"] for row in rows}
    assert len(rows) >= 80
    assert {"AUTHORIZED", "HUMAN_REVIEW", "BLOCKED"}.issubset(decisions)


def test_validation_report_is_bounded():
    report = validation_report()
    assert report["canonical_passed"] == report["canonical_total"]
    assert "no claim" in report["evidence_boundary"].lower()
