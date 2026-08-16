from __future__ import annotations

from dataclasses import replace
import math

import numpy as np

from mdt.optimization.model import ScheduleProblem
from mdt.optimization.stochastic import select_policy_stochastic
from .engine import simulate
from .model import MonteCarloSummary, PolicySpec, SimulationConfig, StressTestResult
from .validation import validate_simulation


def _cvar(values: np.ndarray, alpha: float = 0.95) -> float:
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    threshold = float(np.quantile(values, alpha))
    tail = values[values >= threshold - 1e-12]
    return float(tail.mean()) if len(tail) else threshold


def run_monte_carlo(
    problem: ScheduleProblem,
    policy: PolicySpec,
    config: SimulationConfig,
    replications: int = 60,
    base_seed: int = 20260815,
    risk_aversion: float = 0.35,
) -> MonteCarloSummary:
    if replications < 2:
        raise ValueError("replications must be at least 2")
    if risk_aversion < 0:
        raise ValueError("risk_aversion must be non-negative")
    rows = []
    seeds = tuple(base_seed + i for i in range(replications))
    for seed in seeds:
        result = simulate(problem, policy, replace(config, seed=seed, record_events=False))
        violations = validate_simulation(problem, result)
        if violations:
            raise RuntimeError(f"simulation invariant violation for seed {seed}: {violations[0]}")
        rows.append(result.metrics)

    makespan = np.asarray([r.makespan for r in rows], dtype=float)
    tardiness = np.asarray([r.total_tardiness for r in rows], dtype=float)
    service = np.asarray([r.service_level for r in rows], dtype=float)
    flow = np.asarray([r.mean_flow_time for r in rows], dtype=float)
    wip = np.asarray([r.average_wip for r in rows], dtype=float)
    util = np.asarray([r.mean_machine_utilization for r in rows], dtype=float)
    cvar95 = _cvar(tardiness, 0.95)
    mean_tardiness = float(tardiness.mean())
    mean_makespan = float(makespan.mean())
    # Robust objective prioritizes customer lateness while retaining a modest
    # throughput-horizon penalty. This is simulation optimization, not a MILP objective.
    robust_score = mean_tardiness + risk_aversion * cvar95 + 0.05 * mean_makespan
    z = 1.96
    return MonteCarloSummary(
        policy=policy.name,
        replications=replications,
        base_seed=base_seed,
        mean_makespan=mean_makespan,
        p95_makespan=float(np.quantile(makespan, 0.95)),
        mean_total_tardiness=mean_tardiness,
        p95_total_tardiness=float(np.quantile(tardiness, 0.95)),
        cvar95_total_tardiness=cvar95,
        mean_service_level=float(service.mean()),
        probability_any_late=float(np.mean(tardiness > 1e-9)),
        mean_flow_time=float(flow.mean()),
        mean_average_wip=float(wip.mean()),
        mean_machine_utilization=float(util.mean()),
        makespan_mean_ci95_half_width=float(z * makespan.std(ddof=1) / math.sqrt(replications)),
        tardiness_mean_ci95_half_width=float(z * tardiness.std(ddof=1) / math.sqrt(replications)),
        robust_score=float(robust_score),
        seeds=seeds,
        total_tardiness_scenarios=tuple(float(v) for v in tardiness),
    )


def stress_test_policies(
    problem: ScheduleProblem,
    policies: tuple[PolicySpec, ...],
    config: SimulationConfig,
    replications: int = 60,
    base_seed: int = 20260815,
    risk_aversion: float = 0.35,
    nominal_solver: dict[str, object] | None = None,
    nominal_schedule_violations: tuple[dict[str, str], ...] = (),
) -> StressTestResult:
    if len(policies) < 2:
        raise ValueError("stress testing requires at least two candidate policies")
    summaries = tuple(
        run_monte_carlo(problem, policy, config, replications, base_seed, risk_aversion)
        for policy in policies
    )
    best = min(summaries, key=lambda s: (s.robust_score, s.mean_total_tardiness, s.mean_makespan, s.policy))
    stochastic = select_policy_stochastic(
        {s.policy: s.total_tardiness_scenarios for s in summaries},
        alpha=0.95,
        risk_aversion=risk_aversion,
        time_limit=10.0,
    )
    selected_policy = stochastic.selected_policy or best.policy
    stochastic_payload = {
        "selected_policy": stochastic.selected_policy,
        "expected_total_tardiness": stochastic.expected_loss,
        "cvar95_total_tardiness": stochastic.cvar_loss,
        "objective_value": stochastic.objective_value,
        "solver": {
            "backend": stochastic.evidence.backend,
            "status": stochastic.evidence.status,
            "best_bound": stochastic.evidence.best_bound,
            "mip_gap": stochastic.evidence.mip_gap,
            "solve_time_seconds": stochastic.evidence.solve_time_seconds,
            "oracle_selected_policy": stochastic.evidence.oracle_selected_policy,
            "oracle_objective": stochastic.evidence.oracle_objective,
        },
    }
    return StressTestResult(
        evidence_label="SIMULATED FUTURE-STATE STRESS TEST — SYNTHETIC/BENCHMARK INPUTS",
        objective="scenario-based stochastic policy MILP: expected total tardiness + risk_aversion * CVaR95(total tardiness)",
        summaries=summaries,
        recommended_policy=selected_policy,
        recommendation_rationale=(
            f"{selected_policy} is selected by a scenario-based CVaR stochastic policy MILP over "
            f"{replications} common-random-number future-state replications. The MILP is independently verified by exact policy enumeration; "
            "this remains a simulated/modelled recommendation, not realized plant benefit."
        ),
        nominal_solver=nominal_solver or {},
        nominal_schedule_violations=nominal_schedule_violations,
        stochastic_policy_selection=stochastic_payload,
    )
