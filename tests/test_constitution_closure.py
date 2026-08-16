from pathlib import Path

import numpy as np
import pytest

from mdt.ai import load_anomaly, load_bottleneck, load_bundle, load_cycle_time
from mdt.decision import build_twin_recovery_decision
from mdt.domain import EventType, ManufacturingEvent
from mdt.ie import (
    capacity_plan,
    drum_buffer_rope_plan,
    individuals_mr,
    oee,
    process_cycle_efficiency,
    takt_time,
    two_level_factorial_effects,
)
from mdt.optimization import (
    BoxRobustnessSpec,
    ObjectiveWeights,
    ScheduleProblem,
    default_planning_jobs,
    pareto_schedule_frontier,
    solve_box_robust_schedule,
    assess_schedule,
    validate_schedule,
)
from mdt.planning import PlanningStateNotReady, planning_state_from_twin
from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, simulate
from mdt.twin import TwinEngine


def _bundles(root: Path):
    art = root / "artifacts" / "ai"
    return (
        load_bundle(art / "lateness_risk.joblib"),
        load_cycle_time(art / "cycle_time.joblib"),
        load_bottleneck(art / "bottleneck.joblib"),
        load_anomaly(art / "anomaly.joblib"),
    )


def test_synchronized_twin_residual_planning_freezes_running_work(ft06):
    twin = TwinEngine(ft06)
    twin.apply(ManufacturingEvent("r0", EventType.JOB_RELEASED, 0.0, job_id="J0"))
    twin.apply(ManufacturingEvent("s0", EventType.OPERATION_STARTED, 0.0, operation_id="J0-O0", machine_id="M2"))
    twin.apply(ManufacturingEvent("r1", EventType.JOB_RELEASED, 0.5, job_id="J1"))
    state = planning_state_from_twin(ft06, twin.snapshot(), due_factor=1.5)
    assert state.current_time == 0.5
    assert state.source_event_count == 3
    assert state.schedulable_operations == 35
    assert [op.operation_id for op in state.frozen_operations] == ["J0-O0"]
    assert state.machine_available_from["M2"] == 1.0
    j0 = state.residual_factory.job("J0")
    assert j0.operations[0].operation_id == "J0-O1"
    assert state.planning_jobs[0].release_time >= 1.0


def test_planning_refuses_unknown_down_machine_recovery(ft06):
    twin = TwinEngine(ft06)
    twin.apply(ManufacturingEvent("d", EventType.MACHINE_DOWN, 1.0, machine_id="M5"))
    with pytest.raises(PlanningStateNotReady):
        planning_state_from_twin(ft06, twin.snapshot(), due_factor=1.5)
    state = planning_state_from_twin(ft06, twin.snapshot(), due_factor=1.5, down_machine_recovery={"M5": 6.0})
    assert state.machine_available_from["M5"] == 6.0


def test_box_robust_schedule_and_pareto_are_feasible(ft06):
    jobs = default_planning_jobs(ft06, due_factor=2.0)
    problem = ScheduleProblem(ft06, jobs, ObjectiveWeights(0.05, 1.0, 0.0))
    robust = solve_box_robust_schedule(problem, BoxRobustnessSpec(0.10, {"M5": 0.20}), backend="scipy", time_limit=8.0)
    robust_assessment = assess_schedule(robust.robust_problem, robust.schedule)
    assert robust_assessment.feasible is True
    assert robust.evidence.feasible_incumbent is True
    assert robust.evidence.robust_violations == 0
    assert validate_schedule(robust.robust_problem, robust.schedule) == []
    assert robust.schedule.makespan >= 55.0
    frontier = pareto_schedule_frontier(
        problem, backend="scipy", risk_tardiness_weight=0.0,
        weight_grid=((1.0, 0.0), (0.05, 1.0), (0.0, 1.0)), time_limit=5.0,
    )
    assert len(frontier) >= 1
    for point in frontier:
        assert point.status in {"OPTIMAL", "FEASIBLE", "TIME_LIMIT"}
        assert point.optimality_proven is (point.status == "OPTIMAL")



