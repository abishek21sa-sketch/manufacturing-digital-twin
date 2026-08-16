from __future__ import annotations

from dataclasses import dataclass
import hashlib
import heapq
import math
from typing import Any

import numpy as np

from mdt.optimization.model import ScheduleProblem
from .model import (
    DowntimeInterval,
    PolicySpec,
    ProcessingSegment,
    SimulatedOperation,
    SimulationConfig,
    SimulationEvent,
    SimulationMetrics,
    SimulationResult,
)


@dataclass
class _MachineState:
    status: str = "idle"
    operation_id: str | None = None
    segment_start: float | None = None
    down_start: float | None = None


@dataclass
class _OperationState:
    realized_processing: float | None = None
    remaining: float | None = None
    first_start: float | None = None
    finish: float | None = None
    interruptions: int = 0


def _stable_seed(seed: int, *parts: str) -> int:
    raw = "|".join([str(seed), *parts]).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "little") % (2**32 - 1)


def _processing_multiplier(seed: int, operation_id: str, cv: float) -> float:
    if cv == 0:
        return 1.0
    # Lognormal parameterization with E[multiplier] = 1.
    sigma2 = math.log1p(cv * cv)
    sigma = math.sqrt(sigma2)
    mean = -0.5 * sigma2
    rng = np.random.default_rng(_stable_seed(seed, "processing", operation_id))
    return float(np.clip(rng.lognormal(mean=mean, sigma=sigma), 0.35, 2.5))


def _metrics(problem: ScheduleProblem, completion: dict[str, float], tardiness: dict[str, float],
             productive: dict[str, float], downtime: dict[str, float], actual_release: dict[str, float]) -> SimulationMetrics:
    if not completion:
        raise RuntimeError("simulation completed no jobs")
    makespan = max(completion.values())
    horizon_start = min(actual_release[j.job_id] for j in problem.factory.jobs)
    horizon = max(1e-12, makespan - horizon_start)
    flow_times = [completion[j.job_id] - actual_release[j.job_id] for j in problem.factory.jobs]
    total_flow = float(sum(flow_times))
    mean_flow = total_flow / len(flow_times)
    throughput = len(flow_times) / horizon
    average_wip = total_flow / horizon
    little_rhs = throughput * mean_flow
    total_tardiness = float(sum(tardiness.values()))
    late_jobs = sum(1 for value in tardiness.values() if value > 1e-9)
    utilizations = [min(1.0, max(0.0, productive[m.machine_id] / horizon)) for m in problem.factory.machines]
    return SimulationMetrics(
        makespan=float(makespan),
        total_tardiness=total_tardiness,
        mean_tardiness=total_tardiness / len(flow_times),
        late_jobs=late_jobs,
        service_level=(len(flow_times) - late_jobs) / len(flow_times),
        mean_flow_time=float(mean_flow),
        throughput_rate=float(throughput),
        average_wip=float(average_wip),
        little_law_rhs=float(little_rhs),
        little_law_error=float(abs(average_wip - little_rhs)),
        mean_machine_utilization=float(np.mean(utilizations)),
        total_downtime=float(sum(downtime.values())),
    )


