from pathlib import Path

from mdt.config import Settings


def test_default_sqlite_runtime_directory_is_bootstrapped(tmp_path, monkeypatch):
    monkeypatch.delenv("MDT_DATABASE_URL", raising=False)
    settings = Settings.from_env(tmp_path)
    assert (tmp_path / "runtime").is_dir()
    assert settings.database_url.endswith("/runtime/mdt.db")


def test_repository_env_file_loads_local_gemini_key_without_overriding_process_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("GEMINI" + "_API_KEY=local-test-key\n", encoding="utf-8")
    settings = Settings.from_env(tmp_path)
    assert settings.gemini_api_key == "local-test-key"

    monkeypatch.setenv("GEMINI_API_KEY", "process-wins")
    settings2 = Settings.from_env(tmp_path)
    assert settings2.gemini_api_key == "process-wins"
