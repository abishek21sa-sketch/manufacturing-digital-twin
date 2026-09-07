# Windows Deployment and Operations

Windows is the required local operating-system target for V1.0.

## Prerequisites

- Windows 10/11;
- Python 3.14 recommended (project metadata targets Python 3.14);
- a valid local Gurobi license for the primary optimization path;
- internet access only for initial package installation and optional Gemini API calls;
- Gemini API key only if the optional interrogation layer is used.

## Clean setup

From a freshly extracted repository:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements-windows-tested.txt
python -m pip install -e . --no-deps
```

Copy `.env.example` to `.env`. Never commit `.env`.

## Configuration

- `MDT_DATABASE_URL` — defaults to local SQLite under `runtime/`;
- `MDT_BENCHMARK_INSTANCE` — defaults to `ft06`;
- `GEMINI_API_KEY` — optional local secret;
- `MDT_GEMINI_MODEL` — optional model override;
- `MDT_COPILOT_ENABLED` — enable/disable Gemini layer.

Gurobi credentials/license material are never stored in this repository. The application uses the host's normal Gurobi license configuration.

## Start

```bat
run_windows.bat
```

The server binds to `127.0.0.1:8010` by default. This localhost binding is intentional; V1.0 is an engineering workstation, not a hardened public multi-user service. Use `MDT_PORT=0` for an OS-assigned ephemeral port.

## Acceptance

```bat
accept_v1_windows.bat
```

A passing final line is:

```text
WINDOWS_V1_ACCEPTANCE=PASS
```

## Resource lifecycle

Windows file-lock behavior is part of acceptance. SQLite engines, API lifespan services, Uvicorn smoke servers and Gemini clients are explicitly closed. Temporary database directories must be removable after tests; persistent file locks fail the gate.

## Troubleshooting

**Virtual environment already active.** Do not run `python -m venv .venv` on top of an active existing environment; use the existing `.venv` or extract to a fresh folder.

**Gurobi unavailable.** Verify `gurobipy` imports and your host license is valid. The API can use the independent SciPy backend for development, but final Windows acceptance requires Gurobi.

**Gemini unavailable.** Verify `.env` contains `GEMINI_API_KEY`. Gemini is optional for deterministic product operation but required by the final credential-backed acceptance script because V1.0 includes the feature.

**Port 8010 busy.** Select another requested port or set `MDT_PORT=0`; the launcher never silently changes a requested endpoint.

## Final acceptance order and fail-fast behavior

`accept_v1_windows.bat` deliberately checks public-tree cleanliness, local configuration, the Gurobi license, live Gemini access, and workspace startup **before** the long isolated computational suite. This prevents environment or stale-directory failures from being discovered only after the solver-heavy tests have completed.

The runtime smoke uses the API's `auto` solver backend. On the validated Windows target this selects licensed Gurobi; clean-room environments may fall back to SciPy/HiGHS. HTTP request budgets cover the complete composite recovery workflow (nominal, robust, and Pareto solves) rather than incorrectly assuming one solver time limit equals one endpoint time limit.
