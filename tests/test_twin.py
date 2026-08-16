import pytest

from mdt.domain import EventType, JobStatus, MachineStatus, ManufacturingEvent, OperationStatus
from mdt.twin import TwinEngine, TwinStateError


def e(event_id, event_type, timestamp, **kwargs):
    return ManufacturingEvent(event_id, event_type, timestamp, **kwargs)


def test_release_start_complete_enforces_precedence(ft06):
    twin = TwinEngine(ft06)
    twin.apply(e("r0", EventType.JOB_RELEASED, 0, job_id="J0"))
    assert twin.operations["J0-O0"].status == OperationStatus.READY
    assert twin.operations["J0-O1"].status == OperationStatus.NOT_READY
    with pytest.raises(TwinStateError):
        twin.apply(e("bad", EventType.OPERATION_STARTED, 0, operation_id="J0-O1", machine_id="M0"))
    twin.apply(e("s0", EventType.OPERATION_STARTED, 0, operation_id="J0-O0", machine_id="M2"))
    twin.apply(e("c0", EventType.OPERATION_COMPLETED, 1, operation_id="J0-O0", machine_id="M2"))
    assert twin.operations["J0-O1"].status == OperationStatus.READY
    assert twin.machines["M2"].status == MachineStatus.IDLE


def test_machine_capacity_is_enforced(ft06):
    twin = TwinEngine(ft06)
    twin.apply(e("r0", EventType.JOB_RELEASED, 0, job_id="J0"))
    twin.apply(e("r2", EventType.JOB_RELEASED, 0, job_id="J2"))
    twin.apply(e("s0", EventType.OPERATION_STARTED, 0, operation_id="J0-O0", machine_id="M2"))
    with pytest.raises(TwinStateError):
        twin.apply(e("s2", EventType.OPERATION_STARTED, 0, operation_id="J2-O0", machine_id="M2"))


def test_machine_downtime_state_and_accounting(ft06):
    twin = TwinEngine(ft06)
    twin.apply(e("d", EventType.MACHINE_DOWN, 5, machine_id="M3"))
    assert twin.machines["M3"].status == MachineStatus.DOWN
    twin.apply(e("u", EventType.MACHINE_UP, 8, machine_id="M3"))
    assert twin.machines["M3"].status == MachineStatus.IDLE
    assert twin.machines["M3"].accumulated_downtime == 3.0


def test_event_ledger_rejects_machine_down_during_active_operation(ft06):
    twin = TwinEngine(ft06)
    twin.apply(e("r", EventType.JOB_RELEASED, 0, job_id="J0"))
    twin.apply(e("s", EventType.OPERATION_STARTED, 0, operation_id="J0-O0", machine_id="M2"))
    with pytest.raises(TwinStateError):
        twin.apply(e("d", EventType.MACHINE_DOWN, 0.5, machine_id="M2"))


def test_duplicate_and_backwards_events_rejected(ft06):
    twin = TwinEngine(ft06)
    twin.apply(e("r", EventType.JOB_RELEASED, 2, job_id="J0"))
    with pytest.raises(TwinStateError):
        twin.apply(e("r", EventType.JOB_RELEASED, 2, job_id="J1"))
    with pytest.raises(TwinStateError):
        twin.apply(e("x", EventType.JOB_RELEASED, 1, job_id="J1"))


def test_deterministic_replay(ft06):
    events = [
        e("r", EventType.JOB_RELEASED, 0, job_id="J0"),
        e("s", EventType.OPERATION_STARTED, 0, operation_id="J0-O0", machine_id="M2"),
        e("c", EventType.OPERATION_COMPLETED, 1, operation_id="J0-O0", machine_id="M2"),
    ]
    a = TwinEngine(ft06); b = TwinEngine(ft06)
    sa = a.replay(events); sb = b.replay(events)
    assert sa == sb
    assert sa.wip_jobs == 1
