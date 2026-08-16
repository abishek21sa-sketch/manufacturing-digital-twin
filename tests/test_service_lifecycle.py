from mdt.config import Settings
from mdt.service import TwinService


def test_twin_service_context_disposes_repository(tmp_path, root, monkeypatch):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'service.db').as_posix()}",
        benchmark_instance="ft06",
        project_root=root,
    )
    service = TwinService(settings)
    disposed = {"called": 0}
    original_dispose = service.repository.engine.dispose

    def tracked_dispose(*args, **kwargs):
        disposed["called"] += 1
        return original_dispose(*args, **kwargs)

    monkeypatch.setattr(service.repository.engine, "dispose", tracked_dispose)
    with service:
        assert service.model.operation_count == 36
    service.close()  # idempotent; must not dispose twice
    assert disposed["called"] == 1
