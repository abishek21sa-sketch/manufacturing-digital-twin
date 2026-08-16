# Repository Constitution Traceability — V1.0

This matrix makes the final Constitution audit explicit. `EXTERNAL_VALIDATION_PENDING` means the software boundary is implemented honestly but the claim requires real plant/site evidence. `JUSTIFIED_NON_SEPARATE` is used only where a separate technology/model would not add a real decision capability.

| ID | Governing requirement | Status | Evidence / interpretation |
|---|---|---|---|
| P1 | Decision Intelligence First | **IMPLEMENTED** | Predictions feed operational recovery, robust scheduling, stochastic policy selection and human disposition. |
| P2 | Industrial Engineering First | **VALIDATED** | Factory Physics, flow, reliability, ToC/DBR, CONWIP, capacity, SPC and DOE are executable/tested. |
| P3 | Digital Twin First | **VALIDATED** | AI/OR/simulation consume residual state derived from synchronized TwinSnapshot rather than pristine raw data. |
| P4 | Explainability First | **IMPLEMENTED** | Decision contract includes rationale, assumptions, uncertainty, expected modeled impact, trade-offs and evidence level. |
| P5 | Engineering Before Presentation | **VALIDATED** | Core models and independent checks exist below the workspace UI. |
| P6 | Enterprise Quality | **IMPLEMENTED** | API boundaries, persistence, resource lifecycle, release gates, audit records, docs and Windows acceptance. |
| P7 | Research Value | **IMPLEMENTED** | Distinct coupling of synchronized twin, operational AI, robust OR, DES and stochastic policy selection. |
| S1 | Data ingestion | **IMPLEMENTED** | Public benchmark plus canonical manufacturing-event CSV validation/replay. |
| S2 | State estimation / reconstruction | **VALIDATED** | Event-sourced TwinEngine with deterministic replay and state invariants. |
| S3 | Digital twin | **VALIDATED** | Current-state reconstruction plus future-state stochastic simulation. |
| S4 | Feature engineering | **IMPLEMENTED** | Job/system/machine features for lateness, cycle-time, bottleneck and anomaly tasks. |
| S5 | AI prediction | **SYNTHETICALLY_VALIDATED** | Four operational AI tasks with grouped holdouts and baselines. |
| S6 | Simulation | **VALIDATED** | DES, Monte Carlo, machine failures/repairs, scenario analysis, sensitivity. |
| S7 | Optimization | **VALIDATED** | Nominal, no-regret, box-robust, Pareto and CVaR policy optimization. |
| S8 | Decision engine | **VALIDATED** | Synchronized-twin recovery and future-state policy recommendation. |
| S9 | Explainability | **IMPLEMENTED** | Evidence labels, model contributions, solver truthfulness and complete decision contract. |
| S10 | Copilot | **WINDOWS_VALIDATED** | Gemini bounded scenario interpretation and evidence explanation; optional to core engineering. |
| S11 | APIs | **VALIDATED** | FastAPI routes covered by automated and runtime smoke tests. |
| S12 | Frontend | **WINDOWS_VALIDATED** | Machine-lane future-state workbench was Windows/browser validated before V1 polish; V1 adds synchronized-state context, decision/human-review presentation and a code-backed Methodology page. Exact final V1 browser acceptance remains the release-lock gate. |
| S13 | Testing | **VALIDATED** | Unit, integration, mathematical, solver, simulation, release and Windows acceptance gates. |
| S14 | Documentation | **IMPLEMENTED** | Architecture, Methodology, technical methods, validation, data, limitations, traceability and release story, plus a browser Methodology page tied to packaged evidence. |
| S15 | Deployment | **IMPLEMENTED** | Windows launcher/readiness wait, tested dependency pins and acceptance batch. |
| IE1 | Factory Physics | **VALIDATED** | Workload/flow relationships and simulation closure. |
| IE2 | Queueing Theory | **VALIDATED** | Utilization and Kingman approximation. |
| IE3 | Little's Law | **VALIDATED** | Reference math and DES closure. |
| IE4 | Kingman's Approximation | **VALIDATED** | G/G/1 approximation with parameter guards. |
| IE5 | Theory of Constraints | **VALIDATED** | Static workload constraint and dynamic pressure distinction. |
| IE6 | Drum-Buffer-Rope | **VALIDATED** | Executable drum sequence/buffer/rope release plan. |
| IE7 | CONWIP | **VALIDATED** | DES WIP-card admission and deadlock regression. |
| IE8 | Lean | **IMPLEMENTED** | PCE, flow/WIP visibility and pull-control logic without unsupported savings claims. |
| IE9 | JIT | **IMPLEMENTED** | Takt/latest-release and pull/release timing methods. |
| IE10 | Capacity Planning | **VALIDATED** | Per-machine workload/effective availability/load ratio/capacity gap. |
| IE11 | Scheduling | **VALIDATED** | Finite-capacity precedence/resource scheduling. |
| IE12 | Reliability | **VALIDATED** | MTBF/MTTR availability and failure/repair DES. |
| IE13 | SPC | **VALIDATED** | Individuals/Moving-Range limits and signal detection. |
| IE14 | DOE | **VALIDATED** | Two-level factorial main/interaction effects and sensitivity experiment. |
| OR1 | Linear Programming | **JUSTIFIED_NON_SEPARATE** | Continuous variables live within scheduling MILPs; a standalone LP cannot represent machine disjunctions and adds no distinct decision. |
| OR2 | Mixed-Integer Linear Programming | **VALIDATED** | Gurobi primary and separately coded SciPy/HiGHS path with independent feasibility validation. |
| OR3 | Network Optimization | **JUSTIFIED_NON_SEPARATE** | FT06 routing is fixed; there is no route/network-flow decision. Adding an artificial flow model would be technology bingo. |
| OR4 | Robust Optimization | **VALIDATED** | Formal box-robust processing-time counterpart with machine-specific uncertainty. |
| OR5 | Stochastic Optimization | **VALIDATED** | Scenario-based CVaR policy-selection MILP verified by exact enumeration. |
| OR6 | Constraint Programming | **JUSTIFIED_NON_SEPARATE** | Verified disjunctive MILP already represents the scheduling decision; CP is deferred until it provides measurable scale/performance value. |
| OR7 | Simulation Optimization | **VALIDATED** | Candidate policies evaluated under common random numbers before stochastic selection. |
| OR8 | Multi-objective Optimization | **VALIDATED** | Makespan/tardiness/risk scalarizations filtered to a nondominated Pareto set with truthful solver-status handling. |
| AI1 | Cycle-time Prediction | **SYNTHETICALLY_VALIDATED** | Regression model beats nominal touch-time baseline on grouped synthetic holdout. |
| AI2 | Bottleneck Prediction | **SYNTHETICALLY_VALIDATED** | Machine classifier compared with static-workload baseline. |
| AI3 | Lateness Prediction | **SYNTHETICALLY_VALIDATED** | Calibrated logistic classifier with class-prior/challenger evidence. |
| AI4 | Anomaly Detection | **SYNTHETICALLY_VALIDATED** | Isolation Forest evaluated on injected operational anomalies. |
| AI5 | Explainable AI | **IMPLEMENTED** | Lateness feature contributions plus non-causal evidence semantics. |
| AI6 | Recommendation Engine | **VALIDATED** | Predictions materially change robust buffers/objective/review and feed the decision contract. |
| AI7 | LLM Copilot where justified | **WINDOWS_VALIDATED** | Gemini adds scenario language/explanation while deterministic engineering remains independent. |
| SIM1 | Discrete-event simulation | **VALIDATED** | Custom release/start/completion/failure/repair/preempt-resume event engine. |
| SIM2 | Monte Carlo | **VALIDATED** | Seeded repeated future trajectories and confidence/tail metrics. |
| SIM3 | Scenario Analysis | **VALIDATED** | Plant-wide and machine-specific reliability/variability scenarios. |
| SIM4 | Sensitivity Analysis | **VALIDATED** | Scenario parameters plus factorial DOE effects. |
| D1 | Working digital twin | **VALIDATED** | Event-sourced synchronized state plus future-state DES. |
| D2 | Validated simulation | **VALIDATED** | Deterministic bridge, invariants and stochastic diagnostics. |
| D3 | Optimization models | **VALIDATED** | MILP/robust/Pareto/stochastic models with independent checks. |
| D4 | Explainable AI | **IMPLEMENTED** | Quantitative AI evidence and decision-level explanation. |
| D5 | Strong IE and OR foundations | **VALIDATED** | Executable engineering math and solver formulations. |
| D6 | Production-quality software | **IMPLEMENTED** | Package/API/persistence/lifecycle/security/release tooling appropriate for a local workstation. |
| D7 | Documentation | **IMPLEMENTED** | Public engineering story, methods, validation, traceability and limitations. |
| D8 | Reproducibility | **VALIDATED** | Pinned Windows-tested dependencies, deterministic seeds, packaged artifacts and release gates. |
| D9 | Portfolio readiness | **IMPLEMENTED** | Distinct signature workflow, quantitative evidence, explainable decision and public-release assets. |
| E1 | Real MES/ERP/SCADA/IIoT mapping | **EXTERNAL_VALIDATION_PENDING** | Requires a named plant/source contract; V1 provides canonical adapter/replay architecture without fabricated fields. |
| E2 | Plant-calibrated processing/failure distributions | **EXTERNAL_VALIDATION_PENDING** | Requires real observed data. |
| E3 | Real production predictive validation | **EXTERNAL_VALIDATION_PENDING** | Synthetic/benchmark metrics are not represented as plant accuracy. |
| E4 | Site acceptance / realized benefit | **EXTERNAL_VALIDATION_PENDING** | Requires deployment and measured operational outcomes. |

**Resolved requirements:** 68 / 68

**Unresolved:** 0

The repository does not claim real plant accuracy, realized savings, production deployment performance, or site acceptance without external evidence.
