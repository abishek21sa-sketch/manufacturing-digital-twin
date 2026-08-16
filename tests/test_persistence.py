import pytest
from sqlalchemy.exc import IntegrityError

from mdt.domain import EventType, ManufacturingEvent
from mdt.persistence import EventRepository
from mdt.twin import TwinEngine


def test_event_store_persists_and_recovers(tmp_path, ft06):
    url = f"sqlite:///{(tmp_path / 'events.db').as_posix()}"
    with EventRepository(url) as repo:
        events = [
            ManufacturingEvent("r", EventType.JOB_RELEASED, 0, job_id="J0"),
            ManufacturingEvent("s", EventType.OPERATION_STARTED, 0, operation_id="J0-O0", machine_id="M2"),
            ManufacturingEvent("c", EventType.OPERATION_COMPLETED, 1, operation_id="J0-O0", machine_id="M2"),
        ]
        for event in events:
            repo.append(event)
        assert repo.count() == 3
        persisted = repo.list_events()
    recovered = TwinEngine(ft06).replay(persisted)
    assert recovered.event_count == 3
    assert recovered.operations["J0-O0"].completed_at == 1


def test_event_id_unique_constraint(tmp_path):
    with EventRepository(f"sqlite:///{(tmp_path / 'events.db').as_posix()}") as repo:
        event = ManufacturingEvent("same", EventType.JOB_RELEASED, 0, job_id="J0")
        repo.append(event)
        with pytest.raises(IntegrityError):
            repo.append(event)


def test_event_repository_context_disposes_engine(tmp_path, monkeypatch):
    repo = EventRepository(f"sqlite:///{(tmp_path / 'cleanup.db').as_posix()}")
    disposed = {"called": 0}
    original_dispose = repo.engine.dispose

    def tracked_dispose(*args, **kwargs):
        disposed["called"] += 1
        return original_dispose(*args, **kwargs)

    monkeypatch.setattr(repo.engine, "dispose", tracked_dispose)
    with repo as opened:
        opened.append(ManufacturingEvent("cleanup", EventType.JOB_RELEASED, 0, job_id="J0"))
        assert opened.count() == 1

    assert disposed["called"] == 1


def test_decision_run_audit_and_human_disposition(tmp_path):
    from mdt.domain import HumanDisposition

    with EventRepository(f"sqlite:///{(tmp_path / 'audit.db').as_posix()}") as repo:
        repo.save_decision_run(
            run_id="run-1",
            decision_kind="recovery",
            twin_state_id="state-abc",
            twin_timestamp=12.0,
            twin_event_count=7,
            model_version="0.9.1",
            solver_backend="gurobi",
            data_version="ft06:public_benchmark",
            request_payload={"due_factor": 1.5},
            result_payload={"action": "stage schedule"},
            status="NOMINAL",
        )
        rows = repo.list_decision_runs(limit=5)
        assert len(rows) == 1
        assert rows[0]["twin_state_id"] == "state-abc"
        assert rows[0]["human_disposition"] == "pending"
        updated = repo.update_decision_disposition("run-1", HumanDisposition.DEFERRED, "await maintenance confirmation")
        assert updated["human_disposition"] == "deferred"
        assert updated["disposition_note"] == "await maintenance confirmation"
