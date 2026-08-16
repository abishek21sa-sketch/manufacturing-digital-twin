from __future__ import annotations

from time import perf_counter

from .model import ScheduleProblem, ScheduleResult, ScheduledOperation, SolverEvidence


class GurobiUnavailable(RuntimeError):
    pass


def gurobi_available() -> bool:
    try:
        import gurobipy  # noqa: F401
        return True
    except Exception:
        return False


def solve_with_gurobi(problem: ScheduleProblem, time_limit: float = 30.0, mip_gap: float = 0.0) -> ScheduleResult:
    problem.validate()
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except Exception as exc:
        raise GurobiUnavailable("gurobipy is not installed; install the 'gurobi' extra") from exc

    operations = [op for job in problem.factory.jobs for op in job.operations]
    base_time = max(
        [problem.current_time]
        + [j.release_time for j in problem.jobs]
        + [problem.machine_ready_time(m.machine_id) for m in problem.factory.machines]
    )
    horizon = base_time + sum(op.processing_time for op in operations) + 1.0
    started = perf_counter()
    try:
        # Explicit Env + Model contexts are intentional for deterministic Windows cleanup.
        with gp.Env(params={"OutputFlag": 0}) as env, gp.Model("mdt_jobshop", env=env) as model:
            model.Params.TimeLimit = float(time_limit)
            model.Params.MIPGap = float(mip_gap)
            starts = {}
            tard = {}
            for op in operations:
                pj = problem.planning_job(op.job_id)
                starts[op.operation_id] = model.addVar(
                    lb=max(problem.current_time, pj.release_time, problem.machine_ready_time(op.machine_id)),
                    ub=horizon,
                    name=f"s[{op.operation_id}]",
                )
            cmax = model.addVar(lb=0.0, ub=horizon, name="Cmax")
            for job in problem.factory.jobs:
                tard[job.job_id] = model.addVar(lb=0.0, ub=horizon, name=f"T[{job.job_id}]")

            for job in problem.factory.jobs:
                for prev, nxt in zip(job.operations, job.operations[1:]):
                    model.addConstr(starts[nxt.operation_id] >= starts[prev.operation_id] + prev.processing_time, name=f"prec[{prev.operation_id},{nxt.operation_id}]")

            big_m = horizon
            for machine in problem.factory.machines:
                ops = [o for o in operations if o.machine_id == machine.machine_id]
                for a in range(len(ops)):
                    for b in range(a + 1, len(ops)):
                        left, right = ops[a], ops[b]
                        y = model.addVar(vtype=GRB.BINARY, name=f"y[{left.operation_id},{right.operation_id}]")
                        model.addConstr(starts[left.operation_id] + left.processing_time <= starts[right.operation_id] + big_m * (1 - y))
                        model.addConstr(starts[right.operation_id] + right.processing_time <= starts[left.operation_id] + big_m * y)

            for job in problem.factory.jobs:
                last = job.operations[-1]
                completion = starts[last.operation_id] + last.processing_time
                model.addConstr(cmax >= completion, name=f"makespan[{job.job_id}]")
                model.addConstr(tard[job.job_id] >= completion - problem.planning_job(job.job_id).due_time, name=f"tard[{job.job_id}]")

            if problem.max_total_tardiness is not None:
                model.addConstr(
                    gp.quicksum(tard[job.job_id] for job in problem.factory.jobs) <= float(problem.max_total_tardiness),
                    name="total_tardiness_guard",
                )

            objective = problem.objective.makespan * cmax
            for job in problem.factory.jobs:
                pj = problem.planning_job(job.job_id)
                coefficient = pj.priority_weight * (problem.objective.tardiness + problem.objective.risk_tardiness * pj.risk_score)
                objective += coefficient * tard[job.job_id]
            model.setObjective(objective, GRB.MINIMIZE)
            model.optimize()
            elapsed = perf_counter() - started

            status_map = {GRB.OPTIMAL: "OPTIMAL", GRB.INFEASIBLE: "INFEASIBLE", GRB.UNBOUNDED: "UNBOUNDED", GRB.INF_OR_UNBD: "ERROR", GRB.TIME_LIMIT: "TIME_LIMIT", GRB.INTERRUPTED: "FEASIBLE" if model.SolCount > 0 else "ERROR"}
            status = status_map.get(model.Status, "FEASIBLE" if model.SolCount > 0 else "ERROR")
            if model.SolCount <= 0:
                evidence = SolverEvidence("gurobi", status, None, float(model.ObjBound) if hasattr(model, "ObjBound") else None, None, elapsed, str(model.Status))
                return ScheduleResult((), {}, {}, None, evidence, {})

            scheduled = tuple(ScheduledOperation(op.operation_id, op.job_id, op.machine_id, op.sequence, float(starts[op.operation_id].X), float(starts[op.operation_id].X + op.processing_time)) for op in operations)
            completion = {job.job_id: next(o.finish for o in scheduled if o.operation_id == job.operations[-1].operation_id) for job in problem.factory.jobs}
            tardiness = {j.job_id: max(0.0, completion[j.job_id] - problem.planning_job(j.job_id).due_time) for j in problem.factory.jobs}
            makespan = max(completion.values())
            components = {"makespan": makespan, "total_tardiness": sum(tardiness.values()), "risk_weighted_tardiness": sum(problem.planning_job(j).risk_score * t for j, t in tardiness.items())}
            evidence = SolverEvidence("gurobi", status, float(model.ObjVal), float(model.ObjBound), float(model.MIPGap) if model.IsMIP and model.SolCount > 0 else 0.0, float(model.Runtime), str(model.Status))
            return ScheduleResult(scheduled, completion, tardiness, makespan, evidence, components)
    except GurobiUnavailable:
        raise
    except Exception as exc:
        raise GurobiUnavailable(f"Gurobi environment/license unavailable or solve failed: {exc}") from exc
