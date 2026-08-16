from __future__ import annotations

import json
from pathlib import Path

from mdt.data import load_orlib_instance
from mdt.optimization import ObjectiveWeights, ScheduleProblem, default_planning_jobs, gurobi_available, solve_schedule, validate_schedule


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    if not gurobi_available():
        raise SystemExit("GUROBI_ACCEPTANCE=FAIL: gurobipy is not importable")
    model = load_orlib_instance(root / "data" / "external" / "orlib" / "jobshop1.txt", "ft06")
    problem = ScheduleProblem(model, default_planning_jobs(model, 100.0), ObjectiveWeights(makespan=1.0))
    gurobi = solve_schedule(problem, backend="gurobi", time_limit=30, mip_gap=0.0)
    oracle = solve_schedule(problem, backend="scipy", time_limit=30, mip_gap=0.0)
    violations = validate_schedule(problem, gurobi)
    evidence = {
        "gurobi": {"status": gurobi.evidence.status, "objective": gurobi.evidence.objective_value, "best_bound": gurobi.evidence.best_bound, "mip_gap": gurobi.evidence.mip_gap, "runtime_seconds": gurobi.evidence.solve_time_seconds},
        "independent_oracle": {"backend": oracle.evidence.backend, "status": oracle.evidence.status, "objective": oracle.evidence.objective_value},
        "violations": [v.message for v in violations],
    }
    print(json.dumps(evidence, indent=2))
    if gurobi.evidence.status != "OPTIMAL" or violations or abs((gurobi.makespan or -1) - 55.0) > 1e-4 or abs((oracle.makespan or -2) - (gurobi.makespan or -1)) > 1e-4:
        raise SystemExit("GUROBI_ACCEPTANCE=FAIL")
    print("GUROBI_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
