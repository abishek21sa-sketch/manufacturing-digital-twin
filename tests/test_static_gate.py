from __future__ import annotations

from pathlib import Path

from scripts.static_gate import scan_root


def _minimal_repo(tmp_path: Path) -> Path:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "pkg" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".venv/\n.env\nruntime/*.db\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("GEMINI" + "_API_KEY=\n", encoding="utf-8")
    return tmp_path


def test_local_env_is_allowed_and_never_read_as_source(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    # Deliberately looks like a real credential assignment. Local acceptance requires this file.
    (root / ".env").write_text("GEMINI" + "_API_KEY=super-secret-local-value\n", encoding="utf-8")
    assert scan_root(root) == []


def test_embedded_secret_assignment_in_source_fails(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    (root / "src" / "pkg" / "bad.txt").write_text("GEMINI" + "_API_KEY=accidentally-committed\n", encoding="utf-8")
    failures = scan_root(root)
    assert any("possible embedded secret/config token" in item for item in failures)


def test_missing_env_gitignore_rule_fails(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    (root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    failures = scan_root(root)
    assert any(".gitignore must contain an explicit .env rule" in item for item in failures)