def simulate(problem: ScheduleProblem, policy: PolicySpec, config: SimulationConfig | None = None) -> SimulationResult:
    """Run one stochastic discrete-event future-state trajectory.

    Failures occur against productive operating time and interrupt the active
    operation. Repairs follow a preempt-resume policy. Processing-time
    uncertainty is sampled once per operation. Stable sub-streams make the same
    replication seed comparable across dispatch policies.
    """

    problem.validate()
    policy.validate(problem)
    cfg = config or SimulationConfig()
    cfg.validate(problem)

    machine_state = {
        m.machine_id: _MachineState(status="blocked" if problem.machine_ready_time(m.machine_id) > problem.current_time + 1e-12 else "idle")
        for m in problem.factory.machines
    }
    machine_rng = {
        m.machine_id: np.random.default_rng(_stable_seed(cfg.seed, "machine", m.machine_id))
        for m in problem.factory.machines
    }
    op_state = {
        op.operation_id: _OperationState()
        for job in problem.factory.jobs
        for op in job.operations
    }
    next_index = {job.job_id: 0 for job in problem.factory.jobs}
    released: set[str] = set()
    actual_release: dict[str, float] = {}
    pending_release: list[str] = []
    ready: set[str] = set()
    completion: dict[str, float] = {}
    segments: list[ProcessingSegment] = []
    downtimes: list[DowntimeInterval] = []
    sim_events: list[SimulationEvent] = []
    productive = {m.machine_id: 0.0 for m in problem.factory.machines}
    downtime_total = {m.machine_id: 0.0 for m in problem.factory.machines}

    # heap entries: time, deterministic sequence, kind, payload
    queue: list[tuple[float, int, str, dict[str, Any]]] = []
    event_seq = 0

    def push(time: float, kind: str, **payload: Any) -> None:
        nonlocal event_seq
        event_seq += 1
        if event_seq > cfg.max_events:
            raise RuntimeError("simulation exceeded max_events; possible deadlock/runaway failure process")
        heapq.heappush(queue, (float(time), event_seq, kind, payload))

    for job in problem.factory.jobs:
        push(max(problem.current_time, problem.planning_job(job.job_id).release_time), "release", job_id=job.job_id)
    for machine in problem.factory.machines:
        ready_time = problem.machine_ready_time(machine.machine_id)
        if ready_time > problem.current_time + 1e-12:
            push(ready_time, "machine_wake", machine_id=machine.machine_id)
    planned_machine_order: dict[str, list[str]] = {}
    if policy.rule == "PLANNED":
        for machine in problem.factory.machines:
            ordered = sorted(
                [op.operation_id for job in problem.factory.jobs for op in job.operations if op.machine_id == machine.machine_id],
                key=lambda op_id: (policy.planned_start[op_id], op_id),
            )
            planned_machine_order[machine.machine_id] = ordered
        for when in sorted({float(v) for v in policy.planned_start.values() if v > problem.current_time + 1e-12}):
            push(when, "plan_wake")

    current_time = problem.current_time

    def log(kind: str, *, job_id: str | None = None, operation_id: str | None = None,
            machine_id: str | None = None, **detail: float | str | int) -> None:
        if cfg.record_events:
            sim_events.append(SimulationEvent(float(current_time), kind, job_id, operation_id, machine_id, detail))

    def priority(operation_id: str) -> tuple[Any, ...]:
        spec = problem.factory.operation(operation_id)
        pjob = problem.planning_job(spec.job_id)
        if policy.rule == "SPT":
            return (spec.processing_time, pjob.due_time, pjob.release_time, spec.job_id)
        if policy.rule == "EDD":
            return (pjob.due_time, spec.processing_time, pjob.release_time, spec.job_id)
        if policy.rule == "FIFO":
            return (pjob.release_time, spec.job_id, spec.sequence)
        return (policy.planned_start[operation_id], pjob.due_time, spec.job_id)

    def current_wip() -> int:
        return sum(1 for job_id in released if job_id not in completion)

    def admit_pending() -> None:
        # CONWIP admission keeps the shop-floor WIP at/below the configured cap.
        # Jobs wait outside the system until a card/slot becomes available.
        while pending_release and (cfg.wip_cap is None or current_wip() < cfg.wip_cap):
            job_id = pending_release.pop(0)
            if job_id in released:
                continue
            released.add(job_id)
            actual_release[job_id] = current_time
            first = problem.factory.job(job_id).operations[0]
            ready.add(first.operation_id)
            log("job_released", job_id=job_id, release_control="CONWIP" if cfg.wip_cap is not None else "PLANNED")

    def schedule_active_piece(machine_id: str, operation_id: str, now: float, resume: bool) -> None:
        machine = machine_state[machine_id]
        state = op_state[operation_id]
        spec = problem.factory.operation(operation_id)
        if state.realized_processing is None:
            multiplier = _processing_multiplier(cfg.seed, operation_id, cfg.processing_cv)
            state.realized_processing = max(1e-9, spec.processing_time * multiplier)
            state.remaining = state.realized_processing
            state.first_start = now
        assert state.remaining is not None
        machine.status = "busy"
        machine.operation_id = operation_id
        machine.segment_start = now
        rel = cfg.reliability_for(machine_id)
        if resume:
            log("operation_resumed", job_id=spec.job_id, operation_id=operation_id, machine_id=machine_id,
                remaining_work=float(state.remaining))
        else:
            log("operation_started", job_id=spec.job_id, operation_id=operation_id, machine_id=machine_id,
                realized_processing=float(state.realized_processing))

        if rel.mtbf is None:
            push(now + state.remaining, "complete", machine_id=machine_id, operation_id=operation_id)
            return
        ttf = float(machine_rng[machine_id].exponential(rel.mtbf))
        if ttf + 1e-12 < state.remaining:
            push(now + max(ttf, 1e-9), "failure", machine_id=machine_id, operation_id=operation_id)
        else:
            push(now + state.remaining, "complete", machine_id=machine_id, operation_id=operation_id)

    def dispatch() -> None:
        # One operation per idle/up machine. Recompute queues after each choice so
        # simultaneous dispatches remain deterministic.
        changed = True
        while changed:
            changed = False
            for machine_id in sorted(machine_state):
                machine = machine_state[machine_id]
                if machine.status != "idle":
                    continue
                candidates = [op_id for op_id in ready if problem.factory.operation(op_id).machine_id == machine_id]
                if policy.rule == "PLANNED":
                    # A strict machine sequence must not let a CONWIP-held job
                    # block every admitted job behind it. Preserve the planned
                    # order among jobs that have actually entered the shop; an
                    # unreleased job becomes eligible only after admission.
                    remaining_order = [
                        op_id
                        for op_id in planned_machine_order[machine_id]
                        if op_state[op_id].finish is None and machine.operation_id != op_id
                    ]
                    admitted_order = [
                        op_id
                        for op_id in remaining_order
                        if problem.factory.operation(op_id).job_id in released
                    ]
                    if not admitted_order:
                        continue
                    target = admitted_order[0]
                    if target not in ready or current_time + 1e-12 < policy.planned_start[target]:
                        continue
                    candidates = [target]
                if not candidates:
                    continue
                chosen = min(candidates, key=priority)
                ready.remove(chosen)
                schedule_active_piece(machine_id, chosen, current_time, resume=False)
                changed = True

    completed_ops = 0
    total_ops = problem.factory.operation_count

    while completed_ops < total_ops:
        dispatch()
        if not queue:
            raise RuntimeError("simulation deadlocked with unfinished operations")
        next_time = queue[0][0]
        if next_time + 1e-12 < current_time:
            raise RuntimeError("simulation event time moved backwards")
        current_time = next_time
        same_time: list[tuple[float, int, str, dict[str, Any]]] = []
        while queue and abs(queue[0][0] - current_time) <= 1e-12:
            same_time.append(heapq.heappop(queue))

        for _, _, kind, payload in same_time:
            if kind in {"repair", "plan_wake"}:
                continue
            if kind == "machine_wake":
                machine_id = str(payload["machine_id"])
                machine = machine_state[machine_id]
                if machine.status != "blocked":
                    raise RuntimeError(f"invalid machine wake state for {machine_id}")
                machine.status = "idle"
                log("machine_available", machine_id=machine_id)
                continue
            if kind == "release":
                job_id = str(payload["job_id"])
                if job_id not in released and job_id not in pending_release:
                    pending_release.append(job_id)
                    pending_release.sort(key=lambda jid: (problem.planning_job(jid).release_time, problem.planning_job(jid).due_time, jid))
                if cfg.wip_cap is not None and current_wip() >= cfg.wip_cap:
                    log("job_release_held_conwip", job_id=job_id, wip=current_wip(), wip_cap=cfg.wip_cap)
                admit_pending()
                continue

            machine_id = str(payload["machine_id"])
            operation_id = str(payload["operation_id"])
            machine = machine_state[machine_id]
            state = op_state[operation_id]
            spec = problem.factory.operation(operation_id)
            if machine.operation_id != operation_id or machine.segment_start is None:
                raise RuntimeError(f"stale or inconsistent {kind} event for {operation_id}")

            elapsed = current_time - machine.segment_start
            if elapsed < -1e-12:
                raise RuntimeError("negative processing segment")
            elapsed = max(0.0, elapsed)
            if elapsed > 0:
                segments.append(ProcessingSegment(operation_id, spec.job_id, machine_id, machine.segment_start, current_time))
                productive[machine_id] += elapsed
                assert state.remaining is not None
                state.remaining = max(0.0, state.remaining - elapsed)

            if kind == "failure":
                if state.remaining is None or state.remaining <= 1e-9:
                    raise RuntimeError("failure event fired after operation finished")
                state.interruptions += 1
                machine.status = "down"
                machine.down_start = current_time
                machine.segment_start = None
                rel = cfg.reliability_for(machine_id)
                repair = float(max(1e-9, machine_rng[machine_id].exponential(rel.mttr)))
                log("machine_failed", job_id=spec.job_id, operation_id=operation_id, machine_id=machine_id,
                    repair_duration=repair, remaining_work=float(state.remaining))
                push(current_time + repair, "repair", machine_id=machine_id, operation_id=operation_id)
                continue

            if kind == "complete":
                if state.remaining is None or state.remaining > 1e-7:
                    raise RuntimeError(f"operation {operation_id} completed with remaining work {state.remaining}")
                state.remaining = 0.0
                state.finish = current_time
                machine.status = "idle"
                machine.operation_id = None
                machine.segment_start = None
                completed_ops += 1
                log("operation_completed", job_id=spec.job_id, operation_id=operation_id, machine_id=machine_id)
                next_index[spec.job_id] += 1
                job = problem.factory.job(spec.job_id)
                if next_index[spec.job_id] < len(job.operations):
                    ready.add(job.operations[next_index[spec.job_id]].operation_id)
                else:
                    completion[spec.job_id] = current_time
                    log("job_completed", job_id=spec.job_id)
                    admit_pending()
                continue

            raise RuntimeError(f"unknown event kind {kind}")

        # Repairs are handled in a second pass because they refer to machines
        # that deliberately have no active processing segment while down.
        for _, _, kind, payload in same_time:
            if kind != "repair":
                continue
            machine_id = str(payload["machine_id"])
            operation_id = str(payload["operation_id"])
            machine = machine_state[machine_id]
            state = op_state[operation_id]
            spec = problem.factory.operation(operation_id)
            if machine.status != "down" or machine.operation_id != operation_id or machine.down_start is None:
                raise RuntimeError(f"invalid repair state for {machine_id}")
            interval = DowntimeInterval(machine_id, machine.down_start, current_time)
            downtimes.append(interval)
            downtime_total[machine_id] += current_time - machine.down_start
            machine.down_start = None
            log("machine_repaired", job_id=spec.job_id, operation_id=operation_id, machine_id=machine_id)
            if state.remaining is None or state.remaining <= 0:
                raise RuntimeError("repaired operation has no remaining work")
            schedule_active_piece(machine_id, operation_id, current_time, resume=True)

    tardiness = {
        job.job_id: max(0.0, completion[job.job_id] - problem.planning_job(job.job_id).due_time)
        for job in problem.factory.jobs
    }
    operations = tuple(
        SimulatedOperation(
            op.operation_id,
            op.job_id,
            op.machine_id,
            op.sequence,
            op.processing_time,
            float(op_state[op.operation_id].realized_processing or 0.0),
            float(op_state[op.operation_id].first_start or 0.0),
            float(op_state[op.operation_id].finish or 0.0),
            op_state[op.operation_id].interruptions,
        )
        for job in problem.factory.jobs
        for op in job.operations
    )
    metrics = _metrics(problem, completion, tardiness, productive, downtime_total, actual_release)
    return SimulationResult(
        seed=cfg.seed,
        policy=policy.name,
        operations=operations,
        processing_segments=tuple(segments),
        downtime_intervals=tuple(downtimes),
        events=tuple(sim_events),
        job_completion=completion,
        job_tardiness=tardiness,
        machine_productive_time=productive,
        machine_downtime=downtime_total,
        metrics=metrics,
    )
