from mdt.ai import load_bundle
from mdt.decision import build_future_state_stress_test


def test_ai_ie_or_simulation_stress_test_chain(ft06, root):
    bundle = load_bundle(root / "artifacts" / "ai" / "lateness_risk.joblib")
    result = build_future_state_stress_test(
        ft06,
        bundle,
        backend="scipy",
        due_factor=1.5,
        replications=8,
        base_seed=2026,
        processing_cv=0.10,
        mtbf=80.0,
        mttr=5.0,
        risk_aversion=0.35,
    )
    assert result["evidence_labels"]["future_state"].startswith("SIMULATED")
    assert result["nominal_solver"]["status"] == "OPTIMAL"
    assert result["nominal_schedule"]["violations"] == []
    summaries = result["stress_test"]["summaries"]
    assert {row["policy"] for row in summaries} == {"SPT_STATUS_QUO", "EDD_DISPATCH", "AI_RISK_OPTIMIZED"}
    assert result["stress_test"]["recommended_policy"] in {row["policy"] for row in summaries}
    assert all(row["replications"] == 8 for row in summaries)


def test_machine_specific_reliability_override_is_isolated(ft06, root):
    from mdt.ai import load_bundle, score_planning_jobs
    from mdt.optimization import ObjectiveWeights, ScheduleProblem, default_planning_jobs
    from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, simulate, validate_simulation

    bundle = load_bundle(root / "artifacts" / "ai" / "lateness_risk.joblib")
    jobs = score_planning_jobs(bundle, ft06, default_planning_jobs(ft06, 1.5))
    problem = ScheduleProblem(ft06, jobs, ObjectiveWeights(0.05, 1.0, 2.0))
    result = simulate(
        problem,
        PolicySpec("EDD_M5_STRESS", "EDD"),
        SimulationConfig(
            seed=20260815,
            processing_cv=0.0,
            reliability=ReliabilitySpec(mtbf=None, mttr=5.0),
            machine_reliability={"M5": ReliabilitySpec(mtbf=2.0, mttr=3.0)},
        ),
    )
    assert result.machine_downtime["M5"] > 0
    assert all(value == 0 for machine, value in result.machine_downtime.items() if machine != "M5")
    assert validate_simulation(problem, result) == []
