# Operations Runbook

## Purpose

This runbook defines how an engineer or production planner uses the Manufacturing Digital Twin decision workstation. The product generates evidence-backed recovery recommendations; it does not autonomously release a schedule to MES or a machine controller.

## Controlled decision flow

```text
EVENT LEDGER
  -> deterministic twin replay
  -> TRUST-RH assessment
  -> residual-state recovery MILP
  -> stochastic future-state validation
  -> policy comparison and tail-risk selection
  -> engineer review
  -> approve, defer or reject
```

The first released action is the only action that can be considered for operational execution. The remaining horizon is a planning recommendation and must be rebuilt after new observations arrive.

## Evidence classes

| Class | Meaning | Operational rule |
| --- | --- | --- |
| Observed / ingested | Event-ledger and reconstructed state | Trace to source and timestamp |
| Predicted | Model output such as lateness or bottleneck risk | Keep the validation boundary visible |
| Optimized | Feasible nominal, robust or Pareto schedule | Treat as a recommendation, never as executed work |
| Simulated | Seeded future trajectories and policy metrics | Do not describe as realized plant performance |
| Realized | Site-confirmed execution outcome | Requires external plant data and acceptance |

## Trust states

`AUTHORIZED` means the repository-observable twin evidence satisfies the configured gate and the optimizer may generate a recommendation.

`HUMAN_REVIEW` means the evidence is not a full authorization. The planner may inspect the packet, but the gate must not be treated as an automatic optimizer enable.

`BLOCKED` means the optimizer must not execute. Typical causes are a ledger mismatch, inconsistent twin structure, insufficient model evidence, stale observations or an unresolved machine-down recovery assumption.

TRUST-RH authorizes recommendation generation only. The separate human disposition remains `PENDING` until an engineer explicitly approves, defers or rejects the decision run.

## Standard operator sequence

1. Start `RUN_DEMO.cmd` for the deterministic portfolio scenario or `RUN_APP.cmd` for the current runtime database.
2. Confirm the header shows `TWIN ONLINE`, the expected version and the intended port.
3. Inspect the synchronized machine board and finite-capacity constraint table.
4. Review the event ledger to confirm the event-to-state replay chain.
5. Assess TRUST-RH. Investigate every hard-stop reason before changing thresholds.
6. Build a synchronized recovery and review the nominal/robust solver evidence, frozen work and schedule difference metrics.
7. Run the representative future and four-policy stress test with common random numbers.
8. Record an explicit human disposition and note. Download the decision evidence JSON for the review record.
9. After new shop-floor events arrive, rebuild the twin and repeat the flow; never reuse a stale recommendation.

## Port and lifecycle controls

The preferred localhost port is 8010. Use `MDT_PORT` or `scripts/launch_workspace.py --port N` to select a requested port. Use `0` for an OS-assigned ephemeral port during parallel runs. A requested occupied port fails fast. Product acceptance verifies that the requested and automatically allocated ports are released after graceful shutdown.

The server must be stopped with Ctrl+C or the process lifecycle used by acceptance. Do not terminate a Python process by broad image name on a shared Windows workstation.

## Incident response

| Signal | Immediate action | Do not do |
| --- | --- | --- |
| `BLOCKED` trust state | Inspect ledger and freshness reasons; obtain new evidence or human review | Do not lower thresholds only to force execution |
| Machine is `DOWN` | Supply an explicit recovery timestamp or correct the twin | Do not invent availability in the UI |
| Solver has no feasible incumbent | Preserve the failure packet and inspect constraints | Do not label a heuristic schedule as MILP output |
| Simulation/policy ranking changes | Compare seeds, scenario assumptions and confidence intervals | Do not alter seeds or suppress a baseline |
| Occupied port | Select another requested port or use `MDT_PORT=0` | Do not silently switch endpoints |
| Gemini unavailable | Continue with deterministic engineering tools | Do not treat the LLM as a decision engine |

## Release gate

The distributable ZIP is complete only when the clean extraction contains the full source, packaged model artifacts, evidence, tests, Windows launchers and documentation. Acceptance must cover the public/static gate, runtime smoke, solver and TRUST-RH tests, port allocation/release, and the product workbench/API contract.

All bundled demo and benchmark results remain synthetic, simulated or historical replay evidence unless an underlying source explicitly establishes a stronger class.
