from __future__ import annotations

from dataclasses import dataclass, replace

from mdt.domain import FactoryModel
from mdt.optimization.model import PlanningJob
from .factory_physics import identify_constraint


@dataclass(frozen=True)
class DBRJobPlan:
    job_id: str
    constraint_machine_id: str
    work_before_constraint: float
    drum_start: float
    drum_finish: float
    rope_release_time: float
    buffer_time: float


@dataclass(frozen=True)
class DBRPlan:
    constraint_machine_id: str
    buffer_time: float
    jobs: tuple[DBRJobPlan, ...]

    def release_adjusted_jobs(self, original: tuple[PlanningJob, ...]) -> tuple[PlanningJob, ...]:
        plan = {row.job_id: row for row in self.jobs}
        return tuple(replace(job, release_time=max(job.release_time, plan[job.job_id].rope_release_time)) for job in original)


def drum_buffer_rope_plan(
    factory: FactoryModel,
    planning_jobs: tuple[PlanningJob, ...],
    *,
    buffer_time: float,
) -> DBRPlan:
    """Create a deterministic Drum-Buffer-Rope release plan around the workload constraint.

    The drum is sequenced by earliest due date on the identified constraint. The
    rope release is timed so upstream work should reach the constraint buffer
    `buffer_time` before its drum slot. This is a planning/control calculation,
    not a claim that the static workload constraint will remain the stochastic
    bottleneck.
    """
    if buffer_time < 0:
        raise ValueError("buffer_time must be non-negative")
    pmap = {job.job_id: job for job in planning_jobs}
    if set(pmap) != {job.job_id for job in factory.jobs}:
        raise ValueError("planning jobs must match factory jobs")
    constraint = identify_constraint(factory)
    rows: list[tuple[float, str, float, float]] = []
    for job in factory.jobs:
        work_before = 0.0
        constraint_time = None
        for op in job.operations:
            if op.machine_id == constraint.machine_id:
                constraint_time = op.processing_time
                break
            work_before += op.processing_time
        if constraint_time is None:
            # A job with no constraint visit does not consume the drum. Give it a
            # zero-duration notional slot so the release rule remains explicit.
            constraint_time = 0.0
        rows.append((pmap[job.job_id].due_time, job.job_id, work_before, constraint_time))

    cursor = min((pmap[job_id].release_time + before for _, job_id, before, _ in rows), default=0.0)
    result: list[DBRJobPlan] = []
    for _, job_id, work_before, constraint_time in sorted(rows):
        pj = pmap[job_id]
        drum_start = max(cursor, pj.release_time + work_before)
        drum_finish = drum_start + constraint_time
        rope_release = max(pj.release_time, drum_start - work_before - buffer_time)
        result.append(DBRJobPlan(job_id, constraint.machine_id, work_before, drum_start, drum_finish, rope_release, buffer_time))
        cursor = drum_finish
    return DBRPlan(constraint.machine_id, buffer_time, tuple(result))


def conwip_release_allowed(current_wip: int, wip_limit: int) -> bool:
    if current_wip < 0:
        raise ValueError("current_wip must be non-negative")
    if wip_limit <= 0:
        raise ValueError("wip_limit must be positive")
    return current_wip < wip_limit
