# Validation — V1.0

V1.0 uses layered evidence rather than a single percentage-complete claim.

## Automated release suite

The repository contains **75 automated tests across 22 test modules**. Release execution runs one test file per Python process to isolate native solver/thread state and make Windows cleanup deterministic; `scripts/test_suite_isolated.py` reports the aggregate count and the release check fails on any test failure.

Coverage includes twin replay/invariants, planning-state conversion, all four AI artifacts, IE reference math, nominal/robust/stochastic OR, solver-result semantics, simulation invariants, API/data/Gemini contracts, persistence/resource cleanup, workspace contracts and public-release hygiene.

## Optimization evidence

- Public OR-Library FT06 benchmark.
- Makespan-only optimum: 55.
- Gurobi primary solver and separately coded SciPy/HiGHS path.
- Independent schedule validator checks duration, assignment, releases/machine-ready boundaries, precedence and non-overlap.
- `ScheduleAssessment` retains truthful termination status and separately establishes physical feasibility/optimality proof.
- Stochastic CVaR policy selection is independently verified by exact enumeration.

## AI evidence

AI metrics are **synthetic validation**. The release includes model artifacts and JSON evidence for lateness, cycle-time, bottleneck and anomaly tasks with explicit baselines. These are not represented as real plant predictive accuracy.

## Simulation evidence

- Deterministic DES bridges reproduce known scheduling outcomes when uncertainty is disabled.
- Failure/repair/preempt-resume logic is invariant-tested.
- Common-random-number Monte Carlo reports mean/P95/CVaR/confidence diagnostics.
- Simulation violations and Little's-Law closure are checked in diagnostics.

## Constitution diagnostic

`scripts/v1_diagnostics.py` constructs a non-zero event-sourced twin and checks synchronized residual planning, AI tasks, IE closure, nominal/robust/Pareto/stochastic OR, decision audit, traceability resolution and V1 version/quality-gate consistency.

## Runtime/product evidence

- static/secret gate;
- JavaScript syntax and frontend contract gate;
- live Uvicorn runtime smoke;
- exact workspace `/health` and `/workspace` readiness;
- final browser workflow acceptance on the exact distributed ZIP;
- target Windows acceptance with licensed Gurobi and configured Gemini.

## External boundary

Real MES/ERP/SCADA/IIoT mapping, plant calibration, drift monitoring, site acceptance and realized benefit require external evidence and remain explicitly pending.
