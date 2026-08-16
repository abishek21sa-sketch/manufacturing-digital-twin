from __future__ import annotations

from dataclasses import asdict, replace
from uuid import uuid4

from mdt.ai import (
    AnomalyBundle,
    BottleneckBundle,
    CycleTimeBundle,
    LatenessRiskBundle,
    explain_lateness_scores,
    heuristic_dispatch,
    score_bottleneck,
    score_cycle_time,
    score_planning_jobs,
    score_snapshot_anomalies,
)
from mdt.domain import FactoryModel, TwinSnapshot
from mdt.optimization import (
    BoxRobustnessSpec,
    ObjectiveWeights,
    ScheduleProblem,
    default_planning_jobs,
    pareto_schedule_frontier,
    solve_box_robust_schedule,
    solve_schedule,
    assess_schedule,
    validate_schedule,
)
from mdt.planning import TwinPlanningState, planning_state_from_twin
from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, stress_test_policies


def _baseline_payload(problem: ScheduleProblem) -> dict:
    baseline = heuristic_dispatch(problem, "SPT")
    tardiness = {
        job.job_id: max(0.0, baseline.completion[job.job_id] - problem.planning_job(job.job_id).due_time)
        for job in problem.factory.jobs
    }
    total_tardiness = float(sum(tardiness.values()))
    risk_weighted_tardiness = float(
        sum(problem.planning_job(job_id).risk_score * value for job_id, value in tardiness.items())
    )
    objective_value = float(
        problem.objective.makespan * baseline.makespan
        + problem.objective.tardiness * total_tardiness
        + problem.objective.risk_tardiness * risk_weighted_tardiness
    )
    return {
        "policy": "SPT",
        "makespan": baseline.makespan,
        "total_tardiness": total_tardiness,
        "job_tardiness": tardiness,
        "objective_components": {
            "makespan": baseline.makespan,
            "total_tardiness": total_tardiness,
            "risk_weighted_tardiness": risk_weighted_tardiness,
        },
        "objective_value": objective_value,
    }


def _with_no_regret_tardiness_guard(problem: ScheduleProblem, baseline: dict) -> ScheduleProblem:
    """Prevent a risk-aware schedule from worsening aggregate tardiness.

    The AI-weighted objective is intentionally allowed to redistribute tardiness
    toward lower-risk jobs.  For an operational recommendation, however, that
    trade-off must not silently worsen the aggregate customer tardiness of the
    explicit status-quo baseline.  This epsilon-constraint creates a stable
    no-regret business guard while leaving risk weighting in the objective.
    """
    return replace(problem, max_total_tardiness=float(baseline["total_tardiness"]))


def _planning_payload(state: TwinPlanningState) -> dict:
    return {
        "source": "SYNCHRONIZED_TWIN_STATE",
        "twin_timestamp": state.current_time,
        "twin_event_count": state.source_event_count,
        "twin_state_id": state.source_state_id,
        "completed_jobs": list(state.completed_job_ids),
        "completed_operations": len(state.completed_operation_ids),
        "frozen_operations": [asdict(op) for op in state.frozen_operations],
        "projected_frozen_job_completion": state.projected_frozen_job_completion,
        "schedulable_jobs": state.schedulable_jobs,
        "schedulable_operations": state.schedulable_operations,
        "machine_available_from": state.machine_available_from,
        "assumptions": list(state.assumptions),
    }


def _robustness_from_bottleneck(
    bottleneck_scores: dict[str, float],
    processing_cv: float,
) -> BoxRobustnessSpec:
    base = min(0.25, max(0.05, float(processing_cv)))
    machine_buffer = {
        machine_id: min(0.50, base + 0.20 * probability)
        for machine_id, probability in bottleneck_scores.items()
    }
    return BoxRobustnessSpec(default_relative_buffer=base, machine_relative_buffer=machine_buffer)


