from __future__ import annotations

import argparse
import threading
import time
import webbrowser

import httpx
import uvicorn

from mdt import __version__
from mdt.api.main import app

HOST = "127.0.0.1"
PORT = 8000
BASE_URL = f"http://{HOST}:{PORT}"
WORKSPACE_URL = f"{BASE_URL}/workspace"
METHODOLOGY_URL = f"{BASE_URL}/methodology"


def _wait_until_ready(thread: threading.Thread, errors: list[BaseException], *, timeout_seconds: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        if errors:
            raise RuntimeError("Uvicorn failed during workspace startup") from errors[0]
        if not thread.is_alive():
            raise RuntimeError("Uvicorn exited before the workspace became ready")
        try:
            response = httpx.get(f"{BASE_URL}/health", timeout=0.75)
            if response.status_code == 200:
                payload = response.json()
                if payload.get("status") != "ok":
                    raise RuntimeError(f"Unexpected health payload: {payload}")
                if payload.get("version") != __version__:
                    raise RuntimeError(
                        f"Running server version {payload.get('version')!r} does not match installed package {__version__!r}"
                    )
                workspace = httpx.get(WORKSPACE_URL, timeout=1.5)
                workspace.raise_for_status()
                if "Future-State Production" not in workspace.text:
                    raise RuntimeError("Workspace route responded but expected application content was absent")
                methodology = httpx.get(METHODOLOGY_URL, timeout=1.5)
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
    parser.add_argument(
        "--exit-after-ready",
        action="store_true",
        help="Start the real server, prove /health and /workspace readiness, then shut it down. Used by acceptance tests.",
    )
    args = parser.parse_args()

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info", lifespan="on")
    server = uvicorn.Server(config)
    errors: list[BaseException] = []
    thread = threading.Thread(target=_run_server, args=(server, errors), name="mdt-workspace-server", daemon=False)
    thread.start()

    try:
        health = _wait_until_ready(thread, errors)
        print(f"WORKSPACE_SERVER_READY=PASS version={health.get('version')}", flush=True)
        print(f"[MDT] Workspace: {WORKSPACE_URL}", flush=True)

        if not args.exit_after_ready:
            if not args.no_browser:
                opened = webbrowser.open(WORKSPACE_URL, new=2)
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
