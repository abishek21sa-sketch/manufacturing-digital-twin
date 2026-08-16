from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    benchmark_instance: str
    project_root: Path
    gemini_model: str = "gemini-3.5-flash"
    copilot_enabled: bool = True
    gemini_api_key: str | None = None

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "Settings":
        root = (project_root or Path.cwd()).resolve()
        # Local Windows releases use a repository-local .env. Environment
        # variables already present in the process always win.
        load_dotenv(root / ".env", override=False)
        raw_url = os.getenv("MDT_DATABASE_URL", "sqlite:///runtime/mdt.db")
        if raw_url.startswith("sqlite:///runtime/"):
            db_name = raw_url.removeprefix("sqlite:///runtime/")
            runtime_dir = root / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            raw_url = f"sqlite:///{(runtime_dir / db_name).as_posix()}"
        key = os.getenv("GEMINI_API_KEY") or None
        return cls(
            database_url=raw_url,
            benchmark_instance=os.getenv("MDT_BENCHMARK_INSTANCE", "ft06"),
            project_root=root,
            gemini_model=os.getenv("MDT_GEMINI_MODEL", "gemini-3.5-flash"),
            copilot_enabled=_env_bool("MDT_COPILOT_ENABLED", True),
            gemini_api_key=key,
        )
