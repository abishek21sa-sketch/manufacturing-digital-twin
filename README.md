> **RC4 Windows acceptance:** from the outer extracted RC4 folder, run `.\RUN_ACCEPTANCE.cmd`. Do not run the PowerShell acceptance scripts directly. The RC4 launcher creates/verifies a Python 3.14 project venv, installs the acceptance dependencies, and runs the correct repository gate without depending on PowerShell execution policy.

# Manufacturing Digital Twin Decision Intelligence Platform

**Release:** V1.0 (`1.0.0`)  
**Primary local target:** Windows 11 / Python 3.14  
**Primary OR solver:** Gurobi; independent SciPy/HiGHS verification path  
**Optional LLM layer:** Google Gemini via local `GEMINI_API_KEY`  
**Evidence boundary:** public benchmark + synthetic AI validation + simulated future-state validation; real plant/site validation remains external.

## What this is

A computational manufacturing decision system that reconstructs shop-floor state from manufacturing events, predicts emerging operational risk, generates finite-capacity recovery schedules, stress-tests those schedules under stochastic processing and machine failure, and presents an evidence-labeled recommendation for explicit human review.

It is intentionally **not** a KPI dashboard called a digital twin. The production workflow is:

```text
MANUFACTURING EVENTS / PUBLIC BENCHMARK
                ↓
        SYNCHRONIZED EVENT-SOURCED TWIN
                ↓
  RESIDUAL STATE / CURRENT CLOCK / RESOURCE AVAILABILITY
                ↓
 LATENESS + CYCLE-TIME + BOTTLENECK + ANOMALY AI
                ↓
 IE FLOW / CAPACITY / RELIABILITY / RELEASE CONTROL
                ↓
  GUROBI FINITE-CAPACITY + BOX-ROBUST RECOVERY MILPs
                ↓
     STOCHASTIC DISCRETE-EVENT DIGITAL TWIN
                ↓
 MONTE CARLO + CVaR STOCHASTIC POLICY SELECTION
                ↓
   EXPLAINABLE RECOMMENDATION + HUMAN DISPOSITION
```

The signature interface is the **Future-State Production & Schedule-Recovery Laboratory** at `http://127.0.0.1:8010/workspace`. A companion **Engineering Methodology** page at `http://127.0.0.1:8010/methodology` explains the implemented IE, AI, OR and simulation mathematics and their validation boundaries. Set `MDT_PORT` or pass `scripts/launch_workspace.py --port`; use `0` for an OS-assigned ephemeral port during parallel acceptance runs.

For a career-fair or research demonstration, open the workspace in `mode=demo`, choose one of the four **Quick Scenarios**, then run the three visible stages: build synchronized recovery, simulate a representative future, and stress-test four policies. The workspace reveals each result as it completes and automatically brings the relevant timeline or decision surface into view. The `Baseline`, `Reliability shock`, `Due-date pressure` and `Process variability` presets are deterministic scenario assumptions, not plant observations.

## Digital-Twin-first architecture

`TwinSnapshot` is converted to a residual planning state before AI/OR/simulation operate:

- completed operations are removed;
- running work is frozen/projected from observed starts;
- current twin time becomes the scheduling origin;
- machine availability is carried forward;
- a machine currently DOWN requires an explicit recovery assumption;
- every analytical run retains a deterministic twin-state identifier and event count.

This prevents optimization from silently solving a pristine factory when the synchronized twin has already changed.

## AI — four operational tasks

1. **Lateness-risk classification** — calibrated standardized logistic regression; risk enters the tardiness objective.
2. **Remaining/cycle-time regression** — predicts flow consequence beyond nominal touch time.
3. **Future bottleneck prediction** — predicts the likely dynamic pressure constraint and informs robust buffers/stress targeting.
4. **Operational anomaly detection** — Isolation Forest flags machine-state patterns for human review; anomaly score is not presented as a probability.

Models are quantitatively evaluated on grouped synthetic holdouts against explicit baselines. Exact metrics and model-selection evidence are in `docs/evidence/` and `docs/TECHNICAL_METHODS.md`. These metrics are **synthetic validation**, not claimed plant accuracy.

Gemini is optional and sits above the deterministic stack. It parses bounded scenario language and explains already-computed evidence; it does not fabricate schedules, factory mathematics, solver results or simulation outputs.

## Industrial Engineering

Executable IE methods include:

- Factory Physics, throughput/WIP/flow relationships and Little's Law;
- queue utilization and Kingman's G/G/1 approximation;
- static and dynamic bottleneck analysis;
- Theory of Constraints and Drum-Buffer-Rope release planning;
- CONWIP admission enforced inside the DES;
- takt, capacity, JIT latest release, Process Cycle Efficiency and OEE relationships;
- MTBF/MTTR availability and reliability;
- SPC Individuals/Moving-Range logic;
- two-level factorial DOE/sensitivity effects.

The APIs explicitly refuse to fabricate OEE/takt/SPC outputs when the required live signals are absent.

## Operations Research

