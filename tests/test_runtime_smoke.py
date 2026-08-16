from __future__ import annotations

from pathlib import Path

import pytest

import scripts.runtime_smoke as runtime_smoke


def test_windows_cleanup_retries_transient_permission_error(tmp_path, monkeypatch):
    target = tmp_path / "locked"
    target.mkdir()
    (target / "smoke.db").write_text("x", encoding="utf-8")
    original_rmtree = runtime_smoke.shutil.rmtree
    attempts = {"count": 0}

    def transient_lock(path):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError(32, "file is being used by another process")
        return original_rmtree(path)

    monkeypatch.setattr(runtime_smoke.shutil, "rmtree", transient_lock)
    monkeypatch.setattr(runtime_smoke.time, "sleep", lambda _: None)
    runtime_smoke.remove_tree_with_retry(target, attempts=4, delay_seconds=0)
    assert attempts["count"] == 3
    assert not target.exists()


def test_windows_cleanup_fails_on_persistent_lock(tmp_path, monkeypatch):
    target = tmp_path / "locked"
    target.mkdir()

    def persistent_lock(path):
        raise PermissionError(32, "file is being used by another process")

    monkeypatch.setattr(runtime_smoke.shutil, "rmtree", persistent_lock)
    monkeypatch.setattr(runtime_smoke.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="Windows-safe cleanup failed"):
        runtime_smoke.remove_tree_with_retry(target, attempts=2, delay_seconds=0)
