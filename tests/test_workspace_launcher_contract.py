from pathlib import Path


def test_run_windows_is_decoupled_from_final_public_release_gate(root: Path):
    text = (root / "run_windows.bat").read_text(encoding="utf-8")
    assert "public_release_check.py" not in text
    assert "launch_workspace.py" in text


def test_launcher_waits_for_health_before_browser(root: Path):
    text = (root / "scripts" / "launch_workspace.py").read_text(encoding="utf-8")
    readiness = text.index("_wait_until_ready")
    browser = text.index("webbrowser.open", readiness)
    assert readiness < browser
    assert 'httpx.get(f"{BASE_URL}/health"' in text
    assert 'httpx.get(WORKSPACE_URL' in text
    assert 'httpx.get(METHODOLOGY_URL' in text


def test_v1_version_labels_are_synchronized(root: Path):
    from mdt import __version__

    assert __version__ == "1.0.0"
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert 'version = "1.0.0"' in pyproject
    assert "1.0.0" in readme and "V1.0" in readme