The principal decision model is a disjunctive finite-capacity job-shop MILP with:

- continuous operation start times;
- binary same-machine ordering variables;
- job tardiness variables;
- makespan;
- release/current-twin readiness constraints;
- operation precedence;
- resource non-overlap;
- current machine-availability boundaries;
- AI risk-weighted tardiness;
- an aggregate-tardiness no-regret guard relative to the status-quo SPT plan.

Additional decision methods:

- formal box-robust processing-time counterpart;
- multiobjective/Pareto schedule analysis;
- common-random-number simulation optimization;
- scenario-based CVaR stochastic policy-selection MILP;
- exact enumeration oracle for stochastic policy selection.

Gurobi is the primary Windows solver. A separately coded SciPy/HiGHS path and solver-independent schedule validator provide independent evidence. Solver termination is separated from physical feasibility: a complete independently valid time-limit incumbent can be usable without being mislabeled optimal.

## Stochastic digital twin

The custom event-driven simulation models:

- job release;
- operation readiness/start/completion;
- stochastic processing time;
- machine failure and repair;
- preempt/resume interruption;
- machine downtime;
- SPT, EDD, FIFO and planned sequences;
- CONWIP admission;
- seeded reproducibility;
- Monte Carlo future trajectories;
- P95/CVaR tail risk;
- Little's-Law and event-conservation invariants.

The simulator can reject a nominal optimization policy when its stochastic tail risk is worse. Simulation evidence is clearly labeled **simulated future-state evidence**.

## Decision evidence and audit

Each recommendation exposes:

- action;
- rationale;
- baseline and modeled impact;
- assumptions;
- uncertainty;
- trade-offs;
- solver status/gap and independently assessed solution quality;
- Pareto alternatives;
- evidence level;
- twin-state/run identifiers;
- explicit human review state.

Decision runs are persisted and can be marked `APPROVED`, `REJECTED` or `DEFERRED` with an audit note. No optimizer recommendation automatically becomes a plant action.

The product runtime also exposes the event reconstruction chain at `/v1/twin/ledger`: each row records the event sequence, source/provenance, before/after twin identity and the state objects changed by replay. The workbench presents this alongside finite-capacity slack, machine state, schedule difference evidence, and decision history.

## Data

V1.0 ships with the public **OR-Library FT06** job-shop benchmark and a canonical manufacturing-event CSV adapter/replay gate. Uploaded CSV data is validated and replayed in an **isolated twin**; it is never silently committed to the live event ledger.

The workbench also integrates the reproducible 150,000-row, 80-column
`data/synthetic/mdt_operational_scenarios_150000.csv` dataset. The UI shows its
integrity summary and provides a download link through `/v1/data/synthetic` and
`/v1/data/synthetic/download`. This dataset is synthetic scenario analytics,
not a canonical event history and not live plant telemetry; its manifest and
SHA-256 digest are checked before the summary is shown.

Live MES/ERP/SCADA/IIoT mapping, plant-calibrated distributions and site acceptance are intentionally listed as **external validation pending**, not simulated with invented fields.

## Run on Windows

From a clean extraction:

```powershell
Copy-Item .env.example .env
# Add GEMINI_API_KEY only if you want the optional Gemini layer.
.\run_windows.bat
```

The launcher installs the pinned Windows-tested dependencies, verifies static/frontend integrity, starts Uvicorn, waits for `/health` and `/workspace`, then opens the browser only after the server is ready.

`run_windows.bat` uses the preferred port from `MDT_PORT` (8010 by default). `run_demo_windows.bat` follows the same rule. For concurrent workspaces or CI, set `MDT_PORT=0` or invoke `python scripts/launch_workspace.py --port 0 --no-browser`.

For the final acceptance gate:

```powershell
.\accept_v1_windows.bat
```

The acceptance path exercises release/public gates, Gurobi, independent OR evidence, synchronized-twin recovery, robust/Pareto/stochastic logic, Gemini when configured, and the real workspace startup lifecycle.

## Validation and evidence

Core benchmark/reference evidence includes:

- FT06: 6 jobs, 6 machines, 36 operations, total work 197;
- exact makespan benchmark: 55 under makespan-only scheduling;
- independent Gurobi/HiGHS agreement on the exact benchmark;
- solver-independent schedule-feasibility validation;
- AI model/baseline metrics in `docs/evidence/`;
- deterministic DES bridge to known schedules;
- stochastic failure/repair invariant tests;
- common-random-number Monte Carlo and CVaR policy comparison;
- synchronized non-zero-twin closure diagnostics;
- Constitution traceability and final 25-question quality gate.

See `docs/METHODOLOGY.md`, `docs/TECHNICAL_METHODS.md`, `docs/VALIDATION.md`, `docs/VALIDATION_EVIDENCE.json`, `docs/CONSTITUTION_TRACEABILITY.md` and `docs/QUALITY_GATE.md`.

## Repository map

