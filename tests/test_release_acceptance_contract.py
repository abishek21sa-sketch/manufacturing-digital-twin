from pathlib import Path


def test_release_check_fails_fast_before_long_isolated_suite(root: Path):
    text = (root / "scripts/release_check.py").read_text(encoding="utf-8")
    public_idx = text.index('scripts/public_release_check.py')
    runtime_idx = text.index('scripts/runtime_smoke.py')
    suite_idx = text.index('scripts/test_suite_isolated.py')
    assert public_idx < suite_idx
    assert runtime_idx < suite_idx


def test_runtime_smoke_uses_auto_backend_and_composite_request_budgets(root: Path):
    text = (root / "scripts/runtime_smoke.py").read_text(encoding="utf-8")
    assert 'SMOKE_SOLVER_BACKEND = "auto"' in text
    assert 'DECISION_HTTP_TIMEOUT_SECONDS' in text
    assert 'STRESS_HTTP_TIMEOUT_SECONDS' in text
    assert 'trust_env=False' in text
    # The final runtime smoke must not force the slower HiGHS implementation on
    # the licensed Windows target; dedicated oracle tests still exercise SciPy.
    assert '"backend": "scipy"' not in text


def test_final_windows_acceptance_runs_external_preflight_before_long_release_suite(root: Path):
    text = (root / "accept_v1_windows.bat").read_text(encoding="utf-8").lower()
    release_idx = text.index("scripts\\release_check.py")
    assert text.index("scripts\\public_release_check.py") < release_idx
    assert text.index("scripts\\windows_preflight.py") < release_idx
    assert text.index("scripts\\gemini_acceptance.py") < release_idx
    assert text.index("scripts\\gurobi_acceptance.py") < release_idx
    assert text.index("scripts\\windows_v1_acceptance.py") < release_idx
    assert text.index("scripts\\launch_workspace.py") < release_idx


def test_final_diagnostics_do_not_mutate_frozen_release_evidence_by_default(root: Path):
    diagnostics = (root / "scripts" / "v1_diagnostics.py").read_text(encoding="utf-8")
    release = (root / "scripts" / "release_check.py").read_text(encoding="utf-8")
    assert '"--write-evidence"' in diagnostics
    assert "if args.write_evidence" in diagnostics
    assert '"scripts/v1_diagnostics.py"' in release
    assert "--write-evidence" not in release
