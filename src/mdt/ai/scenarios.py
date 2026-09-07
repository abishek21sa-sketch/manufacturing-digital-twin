from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mdt.domain import FactoryModel, JobSpec, OperationSpec
from mdt.optimization.model import PlanningJob, ScheduleProblem, ScheduledOperation


FEATURE_NAMES = (
    "release_time",
    "due_allowance",
    "total_work",
    "mean_operation_time",
    "max_operation_time",
    "critical_ratio",
    "bottleneck_operation_time",
    "bottleneck_work_share",
    "system_bottleneck_load",
    "system_mean_machine_load",
    "due_tightness",
)


@dataclass(frozen=True)
class HeuristicSchedule:
    completion: dict[str, float]
    makespan: float
    operations: tuple[ScheduledOperation, ...] = ()


def _machine_loads(factory: FactoryModel) -> dict[str, float]:
    loads = {m.machine_id: 0.0 for m in factory.machines}
    for job in factory.jobs:
        for op in job.operations:
            loads[op.machine_id] += op.processing_time
    return loads


def extract_job_features(factory: FactoryModel, planning_jobs: tuple[PlanningJob, ...]) -> tuple[np.ndarray, list[str]]:
    pmap = {j.job_id: j for j in planning_jobs}
    loads = _machine_loads(factory)
    constraint_machine, constraint_load = max(loads.items(), key=lambda item: item[1])
    mean_load = float(np.mean(list(loads.values())))
    rows: list[list[float]] = []
    ids: list[str] = []
    for job in factory.jobs:
        planning = pmap[job.job_id]
        durations = np.asarray([op.processing_time for op in job.operations], dtype=float)
        total = float(durations.sum())
        allowance = planning.due_time - planning.release_time
        bottleneck_time = sum(op.processing_time for op in job.operations if op.machine_id == constraint_machine)
        rows.append([
            planning.release_time,
            allowance,
            total,
            float(durations.mean()),
            float(durations.max()),
            allowance / total if total else 0.0,
            bottleneck_time,
            bottleneck_time / total if total else 0.0,
            constraint_load,
            mean_load,
            total / allowance if allowance > 0 else 999.0,
        ])
        ids.append(job.job_id)
    return np.asarray(rows, dtype=float), ids


def heuristic_dispatch(problem: ScheduleProblem, rule: str = "SPT") -> HeuristicSchedule:
    """Deterministic serial schedule-generation heuristic used as the status-quo baseline.

    This is not the stochastic DES. It produces a feasible deterministic
    finite-capacity schedule for synthetic label generation and baseline comparison.
    """
    problem.validate()
    key = rule.upper()
    if key not in {"SPT", "EDD", "FIFO"}:
        raise ValueError("rule must be SPT, EDD, or FIFO")
    machine_available = {m.machine_id: problem.machine_ready_time(m.machine_id) for m in problem.factory.machines}
    job_ready = {j.job_id: max(problem.current_time, problem.planning_job(j.job_id).release_time) for j in problem.factory.jobs}
    next_index = {j.job_id: 0 for j in problem.factory.jobs}
    completion: dict[str, float] = {}
    scheduled: list[ScheduledOperation] = []
    total_ops = problem.factory.operation_count

    for _ in range(total_ops):
        candidates = []
        for job in problem.factory.jobs:
            idx = next_index[job.job_id]
            if idx >= len(job.operations):
                continue
            op = job.operations[idx]
            earliest = max(job_ready[job.job_id], machine_available[op.machine_id])
            if key == "SPT":
                priority = (op.processing_time, problem.planning_job(job.job_id).due_time, job.job_id)
            elif key == "EDD":
                priority = (problem.planning_job(job.job_id).due_time, op.processing_time, job.job_id)
            else:
                priority = (problem.planning_job(job.job_id).release_time, job.job_id)
            candidates.append((earliest, priority, job, op))
        if not candidates:
            raise RuntimeError("dispatch scheduler deadlocked")
        _, _, job, op = min(candidates, key=lambda item: (item[0], item[1]))
        start = max(job_ready[job.job_id], machine_available[op.machine_id])
        finish = start + op.processing_time
        scheduled.append(ScheduledOperation(op.operation_id, job.job_id, op.machine_id, op.sequence, start, finish))
        machine_available[op.machine_id] = finish
        job_ready[job.job_id] = finish
        next_index[job.job_id] += 1
        if next_index[job.job_id] == len(job.operations):
            completion[job.job_id] = finish
    return HeuristicSchedule(completion, max(completion.values()), tuple(scheduled))


def perturb_factory(factory: FactoryModel, rng: np.random.Generator) -> FactoryModel:
    jobs = []
    for job in factory.jobs:
        ops = []
        for op in job.operations:
            multiplier = float(np.clip(rng.lognormal(mean=0.0, sigma=0.18), 0.65, 1.55))
            ops.append(OperationSpec(op.operation_id, op.job_id, op.sequence, op.machine_id, max(0.25, op.processing_time * multiplier)))
        jobs.append(JobSpec(job.job_id, tuple(ops), release_time=0.0))
    return FactoryModel(factory.factory_id, factory.machines, tuple(jobs), factory.source, "synthetic_scenario", {**factory.metadata, "synthetic": True})


def generate_lateness_dataset(factory: FactoryModel, n_scenarios: int = 300, seed: int = 20260815) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if n_scenarios < 30:
        raise ValueError("at least 30 scenarios are required for grouped validation")
    rng = np.random.default_rng(seed)
    feature_rows: list[np.ndarray] = []
    targets: list[int] = []
    groups: list[int] = []
    for scenario_id in range(n_scenarios):
        scenario_factory = perturb_factory(factory, rng)
        global_tightness = float(rng.uniform(0.95, 2.85))
        planning = []
        for job in scenario_factory.jobs:
            release = float(rng.uniform(0.0, 18.0))
            total = sum(op.processing_time for op in job.operations)
            factor = float(np.clip(global_tightness + rng.normal(0.0, 0.45), 0.75, 3.6))
            planning.append(PlanningJob(job.job_id, release, release + factor * total))
        planning_tuple = tuple(planning)
        problem = ScheduleProblem(scenario_factory, planning_tuple)
        baseline = heuristic_dispatch(problem, "SPT")
        X, ids = extract_job_features(scenario_factory, planning_tuple)
        for row, job_id in zip(X, ids):
            feature_rows.append(row)
            targets.append(int(baseline.completion[job_id] > problem.planning_job(job_id).due_time))
            groups.append(scenario_id)
    return np.vstack(feature_rows), np.asarray(targets, dtype=int), np.asarray(groups, dtype=int)
