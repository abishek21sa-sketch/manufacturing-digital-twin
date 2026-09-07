from __future__ import annotations

from dataclasses import dataclass
from secrets import compare_digest

from fastapi import Request

from mdt.config import Settings


ROLE_ORDER = {"viewer": 1, "operator": 2, "admin": 3}


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    auth_mode: str


class AuthenticationError(Exception):
    """Raised when an API request cannot be authenticated or authorized."""

    def __init__(self, detail: str, status_code: int = 401):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _api_key(request: Request) -> str | None:
    direct = request.headers.get("X-MDT-API-Key")
    if direct:
        return direct.strip()
    authorization = request.headers.get("Authorization", "")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _required_role(request: Request) -> str:
    if request.url.path.startswith("/v1/ops/"):
        return "admin"
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return "viewer"
    return "operator"


def authenticate_request(settings: Settings, request: Request) -> Principal:
    """Apply the platform's explicit local-vs-enterprise auth boundary.

    Local development deliberately stays frictionless. In API-key mode every
    versioned API route requires a role-bearing key; the key itself is never
    logged or returned to callers.
    """

    path = request.url.path
    public = {
        "/",
        "/health",
        "/ready",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/workspace",
        "/methodology",
    }
    if request.method == "OPTIONS" or path in public or path.startswith("/workspace/"):
        return Principal("public", "viewer", "none")
    if not path.startswith("/v1/") or settings.auth_mode == "disabled":
        return Principal("local", "admin", settings.auth_mode)

    supplied = _api_key(request)
    if not supplied:
        raise AuthenticationError("authentication required; supply X-MDT-API-Key or Authorization: Bearer <key>")

    candidates = (
        ("admin", settings.admin_api_key),
        ("operator", settings.operator_api_key),
        ("viewer", settings.readonly_api_key),
    )
    role = next((role for role, expected in candidates if expected and compare_digest(supplied, expected)), None)
    if role is None:
        raise AuthenticationError("invalid API credentials")
    required = _required_role(request)
    if ROLE_ORDER[role] < ROLE_ORDER[required]:
        raise AuthenticationError(f"role {role!r} cannot perform a {required}-level operation", status_code=403)
    return Principal(f"api-key:{role}", role, "api_key")