def _build_twin_problem(
    factory: FactoryModel,
    snapshot: TwinSnapshot,
    risk_model: LatenessRiskBundle,
    *,
    due_factor: float,
    down_machine_recovery: dict[str, float] | None,
) -> tuple[TwinPlanningState, ScheduleProblem, tuple]:
    state = planning_state_from_twin(
        factory,
        snapshot,
        due_factor=due_factor,
        down_machine_recovery=down_machine_recovery,
    )
    if not state.residual_factory.jobs:
        return state, ScheduleProblem(state.residual_factory, (), ObjectiveWeights(makespan=1.0), current_time=state.current_time, machine_available_from=state.machine_available_from), ()
    scored = score_planning_jobs(risk_model, state.residual_factory, state.planning_jobs)
    problem = ScheduleProblem(
        state.residual_factory,
        scored,
        ObjectiveWeights(makespan=0.05, tardiness=1.0, risk_tardiness=2.0),
        current_time=state.current_time,
        machine_available_from=state.machine_available_from,
    )
    return state, problem, scored


def build_twin_recovery_decision(
    factory: FactoryModel,
    snapshot: TwinSnapshot,
    risk_model: LatenessRiskBundle,
    cycle_model: CycleTimeBundle,
    bottleneck_model: BottleneckBundle,
    anomaly_model: AnomalyBundle,
    *,
    backend: str = "auto",
    due_factor: float = 1.5,
    time_limit: float = 30.0,
    processing_cv: float = 0.10,
    mtbf: float | None = 120.0,
    mttr: float = 8.0,
    down_machine_recovery: dict[str, float] | None = None,
) -> dict:
    """Build the operational recovery decision from the synchronized twin state."""

    state, problem, scored = _build_twin_problem(
        factory,
        snapshot,
        risk_model,
        due_factor=due_factor,
        down_machine_recovery=down_machine_recovery,
    )
    run_id = str(uuid4())
    if not state.residual_factory.jobs:
        return {
            "run_id": run_id,
            "planning_state": _planning_payload(state),
            "decision": {
                "action": "no rescheduling required",
                "rationale": "the synchronized twin has no schedulable residual operations",
                "expected_modeled_impact": {},
                "uncertainty": {},
                "assumptions": list(state.assumptions),
                "trade_offs": [],
                "human_review_required": False,
                "human_disposition": "pending",
                "evidence_level": "CALCULATED FROM SYNCHRONIZED TWIN",
            },
        }

    simulation_config = SimulationConfig(
        seed=20260815,
        processing_cv=processing_cv,
        reliability=ReliabilitySpec(mtbf=mtbf, mttr=mttr),
        record_events=False,
    )
    bottleneck_scores = score_bottleneck(bottleneck_model, state.residual_factory, simulation_config)
    predicted_bottleneck = max(bottleneck_scores, key=bottleneck_scores.get)
    cycle_time = score_cycle_time(cycle_model, state.residual_factory, scored)
    anomalies = score_snapshot_anomalies(anomaly_model, factory, snapshot)
    anomalous_machines = [machine_id for machine_id, row in anomalies.items() if bool(row["is_anomaly"])]
    explanations = explain_lateness_scores(risk_model, state.residual_factory, scored, top_k=3)

    baseline = _baseline_payload(problem)
    nominal_problem = _with_no_regret_tardiness_guard(problem, baseline)
    optimized = solve_schedule(nominal_problem, backend=backend, time_limit=time_limit, mip_gap=0.0)
    nominal_assessment = assess_schedule(nominal_problem, optimized)
    nominal_violations = nominal_assessment.violations

    robustness = _robustness_from_bottleneck(bottleneck_scores, processing_cv)
    robust = solve_box_robust_schedule(problem, robustness, backend=backend, time_limit=time_limit, mip_gap=0.0)
    robust_schedule = robust.schedule
    robust_assessment = assess_schedule(robust.robust_problem, robust_schedule)
    robust_violations = robust_assessment.violations

    # Pareto analysis uses a bounded fast pass so normal decision latency does
    # not triple the main scheduling budget. Time-limited incumbents are kept
    # only after independent feasibility validation. If a slower platform finds
    # no incumbent in that fast pass, retry one balanced scalarization with the
    # caller's full solve budget rather than returning an empty frontier.
    pareto_fast_limit = min(time_limit, 5.0)
    pareto = pareto_schedule_frontier(
        problem,
        backend=backend,
        weight_grid=((1.0, 0.0), (0.05, 1.0), (0.0, 1.0)),
        risk_tardiness_weight=1.0,
        time_limit=pareto_fast_limit,
    )
    if not pareto and time_limit > pareto_fast_limit:
        pareto = pareto_schedule_frontier(
            problem,
            backend=backend,
            weight_grid=((0.05, 1.0),),
            risk_tardiness_weight=1.0,
            time_limit=time_limit,
        )

    valid_nominal = nominal_assessment.feasible
    valid_robust = robust_assessment.feasible
    recommended_schedule = "BOX_ROBUST_AI" if valid_robust else ("AI_RISK_NOMINAL" if valid_nominal else "NONE")
    expected_impact = {
        "baseline_spt_makespan": baseline["makespan"],
        "baseline_spt_total_tardiness": baseline["total_tardiness"],
        "nominal_no_regret_tardiness_cap": baseline["total_tardiness"],
        "nominal_optimized_makespan": optimized.makespan,
        "nominal_optimized_total_tardiness": sum(optimized.job_tardiness.values()) if optimized.job_tardiness else None,
        "box_robust_makespan_upper_bound_schedule": robust_schedule.makespan,
        "box_robust_total_tardiness_upper_bound_schedule": sum(robust_schedule.job_tardiness.values()) if robust_schedule.job_tardiness else None,
        "label": "MODELED / OPTIMIZED BENCHMARK CONSEQUENCE — NOT REALIZED BENEFIT",
    }
    risk_rows = {
        job.job_id: {
            "lateness_probability": job.risk_score,
            "predicted_cycle_time": cycle_time[job.job_id],
            "top_lateness_drivers": explanations.get(job.job_id, []),
        }
        for job in scored
    }
    review_reasons = ["all optimized/simulated manufacturing recommendations require explicit human approval before execution"]
    if anomalous_machines:
        review_reasons.append("one or more machines are flagged anomalous by the operational anomaly model")
    if down_machine_recovery:
        review_reasons.append("the plan depends on explicit down-machine recovery assumptions")
    review_required = True
    result = {
        "run_id": run_id,
        "evidence_labels": {
            "twin": "OBSERVED/INGESTED STATE — EVENT-SOURCED",
            "lateness": "PREDICTED — SYNTHETICALLY VALIDATED",
            "cycle_time": "PREDICTED — SYNTHETICALLY VALIDATED",
            "bottleneck": "PREDICTED — SYNTHETICALLY VALIDATED",
            "anomaly": "ANOMALY SCORE — SYNTHETICALLY VALIDATED, NOT A PROBABILITY",
            "nominal": "OPTIMIZED DECISION",
            "robust": "ROBUST OPTIMIZED DECISION — BOX UNCERTAINTY",
        },
        "planning_state": _planning_payload(state),
        "ai": {
            "jobs": risk_rows,
            "future_bottleneck_probability": bottleneck_scores,
            "predicted_bottleneck": predicted_bottleneck,
            "machine_anomaly": anomalies,
            "anomalous_machines": anomalous_machines,
        },
        "baseline": baseline,
        "nominal_optimized": {
            "makespan": optimized.makespan,
            "total_tardiness": sum(optimized.job_tardiness.values()) if optimized.job_tardiness else None,
            "objective_components": optimized.objective_components,
            "solver": asdict(optimized.evidence),
            "solution_quality": asdict(nominal_assessment),
            "violations": [asdict(v) for v in nominal_violations],
            "operations": [asdict(op) for op in optimized.operations],
        },
        "robust_optimized": {
            "uncertainty": asdict(robust.evidence),
            "makespan": robust_schedule.makespan,
            "total_tardiness": sum(robust_schedule.job_tardiness.values()) if robust_schedule.job_tardiness else None,
            "solver": asdict(robust_schedule.evidence),
            "solution_quality": asdict(robust_assessment),
            "violations": [asdict(v) for v in robust_violations],
            "operations": [asdict(op) for op in robust_schedule.operations],
        },
        "pareto_frontier": [asdict(point) for point in pareto],
        "decision": {
            "action": (
                f"stage {recommended_schedule} schedule for stochastic validation and human approval"
                if recommended_schedule != "NONE"
                else "do not deploy a recovery schedule"
            ),
            "recommended_schedule": recommended_schedule,
            "rationale": (
                "The decision is generated from the synchronized residual twin. Lateness risk weights customer tardiness; "
                f"the bottleneck model identifies {predicted_bottleneck} as the most likely future constraint; a bounded robust counterpart protects processing-time uncertainty."
            ),
            "expected_modeled_impact": expected_impact,
            "uncertainty": {
                "processing_cv_scenario_assumption": processing_cv,
                "bottleneck_probability": bottleneck_scores.get(predicted_bottleneck),
                "robust_uncertainty_set": robust.evidence.uncertainty_set,
                "model_evidence": "all predictive models are synthetically validated; external plant calibration pending",
            },
            "assumptions": list(state.assumptions) + [
                "processing-time robust buffers are derived from the configured variability scenario and bottleneck-risk allocation",
                "box robustness is conservative and does not substitute for stochastic simulation",
            ],
            "trade_offs": [
                "the robust schedule may sacrifice nominal makespan/tardiness to protect bounded processing-time uncertainty",
                "a Pareto frontier is provided because throughput horizon and customer tardiness are competing objectives",
                "machine anomaly flags require human review rather than automatic execution",
            ],
            "human_review_required": review_required,
            "human_review_reasons": review_reasons,
            "human_disposition": "pending",
            "evidence_level": "SYNCHRONIZED TWIN + SYNTHETICALLY VALIDATED AI + VERIFIED OR; EXTERNAL VALIDATION PENDING",
        },
    }
    # Compatibility alias used by the Phase-4 timeline until the Phase-5C UI
    # consumes the richer nominal/robust contract directly.
    result["optimized"] = result["nominal_optimized"]
    return result


