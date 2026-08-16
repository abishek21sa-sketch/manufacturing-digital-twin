from pathlib import Path


def test_workspace_is_zero_build_and_has_no_external_frontend_dependency(root: Path):
    html = (root / "workspace/index.html").read_text(encoding="utf-8")
    methodology = (root / "workspace/methodology.html").read_text(encoding="utf-8")
    js = (root / "workspace/app.js").read_text(encoding="utf-8")
    method_js = (root / "workspace/methodology.js").read_text(encoding="utf-8")
    assert 'id="timeline"' in html
    assert "Stress-test four policies" in html
    assert "HUMAN DECISION GATE" in html
    assert 'href="/methodology"' in html
    assert "/v1/decision/stress-test" in js
    assert "/v1/copilot/run-scenario" in js
    assert "/v1/decisions/" in js
    assert "Engineering Methodology" in methodology
    assert "SCENARIO-BASED CVaR POLICY MILP" in methodology
    assert "/v1/methodology/evidence" in method_js
    for content in (html, methodology, js, method_js):
        assert "https://" not in content
        assert "http://" not in content