def test_pareto_keeps_validated_time_limit_incumbent(ft06, monkeypatch):
    """Windows/slow-solver regression: a time-limit incumbent is feasible evidence.

    The Pareto workbench must not become empty merely because a solver reaches
    its time limit after finding a valid schedule. The point remains explicitly
    labeled TIME_LIMIT and does not claim proven optimality.
    """
    from dataclasses import replace
    import mdt.optimization.robust as robust_module
    from mdt.optimization import solve_schedule

    jobs = default_planning_jobs(ft06, due_factor=2.0)
    problem = ScheduleProblem(ft06, jobs, ObjectiveWeights(0.05, 1.0, 0.0))
    solved = solve_schedule(problem, backend="scipy", time_limit=20.0)
    assert solved.operations
    time_limited = replace(
        solved,
        evidence=replace(solved.evidence, status="TIME_LIMIT", raw_status="synthetic Windows time-limit incumbent"),
    )
    monkeypatch.setattr(robust_module, "solve_schedule", lambda *args, **kwargs: time_limited)

    frontier = pareto_schedule_frontier(
        problem,
        backend="scipy",
        weight_grid=((0.05, 1.0),),
        risk_tardiness_weight=0.0,
        time_limit=0.1,
    )
    assert len(frontier) == 1
    assert frontier[0].status == "TIME_LIMIT"
    assert frontier[0].optimality_proven is False


def test_ie_math_and_quality_reference_cases(ft06):
    assert takt_time(480.0, 240.0) == 2.0
    assert oee(0.90, 0.95, 0.99) == pytest.approx(0.84645)
    assert process_cycle_efficiency(10.0, 50.0) == 0.2
    cap = capacity_plan(ft06, horizon=100.0, availability_by_machine={"M5": 0.9})
    m5 = next(row for row in cap if row.machine_id == "M5")
    assert m5.workload == 43.0
    assert m5.effective_available_time == 90.0
    jobs = default_planning_jobs(ft06, 2.0)
    dbr = drum_buffer_rope_plan(ft06, jobs, buffer_time=5.0)
    assert dbr.constraint_machine_id == "M5"
    assert len(dbr.jobs) == 6
    assert all(row.rope_release_time >= 0 for row in dbr.jobs)

    spc = individuals_mr([10, 11, 10, 9, 10, 25])
    assert spc.center_line == pytest.approx(12.5)
    assert spc.moving_range_bar > 0
    assert 5 in spc.out_of_control_indices

    rows = []
    for a in (-1.0, 1.0):
        for b in (-1.0, 1.0):
            rows.append({"A": a, "B": b, "y": 10 + 2*a + 3*b + 4*a*b})
    effects = {row.term: row.effect for row in two_level_factorial_effects(rows, "y")}
    assert effects["A"] == pytest.approx(4.0)
    assert effects["B"] == pytest.approx(6.0)
    assert effects["A*B"] == pytest.approx(8.0)


def test_conwip_des_never_exceeds_wip_cap(ft06):
    jobs = default_planning_jobs(ft06, due_factor=10.0)
    problem = ScheduleProblem(ft06, jobs)
    result = simulate(
        problem,
        PolicySpec("SPT_CONWIP", "SPT"),
        SimulationConfig(
            seed=77,
            processing_cv=0.0,
            reliability=ReliabilitySpec(mtbf=None, mttr=1.0),
            wip_cap=2,
            record_events=True,
        ),
    )
    wip = 0
    max_wip = 0
    for event in result.events:
        if event.kind == "job_released":
            wip += 1
            max_wip = max(max_wip, wip)
        elif event.kind == "job_completed":
            wip -= 1
    assert max_wip <= 2
    assert wip == 0


def test_operational_ai_artifacts_have_distinct_validated_tasks(root):
    _, cycle, bottleneck, anomaly = _bundles(root)
    assert cycle.metadata["evidence_label"] == "SYNTHETIC VALIDATION"
    assert cycle.metadata["test_metrics"]["mae"] < 10.0
    assert bottleneck.metadata["test_metrics"]["top1_accuracy"] >= 0.60
    assert anomaly.metadata["evidence_label"] == "SYNTHETIC VALIDATION"
    assert 0.0 < anomaly.threshold_raw


