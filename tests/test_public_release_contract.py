import json
from pathlib import Path


def test_machine_readable_constitution_traceability_is_fully_resolved(root: Path):
    trace = json.loads((root / "docs/CONSTITUTION_TRACEABILITY.json").read_text(encoding="utf-8"))
    assert trace["release"] == "V1.0" and trace["version"] == "1.0.0"
    assert trace["unresolved"] == []
    assert len(trace["requirements"]) >= 60
    allowed = set(trace["allowed_statuses"])
    assert all(row["status"] in allowed for row in trace["requirements"])


def test_only_final_public_acceptance_path_remains(root: Path):
    assert (root / "accept_v1_windows.bat").exists()
    for name in ("accept_constitution_closure_windows.bat", "retest_constitution_pareto_windows.bat", "retest_solver_contract_windows.bat", "retest_workspace_launch_windows.bat"):
        assert not (root / name).exists()
    quality = (root / "docs/QUALITY_GATE.md").read_text(encoding="utf-8")
    assert "25 / 25 resolved for V1.0" in quality


def test_v1_includes_public_methodology_page_and_document(root: Path):
    assert (root / "workspace/methodology.html").exists()
    assert (root / "workspace/methodology.js").exists()
    assert (root / "docs/METHODOLOGY.md").exists()
    html = (root / "workspace/methodology.html").read_text(encoding="utf-8")
    assert "LITTLE'S LAW" in html
    assert "SCENARIO-BASED CVaR POLICY MILP" in html
