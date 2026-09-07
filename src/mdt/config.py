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


def _env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str
    benchmark_instance: str
    project_root: Path
    gemini_model: str = "gemini-3.5-flash"
    copilot_enabled: bool = True
    gemini_api_key: str | None = None
    environment: str = "development"
    instance_id: str = "mdt-local"
    auth_mode: str = "disabled"
    operator_api_key: str | None = None
    readonly_api_key: str | None = None
    admin_api_key: str | None = None
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver", "test")
    cors_origins: tuple[str, ...] = ()
    event_contract_version: str = "1.0.0"
    schema_revision: str = "mdt-rc4-hardening"
    observability_enabled: bool = True
    auto_create_schema: bool = True

    def validate_operational(self) -> None:
        if self.environment not in {"development", "test", "staging", "production"}:
            raise ValueError("MDT_ENV must be development, test, staging, or production")
        if self.auth_mode not in {"disabled", "api_key"}:
            raise ValueError("MDT_AUTH_MODE must be disabled or api_key")
        if self.auth_mode == "api_key" and not any((self.operator_api_key, self.readonly_api_key, self.admin_api_key)):
            raise ValueError("MDT_AUTH_MODE=api_key requires MDT_API_KEY, MDT_READONLY_API_KEY, or MDT_ADMIN_API_KEY")
        if self.environment == "production":
            if self.auth_mode != "api_key":
                raise ValueError("production requires MDT_AUTH_MODE=api_key")
            if self.database_url.startswith("sqlite:"):
                raise ValueError("production requires a server database URL; SQLite is local-only")
            if not self.admin_api_key:
                raise ValueError("production requires MDT_ADMIN_API_KEY for controlled administration")
            if "*" in self.allowed_hosts:
                raise ValueError("production cannot use wildcard MDT_ALLOWED_HOSTS")
            if self.auto_create_schema:
                raise ValueError("production requires MDT_AUTO_CREATE_SCHEMA=false; apply reviewed migrations explicitly")

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
        operator_key = os.getenv("MDT_API_KEY") or os.getenv("MDT_OPERATOR_API_KEY") or None
        environment = os.getenv("MDT_ENV", "development").strip().lower()
        settings = cls(
            database_url=raw_url,
            benchmark_instance=os.getenv("MDT_BENCHMARK_INSTANCE", "ft06"),
            project_root=root,
            gemini_model=os.getenv("MDT_GEMINI_MODEL", "gemini-3.5-flash"),
            copilot_enabled=_env_bool("MDT_COPILOT_ENABLED", True),
            gemini_api_key=key,
            environment=environment,
            instance_id=os.getenv("MDT_INSTANCE_ID", "mdt-local"),
            auth_mode=os.getenv("MDT_AUTH_MODE", "disabled").strip().lower(),
            operator_api_key=operator_key,
            readonly_api_key=os.getenv("MDT_READONLY_API_KEY") or None,
            admin_api_key=os.getenv("MDT_ADMIN_API_KEY") or None,
            allowed_hosts=_env_list("MDT_ALLOWED_HOSTS", ("127.0.0.1", "localhost", "testserver", "test")),
            cors_origins=_env_list("MDT_CORS_ORIGINS"),
            event_contract_version=os.getenv("MDT_EVENT_CONTRACT_VERSION", "1.0.0"),
            schema_revision=os.getenv("MDT_SCHEMA_REVISION", "mdt-rc4-hardening"),
            observability_enabled=_env_bool("MDT_OBSERVABILITY_ENABLED", True),
            auto_create_schema=_env_bool("MDT_AUTO_CREATE_SCHEMA", environment != "production"),
        )
        settings.validate_operational()
        return settings
