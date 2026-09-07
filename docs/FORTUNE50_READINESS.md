# Fortune-50 Readiness Assessment

Date: 2026-09-06  
Release scope: public V1.0 portfolio/research release

This document is the claim boundary for the repository. It distinguishes what
is complete in a reproducible engineering release from what can only be proven
with a real plant, real labels, enterprise controls, and site acceptance.

## Executive assessment

| Area | Repository status | Evidence boundary |
|---|---|---|
| Industrial engineering and mathematical formulation | **GREEN — complete** | Implemented and regression-tested on FT06/public benchmark and deterministic scenarios. |
| Operations research and optimization | **GREEN — complete** | Gurobi primary path, independent SciPy/HiGHS path, feasibility validator, robust/Pareto/CVaR methods, and exact small-case oracle. |
| AI/ML engineering | **GREEN — complete for research/demo scope** | Four operational models have grouped holdouts, baselines, calibration/error metrics, packaged artifacts, and explicit limitations. |
| Public-data provenance | **GREEN — documented and bounded** | OR-Library data is bundled and used; UCI/NASA sources are catalogued by method and are not misrepresented as a complete plant twin. |
| Synthetic scenario coverage | **GREEN — complete for portfolio scope** | 150,000 deterministic rows, 80 governed columns, ten scenario families, semantic checks, manifest, digest, API summary, and download boundary. |
| Production platform foundation | **AMBER — strong foundation** | API-key role boundary, request IDs, metrics, readiness, migrations, PostgreSQL/Docker shape, idempotent ingestion, and security policy are present. |
| Named-plant production deployment | **EXTERNAL — not claimed** | Requires plant connectors, calibration, SSO/secrets/TLS, tenant/site controls, drift monitoring, backup rehearsal, UAT, and approval. |

The portfolio/research release is ready to publish. A real Fortune-50 plant
deployment is not something a student repository can honestly certify without
completing the external plant deployment gates below and without
the company's systems, data, security review, and operating sign-off.

## IE and mathematical checklist

The release contains executable, tested methods for:

- synchronized residual-twin reconstruction before planning;
- finite-capacity job-shop MILP with precedence, release, machine-ready,
  non-overlap, tardiness, makespan, and risk-weighted terms;
- solver-independent schedule validation and truthful solver-status handling;
- box-robust processing-time protection and Pareto alternatives;
- CONWIP, Drum-Buffer-Rope, bottleneck/constraint analysis, Little's Law,
  utilization, capacity, takt, JIT release, PCE, OEE gating, MTBF/MTTR,
  Kingman's approximation, SPC Individuals/MR, and two-level DOE;
- seeded discrete-event simulation with failure/repair, preemption, WIP caps,
  event conservation, Little's-Law closure, Monte Carlo, common random
  numbers, P95/CVaR, and policy selection;
- a no-regret/status-quo guard and an explicit human disposition gate.

These are mathematical/engineering validation claims, not claims of realized
factory benefit.

## AI/ML checklist

The four deterministic operational models are:

1. grouped-scenario lateness-risk classification;
2. remaining/cycle-time regression;
3. future dynamic-bottleneck prediction; and
4. operational anomaly detection.

Each model has a model card in [`MODEL_CARDS.md`](MODEL_CARDS.md). The release
uses scenario/group splits to reduce leakage, compares against a simple
baseline, preserves test metrics, and labels synthetic validation as
synthetic. Risk is used as an optimization weight; bottleneck prediction
selects a stress target; anomaly scores trigger human review. No model is
allowed to silently command a machine or release a schedule.

## Public-data boundary

The public-data decisions are documented in [`PUBLIC_DATA_CATALOG.md`](PUBLIC_DATA_CATALOG.md).
The repository uses the OR-Library job-shop benchmark directly because it
matches the scheduling problem. UCI AI4I and UCI SECOM are useful public
predictive-maintenance/process references but do not contain the complete
event-sourced scheduling schema. NASA prognostics data is useful for
reliability-method comparison but is not factory shop-floor telemetry.

Where the public sources do not provide a needed field, the project uses
deterministic synthetic values and marks them `synthetic_demo`. It does not
join unrelated public sources into a fictional company or claim that the
result is observed plant data.

## External gates that remain real-world work

These are not hidden implementation TODOs; they require an external site and
authority:

- MES/ERP/SCADA/IIoT source mapping, clock quality, replay/backfill policy, and
  a versioned site data contract;
- plant-calibrated processing, failure, repair, quality, yield, and demand
  distributions with time-based backtesting;
- production SSO/RBAC, secret-manager rotation, TLS/network policy,
  tenant/site isolation, vulnerability review, and audit retention;
- PostgreSQL migration execution plus backup/restore and disaster-recovery
  rehearsal;
- model drift thresholds, monitoring, retraining approval, and rollback;
- planner/operator UAT, safety review, change management, and approval before
  any connection to execution systems;
- measured benefits such as OTIF, throughput, WIP, downtime, scrap, or cost.

## What to say at the career fair

> “This is a reproducible manufacturing decision-intelligence laboratory. It
> combines public job-shop benchmarks, synthetic operational scenarios, IE/OR
> mathematics, ML risk signals, and stochastic future-state simulation. Every
> result is evidence-labeled, and the repository explicitly separates demo
> evidence from the validation required for a real plant.”

Do not say that the models are trained on a named company's plant, that the
simulation proves savings, or that the repository is already approved to write
to MES/SCADA/PLC systems.

## Publication decision

`FORTUNE50_PREPUBLICATION_GATE=PASS` means the repository is publishable as a
serious student research/portfolio release with an honest enterprise boundary.
It does **not** mean `plant_deployment_approved` or `real_world_accuracy_proven`.