def test_twin_decision_excludes_completed_work_and_has_full_contract(ft06, root):
    risk, cycle, bottleneck, anomaly = _bundles(root)
    twin = TwinEngine(ft06)
    twin.apply(ManufacturingEvent("r0", EventType.JOB_RELEASED, 0.0, job_id="J0"))
    twin.apply(ManufacturingEvent("s0", EventType.OPERATION_STARTED, 0.0, operation_id="J0-O0", machine_id="M2"))
    twin.apply(ManufacturingEvent("c0", EventType.OPERATION_COMPLETED, 1.0, operation_id="J0-O0", machine_id="M2"))
    result = build_twin_recovery_decision(
        ft06, twin.snapshot(), risk, cycle, bottleneck, anomaly,
        backend="scipy", due_factor=1.5, time_limit=10.0,
    )
    scheduled_ids = {row["operation_id"] for row in result["nominal_optimized"]["operations"]}
    assert "J0-O0" not in scheduled_ids
    assert result["planning_state"]["completed_operations"] == 1
    assert result["planning_state"]["twin_event_count"] == 3
    contract = result["decision"]
    for key in ("action", "rationale", "expected_modeled_impact", "uncertainty", "assumptions", "trade_offs", "human_review_required", "evidence_level"):
        assert key in contract
    assert result["nominal_optimized"]["violations"] == []
    assert result["robust_optimized"]["violations"] == []
    assert len(result["pareto_frontier"]) >= 1


def test_planned_sequence_with_conwip_does_not_deadlock():
    from mdt.ai import load_bundle, score_planning_jobs
    from mdt.data import load_orlib_instance
    from mdt.optimization import ObjectiveWeights, ScheduleProblem, default_planning_jobs, solve_schedule
    from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, simulate
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    model = load_orlib_instance(root / "data" / "external" / "orlib" / "jobshop1.txt", "ft06")
    risk = load_bundle(root / "artifacts" / "ai" / "lateness_risk.joblib")
    jobs = score_planning_jobs(risk, model, default_planning_jobs(model, 1.5))
    problem = ScheduleProblem(model, jobs, ObjectiveWeights(0.05, 1.0, 2.0))
    solved = solve_schedule(problem, backend="scipy", time_limit=10.0)
    planned = PolicySpec(
        "PLANNED_CONWIP",
        "PLANNED",
        planned_start={op.operation_id: op.start for op in solved.operations},
    )
    result = simulate(
        problem,
        planned,
        SimulationConfig(
            seed=20260815,
            processing_cv=0.05,
            reliability=ReliabilitySpec(mtbf=80.0, mttr=5.0),
            wip_cap=3,
        ),
    )
    assert len(result.job_completion) == len(model.jobs)
    assert result.metrics.makespan > 0


def test_scenario_stochastic_policy_milp_matches_enumeration():
    from mdt.optimization import select_policy_stochastic

    losses = {
        "LOW_MEAN_BAD_TAIL": (1.0, 1.0, 1.0, 20.0),
        "ROBUST": (4.0, 4.0, 4.0, 4.0),
        "WEAK": (8.0, 8.0, 8.0, 8.0),
    }
    result = select_policy_stochastic(losses, alpha=0.75, risk_aversion=1.0)
    assert result.evidence.status == "OPTIMAL"
    assert result.selected_policy == "ROBUST"
    assert result.selected_policy == result.evidence.oracle_selected_policy
    assert result.evidence.mip_gap == 0.0


def test_solver_assessment_accepts_valid_time_limit_incumbent(ft06):
    """Systemic Windows regression: termination status is not feasibility."""
    from dataclasses import replace
    from mdt.optimization import ObjectiveWeights, ScheduleProblem, assess_schedule, default_planning_jobs, solve_schedule

    problem = ScheduleProblem(ft06, default_planning_jobs(ft06, 2.0), ObjectiveWeights(0.05, 1.0, 0.0))
    solved = solve_schedule(problem, backend="scipy", time_limit=20.0)
    assert solved.operations
    time_limited = replace(
        solved,
        evidence=replace(solved.evidence, status="TIME_LIMIT", raw_status="synthetic complete incumbent at Windows time limit"),
    )
    assessment = assess_schedule(problem, time_limited)
    assert assessment.termination_status == "TIME_LIMIT"
    assert assessment.has_incumbent is True
    assert assessment.complete_incumbent is True
    assert assessment.feasible is True
    assert assessment.optimality_proven is False
    assert assessment.quality == "FEASIBLE_INCUMBENT"
    assert assessment.violations == ()


def test_operational_paths_do_not_reimplement_solver_status_policy(root):
    """Prevent another one-by-one status bug across decision/API/acceptance paths."""
    paths = (
        root / "src/mdt/decision.py",
        root / "src/mdt/api/main.py",
        root / "scripts/v1_diagnostics.py",
        root / "scripts/windows_v1_acceptance.py",
    )
    forbidden = (
        'status in {"OPTIMAL", "FEASIBLE"}',
        'status not in {"OPTIMAL", "FEASIBLE"}',
        '["status"] in {"OPTIMAL", "FEASIBLE"}',
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} reimplements solver feasibility policy: {token}"
