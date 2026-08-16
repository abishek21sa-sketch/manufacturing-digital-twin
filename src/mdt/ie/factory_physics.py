from __future__ import annotations

from dataclasses import dataclass
from math import exp

from mdt.domain import FactoryModel


def little_law(throughput_rate: float, mean_flow_time: float) -> float:
    if throughput_rate < 0 or mean_flow_time < 0:
        raise ValueError("throughput and flow time must be non-negative")
    return throughput_rate * mean_flow_time


def utilization(arrival_rate: float, effective_service_rate: float) -> float:
    if arrival_rate < 0:
        raise ValueError("arrival rate must be non-negative")
    if effective_service_rate <= 0:
        raise ValueError("service rate must be positive")
    return arrival_rate / effective_service_rate


def capacity_rate(available_time: float, effective_cycle_time: float) -> float:
    if available_time < 0:
        raise ValueError("available time must be non-negative")
    if effective_cycle_time <= 0:
        raise ValueError("cycle time must be positive")
    return available_time / effective_cycle_time


def takt_time(available_production_time: float, customer_demand: float) -> float:
    if available_production_time <= 0:
        raise ValueError("available production time must be positive")
    if customer_demand <= 0:
        raise ValueError("customer demand must be positive")
    return available_production_time / customer_demand


def oee(availability_fraction: float, performance_fraction: float, quality_fraction: float) -> float:
    values = (availability_fraction, performance_fraction, quality_fraction)
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("OEE components must be fractions in [0, 1]")
    return availability_fraction * performance_fraction * quality_fraction


def process_cycle_efficiency(value_added_time: float, total_lead_time: float) -> float:
    if value_added_time < 0 or total_lead_time <= 0 or value_added_time > total_lead_time:
        raise ValueError("invalid value-added / lead-time relationship")
    return value_added_time / total_lead_time


def jit_latest_release(due_time: float, remaining_touch_time: float, safety_buffer: float = 0.0) -> float:
    """Latest JIT-style release time that preserves touch time plus an explicit buffer."""
    if due_time < 0 or remaining_touch_time < 0 or safety_buffer < 0:
        raise ValueError("JIT times must be non-negative")
    return max(0.0, due_time - remaining_touch_time - safety_buffer)


def availability(mtbf: float, mttr: float) -> float:
    if mtbf <= 0 or mttr < 0:
        raise ValueError("MTBF must be positive and MTTR non-negative")
    return mtbf / (mtbf + mttr)


def reliability_exponential(t: float, mtbf: float) -> float:
    if t < 0 or mtbf <= 0:
        raise ValueError("time must be non-negative and MTBF positive")
    return exp(-t / mtbf)


def kingman_wait(arrival_rate: float, service_rate: float, ca2: float, cs2: float) -> float:
    if arrival_rate < 0 or service_rate <= 0 or ca2 < 0 or cs2 < 0:
        raise ValueError("invalid queue parameters")
    rho = arrival_rate / service_rate
    if rho >= 1:
        raise ValueError("Kingman approximation requires utilization < 1")
    mean_service_time = 1.0 / service_rate
    return (rho / (1.0 - rho)) * ((ca2 + cs2) / 2.0) * mean_service_time


@dataclass(frozen=True)
class ConstraintResult:
    machine_id: str
    workload: float
    share_of_total_work: float


def identify_constraint(model: FactoryModel) -> ConstraintResult:
    loads = {m.machine_id: 0.0 for m in model.machines}
    for job in model.jobs:
        for op in job.operations:
            loads[op.machine_id] += op.processing_time
    machine_id, workload = max(loads.items(), key=lambda kv: kv[1])
    return ConstraintResult(machine_id, workload, workload / model.total_work)


@dataclass(frozen=True)
class CapacityPlanRow:
    machine_id: str
    workload: float
    effective_available_time: float
    load_ratio: float
    capacity_gap: float


def capacity_plan(model: FactoryModel, horizon: float, availability_by_machine: dict[str, float] | None = None) -> tuple[CapacityPlanRow, ...]:
    if horizon <= 0:
        raise ValueError("planning horizon must be positive")
    availability_map = availability_by_machine or {}
    known = {m.machine_id for m in model.machines}
    unknown = set(availability_map) - known
    if unknown:
        raise ValueError(f"unknown availability machines: {sorted(unknown)}")
    loads = {m.machine_id: 0.0 for m in model.machines}
    for job in model.jobs:
        for op in job.operations:
            loads[op.machine_id] += op.processing_time
    rows = []
    for machine in model.machines:
        a = float(availability_map.get(machine.machine_id, 1.0))
        if a <= 0 or a > 1:
            raise ValueError("machine availability must be in (0, 1]")
        effective = horizon * a
        load = loads[machine.machine_id]
        rows.append(CapacityPlanRow(machine.machine_id, load, effective, load / effective, effective - load))
    return tuple(rows)


@dataclass(frozen=True)
class DynamicBottleneckResult:
    machine_id: str
    productive_utilization: float
    downtime_fraction: float
    pressure_index: float


def dynamic_bottleneck(machine_productive_time: dict[str, float], machine_downtime: dict[str, float], horizon: float) -> DynamicBottleneckResult:
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if set(machine_productive_time) != set(machine_downtime):
        raise ValueError("productive-time and downtime machine sets must match")
    if not machine_productive_time:
        raise ValueError("machine metrics are required")
    rows = []
    for machine_id in sorted(machine_productive_time):
        productive = float(machine_productive_time[machine_id])
        downtime = float(machine_downtime[machine_id])
        if productive < 0 or downtime < 0:
            raise ValueError("machine time metrics must be non-negative")
        productive_util = min(1.0, productive / horizon)
        down_fraction = min(1.0, downtime / horizon)
        # Pressure combines productive saturation with capacity lost to downtime.
        pressure = productive_util + down_fraction
        rows.append(DynamicBottleneckResult(machine_id, productive_util, down_fraction, pressure))
    return max(rows, key=lambda row: (row.pressure_index, row.productive_utilization, row.machine_id))
