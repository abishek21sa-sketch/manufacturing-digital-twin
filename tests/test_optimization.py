import pytest

from mdt.optimization import ObjectiveWeights, ScheduleProblem, default_planning_jobs, solve_schedule, validate_schedule


def test_ft06_makespan_matches_exact_reference(ft06):
    problem = ScheduleProblem(ft06, default_planning_jobs(ft06, 100.0), ObjectiveWeights(makespan=1.0))
    result = solve_schedule(problem, backend="scipy", time_limit=30.0, mip_gap=0.0)
    assert result.evidence.status == "OPTIMAL"
    assert result.makespan == pytest.approx(55.0, abs=1e-4)
    assert result.evidence.best_bound == pytest.approx(55.0, abs=1e-4)
    assert result.evidence.mip_gap == pytest.approx(0.0, abs=1e-9)
    assert validate_schedule(problem, result) == []


def test_risk_aware_schedule_is_feasible_and_improves_declared_objective(ft06, root):
    from mdt.ai import load_bundle, score_planning_jobs
    from mdt.ai.scenarios import heuristic_dispatch
    bundle = load_bundle(root / "artifacts/ai/lateness_risk.joblib")
    jobs = score_planning_jobs(bundle, ft06, default_planning_jobs(ft06, 1.5))
    problem = ScheduleProblem(ft06, jobs, ObjectiveWeights(makespan=.05, tardiness=1.0, risk_tardiness=2.0))
    baseline = heuristic_dispatch(problem, "SPT")
    baseline_tard = {j.job_id: max(0, baseline.completion[j.job_id] - j.due_time) for j in jobs}
    baseline_objective = (
        problem.objective.makespan * baseline.makespan
        + problem.objective.tardiness * sum(baseline_tard.values())
        + problem.objective.risk_tardiness * sum(problem.planning_job(j).risk_score * t for j, t in baseline_tard.items())
    )
    result = solve_schedule(problem, backend="scipy", time_limit=30, mip_gap=0)
    assert validate_schedule(problem, result) == []
    assert result.evidence.status == "OPTIMAL"
    assert result.evidence.objective_value <= baseline_objective + 1e-6


def test_invalid_objective_rejected(ft06):
    problem = ScheduleProblem(ft06, default_planning_jobs(ft06), ObjectiveWeights(0, 0, 0))
    with pytest.raises(ValueError):
        solve_schedule(problem, backend="scipy")


def test_unknown_backend_rejected(ft06):
    problem = ScheduleProblem(ft06, default_planning_jobs(ft06))
    with pytest.raises(ValueError):
        solve_schedule(problem, backend="bogus")


def test_total_tardiness_no_regret_guard_is_enforced(ft06, root):
    from dataclasses import replace
    from mdt.ai import load_bundle, score_planning_jobs
    from mdt.optimization import default_planning_jobs

    risk = load_bundle(root / "artifacts/ai/lateness_risk.joblib")
    planning = default_planning_jobs(ft06, 1.5)
    scored = score_planning_jobs(risk, ft06, planning)
    unconstrained = ScheduleProblem(ft06, scored, ObjectiveWeights(0.05, 1.0, 2.0))
    guarded = replace(unconstrained, max_total_tardiness=40.0)
    result = solve_schedule(guarded, backend="scipy", time_limit=30, mip_gap=0.0)
    assert result.evidence.status == "OPTIMAL"
    assert sum(result.job_tardiness.values()) <= 40.0 + 1e-6
    assert validate_schedule(guarded, result) == []
