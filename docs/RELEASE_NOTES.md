# Release Notes

## V1.0.0 — Final public release candidate

- Completed Digital-Twin-first synchronized residual planning.
- Four operational AI tasks with explicit baselines/metrics.
- Added executable ToC/DBR/CONWIP/SPC/DOE and broader IE methods.
- Added no-regret nominal scheduling, box-robust MILP, Pareto analysis and scenario-based CVaR policy optimization.
- Centralized solver-result semantics so `TIME_LIMIT` is not confused with feasibility or optimality.
- Added persisted decision runs and Approve/Reject/Defer human disposition.
- Rebuilt the signature machine-lane Future-State Production & Schedule-Recovery Laboratory for clearer synchronized-state context, operational AI, robust-policy evidence and human approval.
- Added flagship operations-console UX: operator runbook, scenario-lab/control-room/decision-center/evidence-room navigation, reproducible quick-scenario presets, visible workflow progress and automatic result reveal.
- Added a dedicated browser Engineering Methodology page plus `docs/METHODOLOGY.md` to explain the implemented IE/AI/OR/simulation mathematics and validation boundaries.
- Added machine-readable Constitution traceability and 25/25 final quality gate.
- Consolidated Windows startup/release acceptance and removed phase/retest clutter.
- Normalized versioning/documentation/public release assets to `1.0.0`.

## Product Runtime RC2 — Governed operating console

- Added explicit CLI/environment port resolution with preferred port 8010 and OS-assigned ephemeral mode.
- Added occupied-port fail-fast behavior and product acceptance coverage for requested, occupied, automatic and released ports.
- Added auditable event-ledger replay with before/after twin state identities and state-mutation summaries.
- Added explicit MILP schedule-displacement variables and γ stability penalty support for nominal and box-robust schedules.
- Added solver model-size evidence for Gurobi and HiGHS paths.
- Added machine-state board, finite-capacity slack table, schedule-difference evidence, event ledger and decision-history surfaces to the workbench.
- Added operator runbook and decision record schema documentation.

### Evidence boundary

Benchmark/synthetic/simulated results are not realized plant outcomes. Real plant calibration and site acceptance remain external validation work.

## Product Runtime RC3 — Production-readiness foundation

- Added environment-aware operational settings with production fail-fast rules for SQLite, disabled authentication and missing administrator credentials.
- Added viewer/operator/admin API-key boundaries with constant-time credential comparison and request correlation IDs.
- Added `/health`, `/ready`, `/metrics`, authenticated schema metadata and a versioned event-contract endpoint.
- Added atomic, replay-validated, idempotent event-batch ingestion at `/v1/ingest/events`.
- Added PostgreSQL production dependency shape, Dockerfile, Docker Compose deployment shape, production preflight and database operations guidance.

Plant-specific connectors, calibration, centralized identity, secret management, migration rollout, observability integration and site acceptance remain explicitly external gates.

## Development history

0.9.x was the Constitution-closure sequence used to expose and fix no-regret, Pareto, solver-status and Windows-launch regressions before V1.0. Earlier phases progressively established the event-sourced twin, AI + Gurobi scheduling, stochastic DES and signature product/Gemini layer.

### Final acceptance hardening

- Reordered final Windows acceptance so stale-tree, configuration, Gurobi-license, Gemini, and workspace-startup failures are surfaced before the long isolated test suite.
- Corrected runtime-smoke solver semantics: integration smoke now uses `backend=auto` and request timeouts sized for the full composite recovery/stress workflow rather than forcing SciPy behind a 15-second client timeout.
- Expanded obsolete-artifact detection to the full historical phase/candidate file set, preventing an over-extracted legacy working directory from masquerading as the final public V1 tree.
- Disabled proxy inheritance for localhost runtime smoke requests and increased graceful-shutdown allowance to cover a legitimately time-limited in-flight optimization.