def build_twin_future_state_stress_test(
    factory: FactoryModel,
    snapshot: TwinSnapshot,
    risk_model: LatenessRiskBundle,
    cycle_model: CycleTimeBundle,
    bottleneck_model: BottleneckBundle,
    anomaly_model: AnomalyBundle,
    *,
    backend: str = "auto",
    due_factor: float = 1.5,
    time_limit: float = 30.0,
    replications: int = 60,
    base_seed: int = 20260815,
    processing_cv: float = 0.10,
    mtbf: float | None = 120.0,
    mttr: float = 8.0,
    risk_aversion: float = 0.35,
    stressed_machine_id: str | None = None,
    stressed_machine_mtbf: float | None = None,
    stressed_machine_mttr: float | None = None,
    down_machine_recovery: dict[str, float] | None = None,
    wip_cap: int | None = None,
) -> dict:
    decision = build_twin_recovery_decision(
        factory,
        snapshot,
        risk_model,
        cycle_model,
        bottleneck_model,
        anomaly_model,
        backend=backend,
        due_factor=due_factor,
        time_limit=time_limit,
        processing_cv=processing_cv,
        mtbf=mtbf,
        mttr=mttr,
        down_machine_recovery=down_machine_recovery,
    )
    state, problem, _ = _build_twin_problem(factory, snapshot, risk_model, due_factor=due_factor, down_machine_recovery=down_machine_recovery)
    if not state.residual_factory.jobs:
        return {**decision, "stress_test": {"recommended_policy": "NO_ACTION", "summaries": []}}

    nominal_ops = decision["nominal_optimized"]["operations"]
    robust_ops = decision["robust_optimized"]["operations"]
    if not nominal_ops:
        return {**decision, "stress_test": {"recommended_policy": "NO_FEASIBLE_SCHEDULE", "summaries": []}}

    predicted_bottleneck = decision["ai"]["predicted_bottleneck"]
    anomalous = decision["ai"]["anomalous_machines"]
    auto_stress_machine = anomalous[0] if anomalous else predicted_bottleneck
    stress_machine = stressed_machine_id or auto_stress_machine
    known = {m.machine_id for m in state.residual_factory.machines}
    if stress_machine not in known:
        raise ValueError(f"unknown stressed_machine_id {stress_machine}")
    machine_overrides = {
        stress_machine: ReliabilitySpec(
            mtbf=stressed_machine_mtbf if stressed_machine_mtbf is not None else mtbf,
            mttr=stressed_machine_mttr if stressed_machine_mttr is not None else mttr,
        )
    }
    config = SimulationConfig(
        seed=base_seed,
        processing_cv=processing_cv,
        reliability=ReliabilitySpec(mtbf=mtbf, mttr=mttr),
        machine_reliability=machine_overrides,
        wip_cap=wip_cap,
        record_events=False,
    )
    nominal_planned = {row["operation_id"]: row["start"] for row in nominal_ops}
    robust_planned = {row["operation_id"]: row["start"] for row in robust_ops} if robust_ops else nominal_planned
    policies = (
        PolicySpec("SPT_STATUS_QUO", "SPT"),
        PolicySpec("EDD_DISPATCH", "EDD"),
        PolicySpec("AI_RISK_NOMINAL", "PLANNED", nominal_planned),
        PolicySpec("BOX_ROBUST_AI", "PLANNED", robust_planned),
    )
    stress = stress_test_policies(
        problem,
        policies,
        config,
        replications=replications,
        base_seed=base_seed,
        risk_aversion=risk_aversion,
        nominal_solver=decision["nominal_optimized"]["solver"],
        nominal_schedule_violations=tuple(decision["nominal_optimized"]["violations"]),
    )
    decision["stress_test"] = {
        "evidence_label": stress.evidence_label,
        "objective": stress.objective,
        "stressed_machine": stress_machine,
        "stress_machine_source": "operator_override" if stressed_machine_id else ("anomaly_model" if anomalous else "bottleneck_model"),
        "wip_cap": wip_cap,
        "summaries": [asdict(summary) for summary in stress.summaries],
        "stochastic_policy_selection": stress.stochastic_policy_selection,
        "recommended_policy": stress.recommended_policy,
        "rationale": stress.recommendation_rationale,
    }
    decision["decision"]["action"] = f"recommend {stress.recommended_policy} for human approval under the modeled future-state scenario"
    decision["decision"]["uncertainty"]["monte_carlo_replications"] = replications
    decision["decision"]["uncertainty"]["stressed_machine"] = stress_machine
    decision["decision"]["trade_offs"].append("simulation optimization may reject the nominal or box-robust MILP sequence when tail-risk performance is worse")
    return decision


