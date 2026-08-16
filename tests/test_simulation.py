from __future__ import annotations

from pathlib import Path

import pytest

from mdt.ai import heuristic_dispatch, load_bundle, score_planning_jobs
from mdt.optimization import ObjectiveWeights, ScheduleProblem, default_planning_jobs, solve_schedule
from mdt.simulation import (
    PolicySpec,
    ReliabilitySpec,
    SimulationConfig,
    run_monte_carlo,
    simulate,
    validate_simulation,
)


def _problem(ft06, root: Path, due_factor: float = 1.5):
    bundle = load_bundle(root / "artifacts" / "ai" / "lateness_risk.joblib")
    jobs = score_planning_jobs(bundle, ft06, default_planning_jobs(ft06, due_factor))
    return ScheduleProblem(ft06, jobs, ObjectiveWeights(0.05, 1.0, 2.0))


def test_deterministic_des_reproduces_spt_status_quo(ft06, root):
    problem = _problem(ft06, root)
    baseline = heuristic_dispatch(problem, "SPT")
    result = simulate(
        problem,
        PolicySpec("SPT_STATUS_QUO", "SPT"),
        SimulationConfig(seed=7, processing_cv=0.0, reliability=ReliabilitySpec(mtbf=None, mttr=8.0)),
    )
    assert result.metrics.makespan == baseline.makespan == 88.0
    assert result.metrics.total_tardiness == 40.0
    assert result.metrics.total_downtime == 0.0
    assert result.metrics.little_law_error < 1e-12
    assert validate_simulation(problem, result) == []


def test_planned_des_reproduces_nominal_optimized_schedule(ft06, root):
    problem = _problem(ft06, root)
    nominal = solve_schedule(problem, backend="scipy", time_limit=30, mip_gap=0)
    policy = PolicySpec("AI_RISK_OPTIMIZED", "PLANNED", {op.operation_id: op.start for op in nominal.operations})
    result = simulate(
        problem,
        policy,
        SimulationConfig(seed=9, processing_cv=0.0, reliability=ReliabilitySpec(mtbf=None, mttr=8.0)),
    )
    assert result.metrics.makespan == pytest.approx(nominal.makespan, abs=1e-6)
    assert result.metrics.total_tardiness == pytest.approx(sum(nominal.job_tardiness.values()), abs=1e-6)
    assert validate_simulation(problem, result) == []


def test_failures_interrupt_and_resume_without_illegal_processing(ft06, root):
    problem = _problem(ft06, root)
    config = SimulationConfig(seed=123, processing_cv=0.08, reliability=ReliabilitySpec(mtbf=18.0, mttr=4.0))
    result = simulate(problem, PolicySpec("SPT", "SPT"), config)
    assert len(result.downtime_intervals) > 0
    assert any(op.interruptions > 0 for op in result.operations)
    assert any(event.kind == "machine_failed" for event in result.events)
    assert any(event.kind == "machine_repaired" for event in result.events)
    assert validate_simulation(problem, result) == []


def test_simulation_seed_is_exactly_reproducible(ft06, root):
    problem = _problem(ft06, root)
    config = SimulationConfig(seed=42, processing_cv=0.15, reliability=ReliabilitySpec(mtbf=40.0, mttr=6.0))
    first = simulate(problem, PolicySpec("EDD", "EDD"), config)
    second = simulate(problem, PolicySpec("EDD", "EDD"), config)
    assert first == second


def test_policy_spec_rejects_incomplete_planned_schedule(ft06, root):
    problem = _problem(ft06, root)
    with pytest.raises(ValueError, match="every operation"):
        simulate(problem, PolicySpec("bad", "PLANNED", {"J0-O0": 0.0}), SimulationConfig())


def test_monte_carlo_reproducibility_and_tail_metrics(ft06, root):
    problem = _problem(ft06, root)
    policy = PolicySpec("SPT", "SPT")
    config = SimulationConfig(processing_cv=0.10, reliability=ReliabilitySpec(mtbf=80.0, mttr=5.0), record_events=False)
    first = run_monte_carlo(problem, policy, config, replications=8, base_seed=100, risk_aversion=0.4)
    second = run_monte_carlo(problem, policy, config, replications=8, base_seed=100, risk_aversion=0.4)
    assert first == second
    assert first.cvar95_total_tardiness >= first.p95_total_tardiness - 1e-9
    assert first.p95_makespan >= first.mean_makespan * 0.8
    assert first.tardiness_mean_ci95_half_width >= 0
