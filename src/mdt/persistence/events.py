from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import Float, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

from mdt.domain import EventType, HumanDisposition, ManufacturingEvent


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "manufacturing_events"
    sequence_no: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_timestamp: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(String(128))
    operation_id: Mapped[str | None] = mapped_column(String(128))
    machine_id: Mapped[str | None] = mapped_column(String(128))
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class DecisionRunRow(Base):
    __tablename__ = "decision_runs"
    sequence_no: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    created_at_utc: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    twin_state_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    twin_timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    twin_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    solver_backend: Mapped[str] = mapped_column(String(64), nullable=False)
    data_version: Mapped[str] = mapped_column(String(128), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    human_disposition: Mapped[str] = mapped_column(String(32), nullable=False, default=HumanDisposition.PENDING.value)
    disposition_note: Mapped[str | None] = mapped_column(Text)


class IngestionBatchRow(Base):
    __tablename__ = "event_ingestion_batches"
    sequence_no: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at_utc: Mapped[str] = mapped_column(String(64), nullable=False)


def _ingestion_request_hash(
    events: list[ManufacturingEvent], *, source_system: str, schema_version: str
) -> str:
    canonical_events = [
        {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "timestamp": event.timestamp,
            "job_id": event.job_id,
            "operation_id": event.operation_id,
            "machine_id": event.machine_id,
            "payload": event.payload,
        }
        for event in events
    ]
    canonical = json.dumps(
        {"source_system": source_system, "schema_version": schema_version, "events": canonical_events},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EventRepository:
    def __init__(self, database_url: str, *, create_schema: bool = True):
        self.engine = create_engine(database_url, future=True)
        self.create_schema = create_schema
        if create_schema:
            Base.metadata.create_all(self.engine)

    def append(self, event: ManufacturingEvent) -> None:
        with Session(self.engine) as session:
            row = EventRow(
                event_id=event.event_id,
                event_type=event.event_type.value,
                event_timestamp=event.timestamp,
                job_id=event.job_id,
                operation_id=event.operation_id,
                machine_id=event.machine_id,
                payload_json=json.dumps(event.payload, sort_keys=True),
            )
            session.add(row)
            session.commit()

    def append_many(
        self,
        events: list[ManufacturingEvent],
        *,
        source_system: str,
        schema_version: str,
        idempotency_key: str,
    ) -> dict:
        if not events:
            raise ValueError("at least one event is required")
        event_ids = [event.event_id for event in events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event_id must be unique within an ingestion batch")
        request_hash = _ingestion_request_hash(
            events, source_system=source_system, schema_version=schema_version
        )
        with Session(self.engine) as session:
            with session.begin():
                existing_batch = session.scalar(
                    select(IngestionBatchRow).where(IngestionBatchRow.idempotency_key == idempotency_key)
                )
                if existing_batch is not None:
                    if existing_batch.request_hash != request_hash:
                        raise ValueError("idempotency key already exists with a different request")
                    return json.loads(existing_batch.response_json)
                existing_ids = set(
                    session.scalars(select(EventRow.event_id).where(EventRow.event_id.in_(event_ids))).all()
                )
                if existing_ids:
                    raise ValueError(f"event_id already exists: {', '.join(sorted(existing_ids))}")
                response = {
                    "status": "accepted",
                    "idempotency_key": idempotency_key,
                    "source_system": source_system,
                    "schema_version": schema_version,
                    "accepted_event_ids": event_ids,
                    "accepted_count": len(events),
                }
                for event in events:
                    session.add(
                        EventRow(
                            event_id=event.event_id,
                            event_type=event.event_type.value,
                            event_timestamp=event.timestamp,
                            job_id=event.job_id,
                            operation_id=event.operation_id,
                            machine_id=event.machine_id,
                            payload_json=json.dumps(event.payload, sort_keys=True),
                        )
                    )
                session.add(
                    IngestionBatchRow(
                        idempotency_key=idempotency_key,
                        source_system=source_system,
                        schema_version=schema_version,
                        accepted_count=len(events),
                        response_json=json.dumps(response, sort_keys=True),
                        request_hash=request_hash,
                        created_at_utc=datetime.now(timezone.utc).isoformat(),
                    )
                )
                return response

    def list_events(self) -> list[ManufacturingEvent]:
        with Session(self.engine) as session:
            rows = session.scalars(select(EventRow).order_by(EventRow.sequence_no)).all()
        return [
            ManufacturingEvent(
                event_id=row.event_id,
                event_type=EventType(row.event_type),
                timestamp=row.event_timestamp,
                job_id=row.job_id,
                operation_id=row.operation_id,
                machine_id=row.machine_id,
                payload=json.loads(row.payload_json),
            )
            for row in rows
        ]

    def count(self) -> int:
        return len(self.list_events())

    def ingestion_batch(
        self,
        idempotency_key: str,
        *,
        events: list[ManufacturingEvent] | None = None,
        source_system: str | None = None,
        schema_version: str | None = None,
    ) -> dict | None:
        with Session(self.engine) as session:
            row = session.scalar(select(IngestionBatchRow).where(IngestionBatchRow.idempotency_key == idempotency_key))
        if row is None:
            return None
        if events is not None and source_system is not None and schema_version is not None:
            request_hash = _ingestion_request_hash(
                events, source_system=source_system, schema_version=schema_version
            )
            if row.request_hash != request_hash:
                raise ValueError("idempotency key already exists with a different request")
        return json.loads(row.response_json)

    def healthcheck(self) -> dict:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database_url_scheme": self.engine.url.drivername}

    def schema_info(self) -> dict:
        return {
            "revision": "mdt-rc4-hardening",
            "tables": ["manufacturing_events", "decision_runs", "event_ingestion_batches"],
            "migration_policy": "production deployments run reviewed Alembic migrations; create_all is local-only compatibility",
            "auto_create_schema": self.create_schema,
        }

    def save_decision_run(
        self,
        *,
        run_id: str,
        decision_kind: str,
        twin_state_id: str,
        twin_timestamp: float,
        twin_event_count: int,
        model_version: str,
        solver_backend: str,
        data_version: str,
        request_payload: dict,
        result_payload: dict,
        status: str,
    ) -> None:
        with Session(self.engine) as session:
            session.add(
                DecisionRunRow(
                    run_id=run_id,
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    decision_kind=decision_kind,
                    twin_state_id=twin_state_id,
                    twin_timestamp=twin_timestamp,
                    twin_event_count=twin_event_count,
                    model_version=model_version,
                    solver_backend=solver_backend,
                    data_version=data_version,
                    request_json=json.dumps(request_payload, sort_keys=True),
                    result_json=json.dumps(result_payload, sort_keys=True),
                    status=status,
                    human_disposition=HumanDisposition.PENDING.value,
                )
            )
            session.commit()

    def list_decision_runs(self, limit: int = 100) -> list[dict]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with Session(self.engine) as session:
            rows = session.scalars(select(DecisionRunRow).order_by(DecisionRunRow.sequence_no.desc()).limit(limit)).all()
        return [
            {
                "run_id": row.run_id,
                "created_at_utc": row.created_at_utc,
                "decision_kind": row.decision_kind,
                "twin_state_id": row.twin_state_id,
                "twin_timestamp": row.twin_timestamp,
                "twin_event_count": row.twin_event_count,
                "model_version": row.model_version,
                "solver_backend": row.solver_backend,
                "data_version": row.data_version,
                "request": json.loads(row.request_json),
                "result": json.loads(row.result_json),
                "status": row.status,
                "human_disposition": row.human_disposition,
                "disposition_note": row.disposition_note,
            }
            for row in rows
        ]

    def update_decision_disposition(self, run_id: str, disposition: HumanDisposition, note: str | None = None) -> dict:
        if disposition == HumanDisposition.PENDING:
            raise ValueError("human disposition update must be approved, rejected, or deferred")
        with Session(self.engine) as session:
            row = session.scalar(select(DecisionRunRow).where(DecisionRunRow.run_id == run_id))
            if row is None:
                raise KeyError(run_id)
            row.human_disposition = disposition.value
            row.disposition_note = note
            session.commit()
            session.refresh(row)
            return {
                "run_id": row.run_id,
                "human_disposition": row.human_disposition,
                "disposition_note": row.disposition_note,
            }

    def close(self) -> None:
        """Release pooled database connections and OS file handles.

        SQLite keeps pooled connections open until the SQLAlchemy engine is
        disposed. On Windows that can keep the database file locked and
        prevent temporary-directory cleanup.
        """
        self.engine.dispose()

    def __enter__(self) -> "EventRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