# ---------------------------------------------------------------------------
# Backward-compatible benchmark wrappers retained for deterministic regressions.
# They intentionally operate on a zero-event benchmark state and are not used
# by the synchronized-twin API decision workflow.
# ---------------------------------------------------------------------------

def build_recovery_decision(
    factory: FactoryModel,
    risk_model: LatenessRiskBundle,
    backend: str = "auto",
    due_factor: float = 1.5,
    time_limit: float = 30.0,
) -> dict:
    planning = default_planning_jobs(factory, due_factor=due_factor)
    scored = score_planning_jobs(risk_model, factory, planning)
    problem = ScheduleProblem(factory, scored, ObjectiveWeights(makespan=0.05, tardiness=1.0, risk_tardiness=2.0))
    baseline = _baseline_payload(problem)
    guarded_problem = _with_no_regret_tardiness_guard(problem, baseline)
    optimized = solve_schedule(guarded_problem, backend=backend, time_limit=time_limit, mip_gap=0.0)
    assessment = assess_schedule(guarded_problem, optimized)
    violations = assessment.violations
    return {
        "evidence_labels": {"risk": "PREDICTED — SYNTHETICALLY VALIDATED", "baseline": "CALCULATED HEURISTIC SCHEDULE", "optimized": "OPTIMIZED DECISION"},
        "planning_jobs": [asdict(job) for job in scored],
        "baseline": baseline,
        "optimized": {
            "makespan": optimized.makespan,
            "total_tardiness": sum(optimized.job_tardiness.values()),
            "job_tardiness": optimized.job_tardiness,
            "objective_components": optimized.objective_components,
            "solver": asdict(optimized.evidence),
            "solution_quality": asdict(assessment),
            "violations": [asdict(v) for v in violations],
            "operations": [asdict(op) for op in optimized.operations],
        },
        "recommendation": {
            "action": "use optimized finite-capacity sequence" if assessment.feasible else "do not deploy schedule",
            "rationale": "benchmark regression wrapper; production API uses synchronized-twin decision workflow; the risk-aware schedule is protected by an aggregate-tardiness no-regret guard",
            "assumptions": ["benchmark zero-state regression only", "aggregate total tardiness may not exceed the SPT status-quo baseline"],
        },
    }


