from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import tempfile

from mdt import __version__
from mdt.ai import load_anomaly, load_bottleneck, load_bundle, load_cycle_time, score_planning_jobs
from mdt.data import load_orlib_instance
from mdt.decision import build_twin_future_state_stress_test, build_twin_recovery_decision
from mdt.domain import EventType, HumanDisposition, ManufacturingEvent
from mdt.ie import (
    capacity_plan,
    drum_buffer_rope_plan,
    individuals_mr,
    jit_latest_release,
    oee,
    process_cycle_efficiency,
    takt_time,
    two_level_factorial_effects,
)
from mdt.optimization import ObjectiveWeights, ScheduleProblem, default_planning_jobs
from mdt.persistence import EventRepository
from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, simulate
from mdt.twin import TwinEngine


def _conwip_peak(events) -> int:
    wip = 0
    peak = 0
    for event in events:
        if event.kind == "job_released":
            wip += 1
            peak = max(peak, wip)
        elif event.kind == "job_completed":
            wip -= 1
    if wip != 0:
        raise RuntimeError("CONWIP event accounting did not close")
    return peak


def _doe(problem: ScheduleProblem) -> tuple[list[dict[str, float]], list[dict[str, float | str]]]:
    rows = []
    raw = []
    for cv_code in (-1.0, 1.0):
        for mtbf_code in (-1.0, 1.0):
            for mttr_code in (-1.0, 1.0):
                cv = 0.05 if cv_code < 0 else 0.20
                mtbf = 45.0 if mtbf_code < 0 else 120.0
                mttr = 4.0 if mttr_code < 0 else 12.0
                result = simulate(
                    problem,
                    PolicySpec("DOE_SPT", "SPT"),
                    SimulationConfig(
                        seed=20260815,
                        processing_cv=cv,
                        reliability=ReliabilitySpec(mtbf=mtbf, mttr=mttr),
                        record_events=False,
                    ),
                )
                rows.append({"PROCESS_CV": cv_code, "MTBF": mtbf_code, "MTTR": mttr_code, "tardiness": result.metrics.total_tardiness})
                raw.append({"process_cv": cv, "mtbf": mtbf, "mttr": mttr, "total_tardiness": result.metrics.total_tardiness})
    effects = [asdict(effect) for effect in two_level_factorial_effects(rows, "tardiness")]
    return effects, raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V1 engineering diagnostics without mutating the frozen release evidence by default.")
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help="Regenerate docs/VALIDATION_EVIDENCE.json intentionally. Final acceptance does not use this flag.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    model = load_orlib_instance(root / "data" / "external" / "orlib" / "jobshop1.txt", "ft06")
    art = root / "artifacts" / "ai"
    risk = load_bundle(art / "lateness_risk.joblib")
    cycle = load_cycle_time(art / "cycle_time.joblib")
    bottleneck = load_bottleneck(art / "bottleneck.joblib")
    anomaly = load_anomaly(art / "anomaly.joblib")
    ai_report = json.loads((root / "docs" / "evidence" / "AI_VALIDATION.json").read_text(encoding="utf-8"))
    operational_report = json.loads((root / "docs" / "evidence" / "OPERATIONAL_AI_VALIDATION.json").read_text(encoding="utf-8"))

    # Build a genuinely non-zero synchronized twin state: one operation is
    # complete and a second job has an active operation that must be frozen.
    twin = TwinEngine(model)
    events = [
        ManufacturingEvent("cc-r0", EventType.JOB_RELEASED, 0.0, job_id="J0"),
        ManufacturingEvent("cc-s0", EventType.OPERATION_STARTED, 0.0, operation_id="J0-O0", machine_id="M2"),
        ManufacturingEvent("cc-c0", EventType.OPERATION_COMPLETED, 1.0, operation_id="J0-O0", machine_id="M2"),
        ManufacturingEvent("cc-r1", EventType.JOB_RELEASED, 1.0, job_id="J1"),
        ManufacturingEvent("cc-s1", EventType.OPERATION_STARTED, 1.0, operation_id="J1-O0", machine_id="M1"),
    ]
    snapshot = twin.replay(events)

    decision = build_twin_recovery_decision(
        model,
        snapshot,
        risk,
        cycle,
        bottleneck,
        anomaly,
        backend="auto",
        due_factor=1.5,
        time_limit=20.0,
        processing_cv=0.10,
        mtbf=80.0,
        mttr=5.0,
    )
    stress = build_twin_future_state_stress_test(
        model,
        snapshot,
        risk,
        cycle,
        bottleneck,
        anomaly,
        backend="auto",
        due_factor=1.5,
        time_limit=20.0,
        replications=8,
        base_seed=20260815,
        processing_cv=0.10,
        mtbf=80.0,
        mttr=5.0,
        risk_aversion=0.35,
        wip_cap=3,
    )

    # IE control calculations and shop-floor pull/DOE evidence.
    planning = score_planning_jobs(risk, model, default_planning_jobs(model, 1.5))
    base_problem = ScheduleProblem(model, planning, ObjectiveWeights(0.05, 1.0, 2.0))
    conwip = simulate(
        base_problem,
        PolicySpec("CONWIP_SPT", "SPT"),
        SimulationConfig(
            seed=20260815,
            processing_cv=0.05,
            reliability=ReliabilitySpec(mtbf=120.0, mttr=5.0),
            wip_cap=3,
            record_events=True,
        ),
    )
    peak_wip = _conwip_peak(conwip.events)
    dbr = drum_buffer_rope_plan(model, tuple(planning), buffer_time=5.0)
    cap = capacity_plan(model, horizon=100.0, availability_by_machine={"M5": 0.90})
    m5_capacity = next(row for row in cap if row.machine_id == "M5")
    spc = individuals_mr([1.00, 1.04, 0.98, 1.02, 1.01, 1.95])
    doe_effects, doe_runs = _doe(base_problem)

    # Decision audit/disposition persistence.
    with tempfile.TemporaryDirectory() as td:
        with EventRepository(f"sqlite:///{(Path(td) / 'closure.db').as_posix()}") as repo:
            repo.save_decision_run(
                run_id=decision["run_id"],
                decision_kind="constitution_closure_diagnostic",
                twin_state_id=decision["planning_state"]["twin_state_id"],
                twin_timestamp=decision["planning_state"]["twin_timestamp"],
                twin_event_count=decision["planning_state"]["twin_event_count"],
                model_version=__version__,
                solver_backend=decision["nominal_optimized"]["solver"]["backend"],
                data_version="ft06:public_benchmark",
                request_payload={"diagnostic": True},
                result_payload=decision,
                status=decision["decision"]["recommended_schedule"],
            )
            saved = repo.list_decision_runs(limit=5)
            disposition = repo.update_decision_disposition(decision["run_id"], HumanDisposition.APPROVED, "diagnostic approval path")

    cycle_report = operational_report["cycle_time"]
    bottleneck_report = operational_report["bottleneck"]
    anomaly_report = operational_report["anomaly"]
    nominal_ids = {op["operation_id"] for op in decision["nominal_optimized"]["operations"]}
    robust_ids = {op["operation_id"] for op in decision["robust_optimized"]["operations"]}

    pareto_points = decision["pareto_frontier"]
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

    checks = {
        "twin_state_is_nonzero": decision["planning_state"]["twin_event_count"] == 5,
        "completed_work_removed_from_or": "J0-O0" not in nominal_ids and "J0-O0" not in robust_ids,
        "running_work_frozen": any(op["operation_id"] == "J1-O0" for op in decision["planning_state"]["frozen_operations"]),
        "nominal_or_feasible": bool(decision["nominal_optimized"]["solution_quality"]["feasible"]),
        "box_robust_or_feasible": bool(decision["robust_optimized"]["solution_quality"]["feasible"]),
        "robust_status_truthful": decision["robust_optimized"]["solution_quality"]["termination_status"] == decision["robust_optimized"]["solver"]["status"],
        "pareto_frontier_present": len(pareto_points) >= 1,
        "pareto_status_truthful": pareto_status_truthful,
        "pareto_nondominated_3d": pareto_nondominated,
        "four_policy_stress_test": len(stress["stress_test"]["summaries"]) == 4,
        "stochastic_policy_milp_verified": stress["stress_test"]["stochastic_policy_selection"]["solver"]["status"] == "OPTIMAL" and stress["stress_test"]["stochastic_policy_selection"]["selected_policy"] == stress["stress_test"]["stochastic_policy_selection"]["solver"]["oracle_selected_policy"],
        "conwip_cap_respected": peak_wip <= 3,
        "dbr_constraint_is_m5": dbr.constraint_machine_id == "M5",
        "spc_detects_injected_excursion": 5 in spc.out_of_control_indices,
        "decision_run_persisted": len(saved) == 1 and saved[0]["run_id"] == decision["run_id"],
        "human_disposition_persisted": disposition["human_disposition"] == "approved",
        "lateness_beats_prior_baseline": ai_report["production_model"]["brier"] < ai_report["class_prior_baseline"]["brier"],
        "cycle_time_beats_touch_time_baseline": cycle_report["production_model"]["mae"] < cycle_report["touch_time_baseline"]["mae"],
        "bottleneck_beats_static_baseline": bottleneck_report["production_model"]["top1_accuracy"] > bottleneck_report["static_workload_baseline"]["top1_accuracy"],
        "anomaly_beats_simple_threshold": anomaly_report["production_model"]["roc_auc"] > anomaly_report["downtime_threshold_baseline"]["roc_auc"],
        "v1_version_normalized": __version__ == "1.0.0",
        "constitution_traceability_resolved": (lambda tr: tr.get("version") == "1.0.0" and not tr.get("unresolved") and len(tr.get("requirements", [])) >= 60 and all(row.get("status") in set(tr.get("allowed_statuses", [])) for row in tr.get("requirements", [])))(json.loads((root / "docs" / "CONSTITUTION_TRACEABILITY.json").read_text(encoding="utf-8"))),
        "final_quality_gate_25_of_25": "25 / 25 resolved for V1.0" in (root / "docs" / "QUALITY_GATE.md").read_text(encoding="utf-8"),
        "methodology_product_present": (lambda html, doc: all(token in html for token in ["Engineering Methodology", "LITTLE'S LAW", "KINGMAN", "CVaR", "NO-REGRET"]) and all(token in doc for token in ["Little's Law", "Kingman", "CVaR", "no-regret"]))((root / "workspace" / "methodology.html").read_text(encoding="utf-8"), (root / "docs" / "METHODOLOGY.md").read_text(encoding="utf-8")),
        "final_frontend_decision_workflow_present": (lambda html, js: all(token in html for token in ["twinStateId", "DECISION EVIDENCE PACKET", "HUMAN DECISION GATE", "decisionDisposition"]) and all(token in js for token in ["renderDecisionPacket", "data-disposition", "/v1/ai/operational", "/v1/ie/control-plan"]))((root / "workspace" / "index.html").read_text(encoding="utf-8"), (root / "workspace" / "app.js").read_text(encoding="utf-8")),
    }

    evidence = {
        "release": "V1.0",
        "version": __version__,
        "evidence_policy": "Observed/ingested twin state, predicted values, optimized decisions and simulated outcomes are labeled separately. External plant validation remains pending.",
        "synchronized_twin_decision": {
            "planning_state": decision["planning_state"],
            "nominal_solver": decision["nominal_optimized"]["solver"],
            "robust_solver": decision["robust_optimized"]["solver"],
            "pareto_points": decision["pareto_frontier"],
            "decision_contract": decision["decision"],
        },
        "artificial_intelligence": {
            "lateness": ai_report["production_model"],
            "cycle_time": cycle_report["production_model"],
            "cycle_time_baseline": cycle_report["touch_time_baseline"],
            "bottleneck": bottleneck_report["production_model"],
            "bottleneck_baseline": bottleneck_report["static_workload_baseline"],
            "anomaly": anomaly_report["production_model"],
            "anomaly_baseline": anomaly_report["downtime_threshold_baseline"],
            "predicted_bottleneck": decision["ai"]["predicted_bottleneck"],
        },
        "industrial_engineering": {
            "takt_reference": takt_time(480.0, 240.0),
            "oee_reference": oee(0.90, 0.95, 0.99),
            "pce_reference": process_cycle_efficiency(10.0, 50.0),
            "jit_latest_release_reference": jit_latest_release(100.0, 20.0, 5.0),
            "m5_capacity": asdict(m5_capacity),
            "dbr_constraint": dbr.constraint_machine_id,
            "dbr_release_plan": [asdict(row) for row in dbr.jobs],
            "conwip_wip_limit": 3,
            "conwip_observed_peak_wip": peak_wip,
            "spc": asdict(spc),
            "doe_effects": doe_effects,
            "doe_runs": doe_runs,
        },
        "operations_research": {
            "nominal": decision["nominal_optimized"],
            "box_robust": decision["robust_optimized"],
            "pareto_frontier": decision["pareto_frontier"],
            "simulation_optimized_policy": stress["stress_test"]["recommended_policy"],
            "stochastic_policy_selection": stress["stress_test"]["stochastic_policy_selection"],
            "simulation_policy_count": len(stress["stress_test"]["summaries"]),
        },
        "auditability": {
            "run_id": decision["run_id"],
            "saved_runs": len(saved),
            "human_disposition": disposition,
        },
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }
    if args.write_evidence:
        out = root / "docs" / "VALIDATION_EVIDENCE.json"
        out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"VALIDATION_EVIDENCE_WRITTEN={out}")
    terminal_summary = {
        "version": __version__,
        "twin_event_count": decision["planning_state"]["twin_event_count"],
        "completed_work_removed": checks["completed_work_removed_from_or"],
        "running_work_frozen": checks["running_work_frozen"],
        "ai_tasks": {
            "lateness_brier": ai_report["production_model"]["brier"],
            "cycle_time_mae": cycle_report["production_model"]["mae"],
            "bottleneck_top1": bottleneck_report["production_model"]["top1_accuracy"],
            "anomaly_roc_auc": anomaly_report["production_model"]["roc_auc"],
        },
        "ie": {
            "dbr_constraint": dbr.constraint_machine_id,
            "conwip_peak_wip": peak_wip,
            "spc_out_of_control_indices": list(spc.out_of_control_indices),
            "doe_effects": len(doe_effects),
        },
        "or": {
            "nominal_status": decision["nominal_optimized"]["solver"]["status"],
            "robust_status": decision["robust_optimized"]["solver"]["status"],
            "robust_solution_quality": decision["robust_optimized"]["solution_quality"],
            "pareto_points": len(decision["pareto_frontier"]),
            "stochastic_selected_policy": stress["stress_test"]["stochastic_policy_selection"]["selected_policy"],
            "stochastic_oracle": stress["stress_test"]["stochastic_policy_selection"]["solver"]["oracle_selected_policy"],
        },
        "audit": {"decision_run_saved": checks["decision_run_persisted"], "human_disposition": disposition["human_disposition"]},
        "checks_passed": sum(1 for value in checks.values() if value),
        "checks_total": len(checks),
        "status": evidence["status"],
    }
    print(json.dumps(terminal_summary, indent=2))
    if evidence["status"] != "PASS":
        failed = [name for name, value in checks.items() if not value]
        raise SystemExit(f"V1_DIAGNOSTICS=FAIL: {failed}")
    print("V1_DIAGNOSTICS=PASS")


if __name__ == "__main__":
    main()
