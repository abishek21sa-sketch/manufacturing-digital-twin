from __future__ import annotations

import json
from pathlib import Path
import socket
import sys

from mdt import __version__
from mdt.config import Settings


def _check_port_available(host: str = "127.0.0.1", port: int = 8000) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise RuntimeError(f"{host}:{port} is already in use; close the existing process before final acceptance") from exc


def _check_gurobi_license() -> str:
    try:
        import gurobipy as gp
    except Exception as exc:  # pragma: no cover - Windows acceptance path
        raise RuntimeError(f"gurobipy import failed: {exc}") from exc

    try:
        with gp.Env(params={"OutputFlag": 0}) as env, gp.Model("mdt-preflight", env=env) as model:
            x = model.addVar(lb=0.0, ub=1.0, name="x")
            model.setObjective(x)
            model.optimize()
            status = int(model.Status)
            if status != int(gp.GRB.OPTIMAL):
                raise RuntimeError(f"Gurobi trivial license preflight returned unexpected status {status}")
    except Exception as exc:  # pragma: no cover - Windows acceptance path
        raise RuntimeError(f"Gurobi environment/license check failed: {exc}") from exc
    return str(status)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []

    if __version__ != "1.0.0":
        failures.append(f"installed package version is {__version__}, expected 1.0.0")

    if sys.version_info[:2] != (3, 14):
        failures.append(f"Windows-tested interpreter is Python 3.14; current interpreter is {sys.version.split()[0]}")

    settings = Settings.from_env(root)
    if not settings.gemini_api_key:
        failures.append("GEMINI_API_KEY is not configured in process environment or repository-local .env")

    try:
        _check_port_available()
    except RuntimeError as exc:
        failures.append(str(exc))

    gurobi_status: str | None = None
    try:
        gurobi_status = _check_gurobi_license()
    except RuntimeError as exc:
        failures.append(str(exc))

    evidence = {
        "version": __version__,
        "python": sys.version.split()[0],
        "gemini_key_configured": bool(settings.gemini_api_key),
        "port_8000_available": not any("8000" in item for item in failures),
        "gurobi_preflight_status": gurobi_status,
    }
    print(json.dumps(evidence, indent=2))
    if failures:
        raise SystemExit("WINDOWS_PREFLIGHT=FAIL:\n" + "\n".join(f"- {item}" for item in failures))
    print("WINDOWS_PREFLIGHT=PASS")


if __name__ == "__main__":
    main()