def build_future_state_stress_test(
    factory: FactoryModel,
    risk_model: LatenessRiskBundle,
    backend: str = "auto",
    due_factor: float = 1.5,
    time_limit: float = 30.0,
    replications: int = 60,
    base_seed: int = 20260815,
    processing_cv: float = 0.10,
    mtbf: float | None = 120.0,
    mttr: float = 8.0,
    risk_aversion: float = 0.35,
    stressed_machine_id: str | None = None,
    stressed_machine_mtbf: float | None = None,
    stressed_machine_mttr: float | None = None,
) -> dict:
    # Legacy benchmark stress path preserved for Phase 1-4 regression evidence.
    from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, stress_test_policies

    planning = default_planning_jobs(factory, due_factor=due_factor)
    scored = score_planning_jobs(risk_model, factory, planning)
    problem = ScheduleProblem(factory, scored, ObjectiveWeights(makespan=0.05, tardiness=1.0, risk_tardiness=2.0))
    optimized = solve_schedule(problem, backend=backend, time_limit=time_limit, mip_gap=0.0)
    assessment = assess_schedule(problem, optimized)
    violations = assessment.violations
    if not assessment.feasible:
        return {"evidence_label": "OPTIMIZATION NOT READY FOR STRESS TEST", "solver": asdict(optimized.evidence), "violations": [asdict(v) for v in violations], "recommendation": "do not simulate/deploy an infeasible nominal recovery schedule"}
    planned = {op.operation_id: op.start for op in optimized.operations}
    policies = (PolicySpec("SPT_STATUS_QUO", "SPT"), PolicySpec("EDD_DISPATCH", "EDD"), PolicySpec("AI_RISK_OPTIMIZED", "PLANNED", planned))
    machine_overrides = {}
    if stressed_machine_id is not None:
        known_machines = {m.machine_id for m in factory.machines}
        if stressed_machine_id not in known_machines:
            raise ValueError(f"unknown stressed_machine_id {stressed_machine_id}")
        machine_overrides[stressed_machine_id] = ReliabilitySpec(mtbf=stressed_machine_mtbf if stressed_machine_mtbf is not None else mtbf, mttr=stressed_machine_mttr if stressed_machine_mttr is not None else mttr)
    config = SimulationConfig(seed=base_seed, processing_cv=processing_cv, reliability=ReliabilitySpec(mtbf=mtbf, mttr=mttr), machine_reliability=machine_overrides, record_events=False)
    stress = stress_test_policies(problem, policies, config, replications=replications, base_seed=base_seed, risk_aversion=risk_aversion, nominal_solver=asdict(optimized.evidence), nominal_schedule_violations=tuple(asdict(v) for v in violations))
    return {
        "evidence_labels": {"risk": "PREDICTED — SYNTHETICALLY VALIDATED", "nominal_schedule": "OPTIMIZED DECISION", "future_state": stress.evidence_label, "recommendation": "SIMULATION-OPTIMIZED POLICY SELECTION"},
        "scenario": {"due_factor": due_factor, "replications": replications, "base_seed": base_seed, "processing_cv": processing_cv, "mtbf": mtbf, "mttr": mttr, "risk_aversion": risk_aversion, "stressed_machine_id": stressed_machine_id, "stressed_machine_mtbf": stressed_machine_mtbf, "stressed_machine_mttr": stressed_machine_mttr},
        "planning_jobs": [asdict(job) for job in scored],
        "nominal_solver": asdict(optimized.evidence),
        "nominal_schedule": {"makespan": optimized.makespan, "total_tardiness": sum(optimized.job_tardiness.values()), "violations": []},
        "stress_test": {"objective": stress.objective, "summaries": [asdict(summary) for summary in stress.summaries], "recommended_policy": stress.recommended_policy, "rationale": stress.recommendation_rationale},
        "limitations": ["future trajectories use benchmark/synthetic processing and reliability assumptions", "Monte Carlo outcomes are simulated, not observed or realized plant results", "AI risk model is synthetically validated and not plant-calibrated"],
    }
