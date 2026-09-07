from __future__ import annotations

from mdt.config import Settings
from mdt.data import load_orlib_instance
from mdt.persistence import EventRepository
from mdt.twin import TwinEngine


class TwinService:
    """Application service owning the twin model and durable event repository.

    The service has an explicit lifecycle because SQLite file handles must be
    released deterministically on Windows before temporary or runtime database
    files can be removed or replaced.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        source = settings.project_root / "data" / "external" / "orlib" / "jobshop1.txt"
        self.model = load_orlib_instance(source, settings.benchmark_instance)
        self.repository = EventRepository(settings.database_url, create_schema=settings.auto_create_schema)
        self.engine = TwinEngine(self.model)
        self.engine.replay(self.repository.list_events())
        self._closed = False

    def refresh(self) -> None:
        self.engine = TwinEngine(self.model)
        self.engine.replay(self.repository.list_events())

    def close(self) -> None:
        if not self._closed:
            self.repository.close()
            self._closed = True

    def __enter__(self) -> "TwinService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
