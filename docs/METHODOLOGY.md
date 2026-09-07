# Engineering Methodology — V1.0

The browser Methodology page is served at `http://127.0.0.1:8010/methodology`. This document is the GitHub-readable companion. It summarizes only mathematics and model contracts that are implemented in the repository; `docs/TECHNICAL_METHODS.md` contains the full technical specification and validation details.

## Decision chain

```text
manufacturing events
→ synchronized TwinSnapshot
→ residual planning state
→ operational AI forecasts
→ IE consequence / release control
→ nominal + robust finite-capacity scheduling
→ stochastic discrete-event future states
→ CVaR policy selection
→ explainable recommendation
→ explicit human disposition
```

The central architectural rule is **Digital Twin First**: completed work is removed, running work is frozen/projected, current time/resource availability carries forward, and a down machine requires an explicit recovery assumption before AI/OR/simulation operate.

## Industrial Engineering mathematics

- **Little's Law:** `L = λW`.
- **Kingman G/G/1 waiting approximation:** `Wq ≈ [ρ/(1-ρ)] [(Ca²+Cs²)/2] E[S]`, with `ρ < 1`.
- **Availability:** `A = MTBF / (MTBF + MTTR)`.
- **Reliability:** `R(t) = exp(-t / MTBF)` under the exponential reference model.
- **Takt:** `available production time / customer demand`.
- **OEE:** `availability × performance × quality`.
- **Process Cycle Efficiency:** `value-added time / total lead time`.
- **JIT latest release:** `max(0, due time - remaining touch time - safety buffer)`.
- **SPC Individuals/MR:** `sigma_hat = MRbar / 1.128`, with `Xbar ± 3 sigma_hat` limits.
- **Two-level DOE:** balanced `-1/+1` main and two-way interaction effects use `2 * mean(x_term * y)`.

Theory of Constraints identifies workload/dynamic pressure constraints. Drum-Buffer-Rope sequences the constraint drum and calculates buffer/rope release timing. CONWIP is enforced as an admission constraint inside the DES, not merely reported as a KPI.

## Artificial Intelligence

Four separate operational tasks are implemented and quantitatively evaluated on grouped synthetic benchmark scenarios:

1. lateness-risk classification;
2. remaining/cycle-time regression;
3. future-bottleneck classification;
4. unsupervised operational anomaly detection.

Each task has its own target, model, baseline/challenger evidence and operational use. Published predictive metrics are **SYNTHETIC VALIDATION**, not real-plant accuracy.

## Operations Research

### Nominal finite-capacity job-shop MILP

Decision variables include continuous start/tardiness/makespan variables and binary same-machine order variables. The risk-aware objective is:

`min alpha*Cmax + sum_j w_j(beta + gamma*r_j)T_j`

subject to release/current-state readiness, precedence, machine non-overlap, tardiness and makespan constraints.

A nominal **no-regret service guard** requires:

`sum_j T_j <= status-quo SPT total tardiness`.

### Box robustness

Machine-specific bounded processing uncertainty uses:

`p'_o = p_o(1 + delta_m)`.

Predicted bottleneck risk can allocate stronger protection to likely future constraints.

### Multiobjective scheduling

Scalarizations expose the trade space in:

`(makespan, total tardiness, risk-weighted tardiness)`.

Returned candidate points are independently feasibility-checked and filtered for nondominance. A feasible `TIME_LIMIT` incumbent remains labeled `TIME_LIMIT`; it is never presented as optimal.

### Scenario-based CVaR policy MILP

For common-random-number Monte Carlo policy losses `L[p,s]`:

`min sum_p x_p E[L_p] + lambda [eta + 1/((1-alpha)N) sum_s u_s]`

with exactly one selected policy, binary `x_p`, and scenario excess constraints `u_s >= sum_p L[p,s]x_p - eta`. The result is independently checked by exact enumeration of every candidate policy objective.

## Stochastic digital twin

The custom discrete-event engine models releases, queues, starts/completions, stochastic processing, machine failures/repairs, preempt-resume interruptions, downtime segments and CONWIP admission. Candidate policies receive common seed sets. Reported outputs include mean/P95 performance, CVaR95, service level, WIP, utilization and confidence diagnostics.

## Explainability and governance

Every recommendation includes rationale, assumptions, uncertainty, modeled impact, trade-offs, solver evidence, evidence level, twin/run identifiers and explicit human disposition. Gemini is optional and operates **above** the deterministic stack: it parses bounded scenario language and explains computed evidence but does not create engineering calculations or solver results.

## Validation boundary

Repository validation covers benchmark parsing, event-state replay, IE reference mathematics, synthetic AI holdouts, solver/oracle/feasibility checks, deterministic DES bridges, stochastic invariants, robustness/stochastic selection, release hygiene and Windows runtime behavior.

Still external: named-plant MES/ERP/SCADA mapping, real distribution calibration, historical plant predictive validation, live OEE/SPC/takt signals, site acceptance and realized operational benefit.
