# Architecture — V1.0

## Primary operational decision

**Given the synchronized current factory state, what feasible recovery / release / dispatch policy should operations use, and how robust is that action to future processing and reliability uncertainty?**

The core path is now Digital-Twin-first rather than benchmark-first:

```text
CANONICAL MANUFACTURING EVENTS
        ↓
DURABLE EVENT LEDGER
        ↓
SYNCHRONIZED TwinSnapshot
        ↓
TwinSnapshot → residual planning-state adapter
  • current clock
  • completed work removed
  • running work frozen/projected
  • machine availability carried forward
  • down machines require explicit recovery assumption
        ↓
AI FUTURE-STATE ESTIMATES
  • lateness probability
  • remaining/cycle-time prediction
  • future bottleneck probability
  • operational anomaly score
        ↓
IE OPERATIONAL CONSEQUENCE / CONTROL
  • WIP / flow / capacity / constraint
  • DBR release plan
  • CONWIP admission
  • reliability / queue effects
  • SPC / DOE / sensitivity
        ↓
OR DECISION LAYER
  • nominal risk-aware job-shop MILP
  • box-robust scheduling counterpart
  • makespan/tardiness/risk nondominated candidate frontier
        ↓
STOCHASTIC DIGITAL-TWIN STRESS TEST
  • failures / repairs / processing variability
  • common random numbers
  • candidate policy loss scenarios
        ↓
STOCHASTIC CVaR POLICY-SELECTION MILP
  • independently checked by exact policy enumeration
        ↓
EXPLAINABLE DECISION CONTRACT
  • action
  • rationale
  • modeled impact
  • uncertainty
  • assumptions
  • trade-offs
  • solver evidence
  • human approval state
        ↓
HUMAN APPROVE / REJECT / DEFER
```

## State boundary

`src/mdt/planning.py` is the architectural seam between operational truth and planning mathematics. Analytics may not silently regenerate a pristine factory when a synchronized twin exists.

Completed operations are removed from the residual model. A currently running operation is frozen using its observed start and a clearly stated nominal-remaining-time projection. A machine currently DOWN is **not** silently made available: the planner returns `NOT READY` until an explicit recovery timestamp is supplied.

Every derived planning state carries a deterministic `twin_state_id` hash plus event count/timestamp. Decision runs persist these values, model version, solver backend, input/output JSON and human disposition.

## AI roles

AI estimates uncertain future parameters; it does not replace IE/OR.

- Lateness classifier → tardiness weights.
- Cycle-time regressor → expected remaining flow-time consequence.
- Bottleneck classifier → likely future constraint / robust-buffer allocation / default stress target.
- Anomaly detector → human-review flag and stress-target evidence.
- Gemini → structured scenario interpretation and explanation only.

## IE roles

IE translates state/prediction into production-system consequences and control logic: WIP, throughput, flow time, constraint pressure, capacity gaps, DBR/CONWIP release behavior, reliability availability, SPC signals and factorial sensitivity.

## OR roles

The operation-level decision is finite-capacity scheduling. Gurobi is primary on the Windows target; HiGHS provides a separately coded solver implementation and the schedule validator independently checks feasibility.

Robust scheduling protects bounded processing-time uncertainty. Pareto analysis exposes makespan/tardiness/risk trade-offs and preserves solver termination status for every retained feasible point. After Monte Carlo generates policy scenario losses, a separate CVaR stochastic-selection MILP chooses one candidate policy and is checked by exact enumeration.

## Simulation role

The DES is not a visualization. It is an event queue with explicit release/start/complete/failure/repair events, preempt-resume processing, machine downtime, CONWIP admission, processing segments and reproducible seeded random substreams.

## Data modes

- public benchmark routing/processing data;
- canonical CSV historical event replay;
- durable local SQLite event ledger;
- generated synthetic future scenarios.

A real plant integration would implement a source adapter into the same canonical event schema and pass the readiness gate before analytics are enabled.

## Evidence semantics

Outputs are labeled as **OBSERVED/INGESTED**, **CALCULATED**, **PREDICTED**, **OPTIMIZED**, or **SIMULATED**. Benchmark/synthetic validation is not represented as real plant performance.


## Presentation layer

The zero-build browser client is intentionally a manufacturing operations workbench rather than a KPI dashboard. The main `/workspace` route centers the machine-lane future-state timeline, synchronized twin context, predictive risk, robust policy evidence and explicit human decision gate. `/methodology` is the code-backed mathematical companion and loads packaged validation evidence through `/v1/methodology/evidence`. Both pages are served locally by FastAPI and require no external frontend runtime.
