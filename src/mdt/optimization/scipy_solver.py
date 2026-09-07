from __future__ import annotations

from math import inf
from time import perf_counter

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from .model import ScheduleProblem, ScheduleResult, ScheduledOperation, SolverEvidence


def solve_with_scipy(problem: ScheduleProblem, time_limit: float = 30.0, mip_gap: float = 0.0) -> ScheduleResult:
    problem.validate()
    operations = [op for job in problem.factory.jobs for op in job.operations]
    op_idx = {op.operation_id: i for i, op in enumerate(operations)}
    machine_pairs: list[tuple[int, int]] = []
    for machine in problem.factory.machines:
        indices = [op_idx[o.operation_id] for o in operations if o.machine_id == machine.machine_id]
        for a in range(len(indices)):
            for b in range(a + 1, len(indices)):
                machine_pairs.append((indices[a], indices[b]))

    n_ops = len(operations)
    n_pairs = len(machine_pairs)
    n_jobs = len(problem.factory.jobs)
    start_offset = 0
    pair_offset = n_ops
    tard_offset = pair_offset + n_pairs
    cmax_idx = tard_offset + n_jobs
    n_vars = cmax_idx + 1
    deviation_ids = tuple(
        op.operation_id
        for op in operations
        if problem.stability_penalty > 0 and op.operation_id in problem.prior_start
    )
    deviation_offset = n_vars
    deviation_idx = {operation_id: deviation_offset + i for i, operation_id in enumerate(deviation_ids)}
    n_vars += len(deviation_ids)

    c = np.zeros(n_vars)
    integrality = np.zeros(n_vars)
    integrality[pair_offset:tard_offset] = 1
    c[cmax_idx] = problem.objective.makespan
    for j_idx, job in enumerate(problem.factory.jobs):
        pj = problem.planning_job(job.job_id)
        c[tard_offset + j_idx] = pj.priority_weight * (
            problem.objective.tardiness + problem.objective.risk_tardiness * pj.risk_score
        )
    for index in deviation_idx.values():
        c[index] = problem.stability_penalty

    base_time = max(
        [problem.current_time]
        + [j.release_time for j in problem.jobs]
        + [problem.machine_ready_time(m.machine_id) for m in problem.factory.machines]
    )
    horizon = base_time + sum(op.processing_time for op in operations) + 1.0
    lb = np.zeros(n_vars)
    ub = np.full(n_vars, horizon)
    ub[pair_offset:tard_offset] = 1.0
    for op in operations:
        pj = problem.planning_job(op.job_id)
        lb[op_idx[op.operation_id]] = max(problem.current_time, pj.release_time, problem.machine_ready_time(op.machine_id))
    bounds = Bounds(lb, ub)

    rows: list[dict[int, float]] = []
    uppers: list[float] = []

    def add(coeffs: dict[int, float], upper: float) -> None:
        rows.append(coeffs); uppers.append(upper)

    for job in problem.factory.jobs:
        for prev, nxt in zip(job.operations, job.operations[1:]):
            add({op_idx[prev.operation_id]: 1.0, op_idx[nxt.operation_id]: -1.0}, -prev.processing_time)

    for operation_id, index in deviation_idx.items():
        prior = float(problem.prior_start[operation_id])
        # deviation >= start - prior and deviation >= prior - start
        add({op_idx[operation_id]: 1.0, index: -1.0}, prior)
        add({op_idx[operation_id]: -1.0, index: -1.0}, -prior)

    big_m = horizon
    for p_idx, (i, j) in enumerate(machine_pairs):
        y = pair_offset + p_idx
        pi = operations[i].processing_time
        pj = operations[j].processing_time
        # s_i + p_i <= s_j + M(1-y)  -> s_i-s_j+M*y <= M-p_i
        add({i: 1.0, j: -1.0, y: big_m}, big_m - pi)
        # s_j + p_j <= s_i + M*y -> s_j-s_i-M*y <= -p_j
        add({j: 1.0, i: -1.0, y: -big_m}, -pj)

    for j_idx, job in enumerate(problem.factory.jobs):
        last = job.operations[-1]
        s = op_idx[last.operation_id]
        add({s: 1.0, cmax_idx: -1.0}, -last.processing_time)
        due = problem.planning_job(job.job_id).due_time
        # T >= s+p-due -> s-T <= due-p
        add({s: 1.0, tard_offset + j_idx: -1.0}, due - last.processing_time)

    if problem.max_total_tardiness is not None:
        add(
            {tard_offset + j_idx: 1.0 for j_idx in range(n_jobs)},
            float(problem.max_total_tardiness),
        )

    A = lil_matrix((len(rows), n_vars), dtype=float)
    for r, coeffs in enumerate(rows):
        for idx, val in coeffs.items():
            A[r, idx] = val
    constraints = LinearConstraint(A.tocsr(), np.full(len(rows), -inf), np.asarray(uppers))

    started = perf_counter()
    res = milp(
        c=c,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
        options={"time_limit": float(time_limit), "mip_rel_gap": float(mip_gap), "presolve": True},
    )
    elapsed = perf_counter() - started
    status_map = {0: "OPTIMAL", 1: "TIME_LIMIT", 2: "INFEASIBLE", 3: "UNBOUNDED", 4: "ERROR"}
    status = status_map.get(int(res.status), "ERROR")
    if res.x is None:
        return ScheduleResult((), {}, {}, None, SolverEvidence(
            "scipy-highs", status, None, getattr(res, "mip_dual_bound", None), getattr(res, "mip_gap", None), elapsed, str(res.message), n_vars, len(rows)
        ), {})

    x = res.x
    scheduled = tuple(
        ScheduledOperation(op.operation_id, op.job_id, op.machine_id, op.sequence, float(x[op_idx[op.operation_id]]), float(x[op_idx[op.operation_id]] + op.processing_time))
        for op in operations
    )
    completion = {job.job_id: next(o.finish for o in scheduled if o.operation_id == job.operations[-1].operation_id) for job in problem.factory.jobs}
    tardiness = {j.job_id: max(0.0, completion[j.job_id] - problem.planning_job(j.job_id).due_time) for j in problem.factory.jobs}
    makespan = max(completion.values())
    components = {
        "makespan": makespan,
        "total_tardiness": sum(tardiness.values()),
        "risk_weighted_tardiness": sum(problem.planning_job(j).risk_score * t for j, t in tardiness.items()),
        "schedule_stability": sum(abs(float(x[op_idx[operation_id]]) - float(problem.prior_start[operation_id])) for operation_id in deviation_ids),
        "stability_penalty": float(sum(c[index] * x[index] for index in deviation_idx.values())),
    }
    return ScheduleResult(
        scheduled, completion, tardiness, makespan,
        SolverEvidence(
            "scipy-highs", status, float(res.fun) if res.fun is not None else None,
            float(res.mip_dual_bound) if getattr(res, "mip_dual_bound", None) is not None else None,
            float(res.mip_gap) if getattr(res, "mip_gap", None) is not None else None,
            elapsed, str(res.message), n_vars, len(rows),
        ), components,
    )