```text
src/mdt/                production Python package
  ai/                   model training/inference/explanations
  api/                  FastAPI application
  data/                 benchmark and external-event adapters
  ie/                   Industrial Engineering methods
  optimization/         nominal/robust/Pareto/stochastic OR
  simulation/           discrete-event future-state twin
  twin/                 event-sourced state reconstruction
workspace/              zero-build workbench + engineering methodology page
artifacts/ai/            packaged validated model artifacts
data/                    benchmark/sample inputs
docs/                    architecture, methods, evidence, traceability
scripts/                 diagnostics/release/Windows acceptance
```

## Important limitations

- AI accuracy is validated on synthetic benchmark-derived scenarios, not a named factory.
- Reliability/processing distributions are scenario assumptions until plant-calibrated.
- Historical CSV replay is an adapter/readiness boundary, not a live MES connector.
- OEE/SPC/takt cannot be called live plant measures without the required signals.
- Simulated/optimized improvements are **modeled consequences**, not realized savings.
- The product is a portfolio/research-grade workstation and still requires site-specific security, data contracts, governance and operational integration before production plant deployment.

## Release status

**V1.0 engineering baseline is preserved.** The product runtime release candidate adds governed operating-console surfaces and port/lifecycle hardening. The final distributed ZIP is accepted only after clean-extraction testing and the target Windows acceptance/browser checks.


## Signature algorithm
See [`docs/SIGNATURE_ALGORITHM.md`](docs/SIGNATURE_ALGORITHM.md) for the governed TRUST-RH formulation.


## Product runtime layer

The portfolio distribution adds three outer-folder commands in addition to the engineering acceptance gate:

```powershell
.\RUN_APP.cmd
.\RUN_DEMO.cmd
.\RUN_PRODUCT_ACCEPTANCE.cmd
```

`RUN_DEMO.cmd` resets a dedicated `runtime/mdt_demo.db`, loads a deterministic non-zero FT06 manufacturing history, executes a compact stress-test decision workflow, writes `artifacts/demo/latest_demo_evidence.json`, and launches the same production workspace in demo mode. The normal `runtime/mdt.db` is not overwritten. The workbench can also download the current decision evidence packet as JSON.

See `docs/OPERATIONS_RUNBOOK.md` for the operator workflow, trust-state handling, release gates, evidence boundaries and incident response expectations.

## Production-readiness foundation

RC4 hardens the platform boundary needed before a named plant deployment: production-aware settings, API-key role controls, request IDs, liveness/readiness/metrics endpoints, a versioned idempotent event-ingestion contract with request-fingerprint protection, reviewed Alembic migrations, PostgreSQL/Docker deployment artifacts, production preflight checks and a security policy. See `docs/PRODUCTION_READINESS.md`, `docs/EVENT_CONTRACT_V1.md`, `docs/DATABASE_OPERATIONS.md` and `SECURITY.md`.

These controls do not claim that a plant connector, plant calibration, enterprise identity integration or site acceptance has occurred. Those remain explicit external release gates.

## Cloud deployment (Render)

`render.yaml` at the repository root is a Render Blueprint for a single Docker web service built from the existing `Dockerfile` -- there is no separate frontend deployment because the FastAPI app serves the zero-build `workspace/` UI directly. It provisions a managed PostgreSQL database and wires `MDT_DATABASE_URL` to it automatically; **SQLite is not offered as a deployment option** because `src/mdt/config.py` itself rejects a `sqlite:` URL whenever `MDT_ENV=production`, requiring a server database and `MDT_AUTO_CREATE_SCHEMA=false` with reviewed Alembic migrations instead. The service's `dockerCommand` runs `alembic upgrade head` before starting Uvicorn, mirroring what `docker-compose.production.yml`'s separate `migrate` step does locally.

To deploy: push this repo to GitHub, then in the Render dashboard use "New +" -> "Blueprint" and point it at the repo. Render proposes the web service and database from `render.yaml`; review the auto-generated API keys (`MDT_API_KEY`, `MDT_READONLY_API_KEY`, `MDT_ADMIN_API_KEY`) in the dashboard before calling any `/v1/*` endpoint, and set `GEMINI_API_KEY` plus `MDT_COPILOT_ENABLED=true` only if the optional Gemini copilot layer is wanted. Render's free Postgres plan is time-limited and the free web-service plan spins down on idle, so treat this as a portfolio/demo deployment, not a persistent production instance. No deploy has been run against a real Render account as part of adding this file -- no deploy credentials were used or available.

## Pre-publication Fortune-50 readiness boundary

Before a public GitHub commit, run the offline claim/provenance gate:

```powershell
$env:PYTHONPATH="src"
$env:PYTHONNOUSERSITE="1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
.\.venv\Scripts\python.exe scripts\fortune50_preflight.py
```

The assessment in `docs/FORTUNE50_READINESS.md` and the model cards in
`docs/MODEL_CARDS.md` are part of the release contract. They make the project
stronger for research and career-fair review without claiming that synthetic
validation is plant accuracy or that a demo is approved for MES/SCADA/PLC
execution. Public source provenance and licensing boundaries are maintained in
`docs/PUBLIC_DATA_CATALOG.md`.
