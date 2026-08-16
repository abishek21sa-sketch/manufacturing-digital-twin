from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from mdt.ai import load_bundle, score_planning_jobs
from mdt.data import load_orlib_instance
from mdt.optimization import ObjectiveWeights, ScheduleProblem, default_planning_jobs, solve_schedule
from mdt.simulation import PolicySpec, ReliabilitySpec, SimulationConfig, simulate


def timed(callable_):
    start = perf_counter()
    value = callable_()
    return value, perf_counter() - start


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    factory, load_seconds = timed(lambda: load_orlib_instance(root / "data/external/orlib/jobshop1.txt", "ft06"))
    bundle, model_load_seconds = timed(lambda: load_bundle(root / "artifacts/ai/lateness_risk.joblib"))
    planning = default_planning_jobs(factory, 1.5)
    scored, inference_seconds = timed(lambda: score_planning_jobs(bundle, factory, planning))
    problem = ScheduleProblem(factory, scored, ObjectiveWeights(0.05, 1.0, 2.0))
    schedule, oracle_solve_seconds = timed(lambda: solve_schedule(problem, backend="scipy", time_limit=30, mip_gap=0.0))
    trajectory, des_seconds = timed(
        lambda: simulate(
            problem,
            PolicySpec("SPT_PERF", "SPT"),
            SimulationConfig(seed=20260815, processing_cv=0.10, reliability=ReliabilitySpec(mtbf=80.0, mttr=5.0)),
        )
    )
    evidence = {
        "release": "V1.0",
        "benchmark": "FT06",
        "timings_seconds": {
            "benchmark_load": load_seconds,
            "ai_model_load": model_load_seconds,
            "six_job_ai_inference": inference_seconds,
            "scipy_highs_milp": oracle_solve_seconds,
            "single_stochastic_des": des_seconds,
        },
        "outputs": {
            "ai_jobs_scored": len(scored),
            "oracle_status": schedule.evidence.status,
            "oracle_makespan": schedule.makespan,
            "des_makespan": trajectory.metrics.makespan,
        },
    }
    print(json.dumps(evidence, indent=2))
    # These are deliberately generous regression ceilings, not performance claims.
    if load_seconds > 5 or model_load_seconds > 10 or inference_seconds > 5 or oracle_solve_seconds > 30 or des_seconds > 10:
        raise SystemExit("PERFORMANCE_CHECK=FAIL")
    print("PERFORMANCE_CHECK=PASS")


if __name__ == "__main__":
    main()
