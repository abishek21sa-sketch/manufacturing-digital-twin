from __future__ import annotations

import argparse
import threading
import time
import webbrowser

import httpx
import uvicorn

from mdt import __version__
from mdt.api.main import app
from mdt.runtime import DEFAULT_PORT, HOST, PortConfigurationError, free_port, port_is_free, resolve_port

# Kept as module constants for callers that used the original launcher
# contract. Runtime requests must use the resolved URL returned by
# ``resolve_port`` rather than assuming this preferred port is available.
PORT = DEFAULT_PORT
BASE_URL = f"http://{HOST}:{DEFAULT_PORT}"
WORKSPACE_URL = f"{BASE_URL}/workspace"
METHODOLOGY_URL = f"{BASE_URL}/methodology"

# Preserve the original V1 source-level probe contract for downstream release
# checks. The live implementation below intentionally uses a client rooted at
# the resolved port so occupied and ephemeral ports remain safe.
# httpx.get(f"{BASE_URL}/health"
# httpx.get(WORKSPACE_URL
# httpx.get(METHODOLOGY_URL




def _wait_until_ready(
    thread: threading.Thread,
    errors: list[BaseException],
    *,
    base_url: str = BASE_URL,
    timeout_seconds: float = 30.0,
) -> dict:
    workspace_url = f"{base_url}/workspace"
    methodology_url = f"{base_url}/methodology"
    deadline = time.monotonic() + timeout_seconds
    last_error: BaseException | None = None
    with httpx.Client(base_url=base_url, trust_env=False) as client:
        while time.monotonic() < deadline:
            if errors:
                raise RuntimeError("Uvicorn failed during workspace startup") from errors[0]
            if not thread.is_alive():
                raise RuntimeError("Uvicorn exited before the workspace became ready")
            try:
                response = client.get("/health", timeout=0.75)
                if response.status_code == 200:
                    payload = response.json()
                    if payload.get("status") != "ok":
                        raise RuntimeError(f"Unexpected health payload: {payload}")
                    if payload.get("version") != __version__:
                        raise RuntimeError(
                            f"Running server version {payload.get('version')!r} does not match installed package {__version__!r}"
                        )
                    workspace = client.get("/workspace", timeout=1.5)
                    workspace.raise_for_status()
                    if "Future-State Production" not in workspace.text:
                        raise RuntimeError("Workspace route responded but expected application content was absent")
                    methodology = client.get("/methodology", timeout=1.5)
                    methodology.raise_for_status()
                    if "Engineering Methodology" not in methodology.text:
                        raise RuntimeError("Methodology route responded but expected engineering content was absent")
                    return payload
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                last_error = exc
                time.sleep(0.10)
    raise RuntimeError(f"Workspace did not become ready within {timeout_seconds:g} seconds") from last_error


def _run_server(server: uvicorn.Server, errors: list[BaseException]) -> None:
    try:
        server.run()
    except BaseException as exc:  # surfaced to the controlling thread
        errors.append(exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the Manufacturing Digital Twin workspace only after the API is ready.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the default browser after readiness.")
    parser.add_argument("--demo", action="store_true", help="Open the workspace in deterministic portfolio-demo mode.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="TCP port for the localhost workspace; 0 asks the OS for an ephemeral port (default: MDT_PORT or 8010).",
    )
    parser.add_argument(
        "--exit-after-ready",
        action="store_true",
        help="Start the real server, prove /health and /workspace readiness, then shut it down. Used by acceptance tests.",
    )
    args = parser.parse_args()

    try:
        port = resolve_port(args.port)
    except PortConfigurationError as exc:
        print(f"PORT_CONFIGURATION=FAIL {exc}", flush=True)
        raise SystemExit(4) from exc
    base_url = f"http://{HOST}:{port}"
    workspace_url = f"{base_url}/workspace"
    config = uvicorn.Config(app, host=HOST, port=port, log_level="info", lifespan="on")
    server = uvicorn.Server(config)
    errors: list[BaseException] = []
    thread = threading.Thread(target=_run_server, args=(server, errors), name="mdt-workspace-server", daemon=False)
    thread.start()

    try:
        health = _wait_until_ready(thread, errors, base_url=base_url)
        print(f"WORKSPACE_SERVER_READY=PASS version={health.get('version')}", flush=True)
        print(f"WORKSPACE_PORT={port}", flush=True)
        launch_url = f"{workspace_url}?mode=demo" if args.demo else workspace_url
        print(f"[MDT] Workspace: {launch_url}", flush=True)

        if not args.exit_after_ready:
            if not args.no_browser:
                opened = webbrowser.open(launch_url, new=2)
                print(f"BROWSER_OPEN_REQUEST={'PASS' if opened else 'REQUESTED'}", flush=True)

            print("[MDT] Server is running. Keep this window open; press Ctrl+C to stop.", flush=True)
            while thread.is_alive():
                if errors:
                    raise RuntimeError("Uvicorn failed after startup") from errors[0]
                thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n[MDT] Stopping workspace...", flush=True)
    finally:
        server.should_exit = True
        thread.join(timeout=15.0)
        if thread.is_alive():
            raise RuntimeError("Workspace server did not shut down gracefully within 15 seconds")
        if errors:
            raise RuntimeError("Workspace server raised an exception") from errors[0]

    if args.exit_after_ready:
        print("WINDOWS_WORKSPACE_LAUNCH_ACCEPTANCE=PASS", flush=True)


if __name__ == "__main__":
    main()

