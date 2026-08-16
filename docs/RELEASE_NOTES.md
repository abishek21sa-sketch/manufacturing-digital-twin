# Release Notes

## V1.0.0 — Final public release candidate

- Completed Digital-Twin-first synchronized residual planning.
- Four operational AI tasks with explicit baselines/metrics.
- Added executable ToC/DBR/CONWIP/SPC/DOE and broader IE methods.
- Added no-regret nominal scheduling, box-robust MILP, Pareto analysis and scenario-based CVaR policy optimization.
- Centralized solver-result semantics so `TIME_LIMIT` is not confused with feasibility or optimality.
- Added persisted decision runs and Approve/Reject/Defer human disposition.
- Rebuilt the signature machine-lane Future-State Production & Schedule-Recovery Laboratory for clearer synchronized-state context, operational AI, robust-policy evidence and human approval.
- Added a dedicated browser Engineering Methodology page plus `docs/METHODOLOGY.md` to explain the implemented IE/AI/OR/simulation mathematics and validation boundaries.
- Added machine-readable Constitution traceability and 25/25 final quality gate.
- Consolidated Windows startup/release acceptance and removed phase/retest clutter.
- Normalized versioning/documentation/public release assets to `1.0.0`.

### Evidence boundary

Benchmark/synthetic/simulated results are not realized plant outcomes. Real plant calibration and site acceptance remain external validation work.

## Development history

0.9.x was the Constitution-closure sequence used to expose and fix no-regret, Pareto, solver-status and Windows-launch regressions before V1.0. Earlier phases progressively established the event-sourced twin, AI + Gurobi scheduling, stochastic DES and signature product/Gemini layer.

### Final acceptance hardening

- Reordered final Windows acceptance so stale-tree, configuration, Gurobi-license, Gemini, and workspace-startup failures are surfaced before the long isolated test suite.
- Corrected runtime-smoke solver semantics: integration smoke now uses `backend=auto` and request timeouts sized for the full composite recovery/stress workflow rather than forcing SciPy behind a 15-second client timeout.
- Expanded obsolete-artifact detection to the full historical phase/candidate file set, preventing an over-extracted legacy working directory from masquerading as the final public V1 tree.
- Disabled proxy inheritance for localhost runtime smoke requests and increased graceful-shutdown allowance to cover a legitimately time-limited in-flight optimization.
