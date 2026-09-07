from __future__ import annotations

import json
import subprocess
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mdt import __version__
from mdt.ai import load_anomaly, load_bottleneck, load_bundle, load_cycle_time, score_planning_jobs
from mdt.data import load_orlib_instance
from mdt.decision import build_recovery_decision, build_twin_future_state_stress_test
from mdt.domain import EventType, ManufacturingEvent
from mdt.optimization import ObjectiveWeights, ScheduleProblem, gurobi_available, solve_schedule, validate_schedule
from mdt.planning import planning_state_from_twin
from mdt.twin import TwinEngine
from mdt.trust import TrustDecision, assess_trust
from mdt.trust_validation import validation_report


def main() -> None:
    root = ROOT
    native_env = {**__import__("os").environ, "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    subprocess.run([sys.executable, "-I", "scripts/windows_native_runtime_smoke.py"], cwd=root, check=True, env=native_env)
    subprocess.run([sys.executable, "scripts/windows_trust_rh_signature_acceptance.py"], cwd=root, check=True, env={**__import__("os").environ, "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    subprocess.run([sys.executable, "scripts/trust_rh_evidence.py"], cwd=root, check=True, env={**__import__("os").environ, "PYTHONPATH": str(root / "src")})
    if __version__ != "1.0.0":
        raise SystemExit(f"WINDOWS_V1_ENGINEERING_ACCEPTANCE=FAIL: version {__version__} != 1.0.0")
    if not gurobi_available():
        raise SystemExit("WINDOWS_V1_ENGINEERING_ACCEPTANCE=FAIL: gurobipy is not importable")
    factory = load_orlib_instance(root / "data/external/orlib/jobshop1.txt", "ft06")
    art = root / "artifacts/ai"
    risk = load_bundle(art / "lateness_risk.joblib")
    cycle = load_cycle_time(art / "cycle_time.joblib")
    bottleneck = load_bottleneck(art / "bottleneck.joblib")
    anomaly = load_anomaly(art / "anomaly.joblib")

    # Cross-platform regression for the 0.9.2 no-regret service guard.
    # Both solvers must optimize the declared risk-aware objective without
    # increasing aggregate tardiness above the explicit SPT baseline.
    guarded_gurobi = build_recovery_decision(factory, risk, backend="gurobi", due_factor=1.5, time_limit=30.0)
    guarded_highs = build_recovery_decision(factory, risk, backend="scipy", due_factor=1.5, time_limit=30.0)

    twin = TwinEngine(factory)
    snapshot = twin.replay([
        ManufacturingEvent("w-r0", EventType.JOB_RELEASED, 0.0, job_id="J0"),
        ManufacturingEvent("w-s0", EventType.OPERATION_STARTED, 0.0, operation_id="J0-O0", machine_id="M2"),
        ManufacturingEvent("w-c0", EventType.OPERATION_COMPLETED, 1.0, operation_id="J0-O0", machine_id="M2"),
        ManufacturingEvent("w-r1", EventType.JOB_RELEASED, 1.0, job_id="J1"),
        ManufacturingEvent("w-s1", EventType.OPERATION_STARTED, 1.0, operation_id="J1-O0", machine_id="M1"),
    ])
    state = planning_state_from_twin(factory, snapshot, due_factor=1.5)
    scored = score_planning_jobs(risk, state.residual_factory, state.planning_jobs)
    problem = ScheduleProblem(
        state.residual_factory,
        scored,
        ObjectiveWeights(0.05, 1.0, 2.0),
        current_time=state.current_time,
        machine_available_from=state.machine_available_from,
    )
    gurobi = solve_schedule(problem, backend="gurobi", time_limit=30, mip_gap=0.0)
    oracle = solve_schedule(problem, backend="scipy", time_limit=30, mip_gap=0.0)
    violations = validate_schedule(problem, gurobi)
    if gurobi.evidence.status != "OPTIMAL" or oracle.evidence.status != "OPTIMAL" or violations:
        raise SystemExit("WINDOWS_V1_ENGINEERING_ACCEPTANCE=FAIL: synchronized residual schedule did not solve/validate")
    if abs(float(gurobi.evidence.objective_value or 0) - float(oracle.evidence.objective_value or 0)) > 1e-4:
        raise SystemExit("WINDOWS_V1_ENGINEERING_ACCEPTANCE=FAIL: Gurobi and HiGHS residual objectives disagree")

    stress = build_twin_future_state_stress_test(
        factory,
        snapshot,
        risk,
        cycle,
        bottleneck,
        anomaly,
        backend="gurobi",
        due_factor=1.5,
        time_limit=20.0,
        replications=4,
        base_seed=20260815,
        processing_cv=0.10,
        mtbf=80.0,
        mttr=5.0,
        risk_aversion=0.35,
        wip_cap=3,
    )
    selection = stress["stress_test"]["stochastic_policy_selection"]
    pareto_points = stress["pareto_frontier"]
    pareto_status_truthful = all(
        point.get("status") in {"OPTIMAL", "FEASIBLE", "TIME_LIMIT"}
        and bool(point.get("optimality_proven")) == (point.get("status") == "OPTIMAL")
        for point in pareto_points
    )
    pareto_nondominated = all(
        not any(
            other is not point
            and other["makespan"] <= point["makespan"] + 1e-7
            and other["total_tardiness"] <= point["total_tardiness"] + 1e-7
            and other["risk_weighted_tardiness"] <= point["risk_weighted_tardiness"] + 1e-7
            and (
                other["makespan"] < point["makespan"] - 1e-7
                or other["total_tardiness"] < point["total_tardiness"] - 1e-7
                or other["risk_weighted_tardiness"] < point["risk_weighted_tardiness"] - 1e-7
            )
            for other in pareto_points
        )
        for point in pareto_points
    )
    trust_evidence = {"lateness": True, "cycle_time": True, "bottleneck": True, "anomaly": True}
    trust_authorized = assess_trust(
        snapshot=snapshot, factory_model=factory, ledger_events=[object()] * snapshot.event_count,
        model_evidence=trust_evidence, reference_time=snapshot.timestamp,
    )
    trust_review = assess_trust(
        snapshot=snapshot, factory_model=factory, ledger_events=[object()] * snapshot.event_count,
        model_evidence=trust_evidence, reference_time=snapshot.timestamp + 50.0,
    )
    trust_blocked = assess_trust(
        snapshot=snapshot, factory_model=factory, ledger_events=[object()] * max(0, snapshot.event_count - 1),
        model_evidence=trust_evidence, reference_time=snapshot.timestamp,
    )
    trust_validation = validation_report()

    checks = {
        "trust_rh_authorized_path": trust_authorized.decision == TrustDecision.AUTHORIZED,
        "trust_rh_review_path": trust_review.decision == TrustDecision.HUMAN_REVIEW,
        "trust_rh_blocked_path": trust_blocked.decision == TrustDecision.BLOCKED,
        "trust_rh_canonical_validation": trust_validation["canonical_passed"] == trust_validation["canonical_total"] == 7,
        "trust_rh_sensitivity_96": trust_validation["sensitivity_cases"] == 96,
        "gurobi_no_regret_tardiness": guarded_gurobi["optimized"]["total_tardiness"] <= guarded_gurobi["baseline"]["total_tardiness"] + 1e-6,
        "highs_no_regret_tardiness": guarded_highs["optimized"]["total_tardiness"] <= guarded_highs["baseline"]["total_tardiness"] + 1e-6,
        "gurobi_declared_objective_improves": guarded_gurobi["optimized"]["solver"]["objective_value"] <= guarded_gurobi["baseline"]["objective_value"] + 1e-6,
        "highs_declared_objective_improves": guarded_highs["optimized"]["solver"]["objective_value"] <= guarded_highs["baseline"]["objective_value"] + 1e-6,
        "guarded_cross_solver_objective_agreement": abs(float(guarded_gurobi["optimized"]["solver"]["objective_value"] or 0) - float(guarded_highs["optimized"]["solver"]["objective_value"] or 0)) <= 1e-4,
        "five_event_twin": stress["planning_state"]["twin_event_count"] == 5,
        "completed_removed": all(op["operation_id"] != "J0-O0" for op in stress["nominal_optimized"]["operations"]),
        "running_frozen": any(op["operation_id"] == "J1-O0" for op in stress["planning_state"]["frozen_operations"]),
        "gurobi_nominal_optimal": stress["nominal_optimized"]["solver"]["backend"] == "gurobi" and stress["nominal_optimized"]["solver"]["status"] == "OPTIMAL",
        "gurobi_robust_feasible": stress["robust_optimized"]["solver"]["backend"] == "gurobi" and bool(stress["robust_optimized"]["solution_quality"]["feasible"]),
        "robust_status_truthful": stress["robust_optimized"]["solution_quality"]["termination_status"] == stress["robust_optimized"]["solver"]["status"],
        "robust_optimality_truthful": bool(stress["robust_optimized"]["solution_quality"]["optimality_proven"]) == (stress["robust_optimized"]["solver"]["status"] == "OPTIMAL"),
        "pareto_present": len(pareto_points) >= 1,
        "pareto_status_truthful": pareto_status_truthful,
        "pareto_nondominated_3d": pareto_nondominated,
        "four_policies": len(stress["stress_test"]["summaries"]) == 4 and {row["policy"] for row in stress["stress_test"]["summaries"]} == {"SPT_STATUS_QUO", "EDD_DISPATCH", "AI_RISK_NOMINAL", "BOX_ROBUST_AI"},
        "complete_decision_contract": all(key in stress["decision"] for key in ("action", "rationale", "expected_modeled_impact", "uncertainty", "assumptions", "trade_offs", "human_review_required", "evidence_level")),
        "stochastic_milp_optimal": selection["solver"]["status"] == "OPTIMAL",
        "stochastic_oracle_agrees": selection["selected_policy"] == selection["solver"]["oracle_selected_policy"],
        "gurobi_highs_residual_agreement": abs(float(gurobi.evidence.objective_value or 0) - float(oracle.evidence.objective_value or 0)) <= 1e-4,
    }
    evidence = {
        "no_regret_guard": {
            "baseline_total_tardiness": guarded_gurobi["baseline"]["total_tardiness"],
            "gurobi_total_tardiness": guarded_gurobi["optimized"]["total_tardiness"],
            "highs_total_tardiness": guarded_highs["optimized"]["total_tardiness"],
            "gurobi_objective": guarded_gurobi["optimized"]["solver"]["objective_value"],
            "highs_objective": guarded_highs["optimized"]["solver"]["objective_value"],
        },
        "twin_state_id": stress["planning_state"]["twin_state_id"],
        "gurobi_residual": {
            "status": gurobi.evidence.status,
            "objective": gurobi.evidence.objective_value,
            "best_bound": gurobi.evidence.best_bound,
            "mip_gap": gurobi.evidence.mip_gap,
        },
        "highs_residual": {"status": oracle.evidence.status, "objective": oracle.evidence.objective_value},
        "box_robust_solver": stress["robust_optimized"]["solver"],
        "pareto_frontier": pareto_points,
        "stochastic_policy_selection": selection,
        "recommended_policy": stress["stress_test"]["recommended_policy"],
        "trust_rh": {
            "authorized": trust_authorized.to_dict(),
            "review": trust_review.to_dict(),
            "blocked": trust_blocked.to_dict(),
            "validation": trust_validation,
        },
        "checks": checks,
    }
    print(json.dumps(evidence, indent=2))
    if not all(checks.values()):
        raise SystemExit(f"WINDOWS_V1_ENGINEERING_ACCEPTANCE=FAIL: {[k for k,v in checks.items() if not v]}")
    print("WINDOWS_V1_ENGINEERING_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
