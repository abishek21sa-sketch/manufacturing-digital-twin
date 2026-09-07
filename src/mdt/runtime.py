from __future__ import annotations

import os
import socket

HOST = "127.0.0.1"
# Keep local workbench instances away from the conventional development port.
# Container deployments may still expose the internal HTTP listener on 8000;
# this is the host-facing Windows default.
DEFAULT_PORT = 8010


class PortConfigurationError(RuntimeError):
    """Raised when a requested local workspace port cannot be used."""


def free_port(host: str = HOST) -> int:
    """Ask the OS for a currently free localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def port_is_free(port: int, host: str = HOST) -> bool:
    """Return whether a TCP port can currently be bound on ``host``."""
    if port == 0:
        return True
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def _coerce_port(value: int | str | None) -> int:
    if value is None or str(value).strip() == "":
        return DEFAULT_PORT
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise PortConfigurationError(f"invalid MDT port {value!r}; use 0 or an integer from 1024 to 65535") from exc
    if port != 0 and not 1024 <= port <= 65535:
        raise PortConfigurationError(f"invalid MDT port {port}; use 0 or an integer from 1024 to 65535")
    return port


def resolve_port(requested: int | str | None = None, *, host: str = HOST) -> int:
    """Resolve CLI/environment configuration into a safe workspace port."""
    configured = requested if requested is not None else os.getenv("MDT_PORT")
    port = _coerce_port(configured)
    if port == 0:
        return free_port(host)
    if not port_is_free(port, host):
        raise PortConfigurationError(
            f"{host}:{port} is already in use; choose another port or set MDT_PORT=0 for automatic allocation"
        )
    return port
