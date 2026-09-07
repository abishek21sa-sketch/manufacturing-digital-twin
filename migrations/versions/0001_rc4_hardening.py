"""Create the production event, decision and ingestion ledger schema."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_rc4_hardening"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manufacturing_events",
        sa.Column("sequence_no", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_timestamp", sa.Float(), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("operation_id", sa.String(length=128), nullable=True),
        sa.Column("machine_id", sa.String(length=128), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("sequence_no"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index("ix_manufacturing_events_event_id", "manufacturing_events", ["event_id"], unique=True)
    op.create_index("ix_manufacturing_events_event_timestamp", "manufacturing_events", ["event_timestamp"])

    op.create_table(
        "decision_runs",
        sa.Column("sequence_no", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("created_at_utc", sa.String(length=64), nullable=False),
        sa.Column("decision_kind", sa.String(length=64), nullable=False),
        sa.Column("twin_state_id", sa.String(length=64), nullable=False),
        sa.Column("twin_timestamp", sa.Float(), nullable=False),
        sa.Column("twin_event_count", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("solver_backend", sa.String(length=64), nullable=False),
        sa.Column("data_version", sa.String(length=128), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("human_disposition", sa.String(length=32), nullable=False),
        sa.Column("disposition_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("sequence_no"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_decision_runs_run_id", "decision_runs", ["run_id"], unique=True)
    op.create_index("ix_decision_runs_decision_kind", "decision_runs", ["decision_kind"])
    op.create_index("ix_decision_runs_twin_state_id", "decision_runs", ["twin_state_id"])

    op.create_table(
        "event_ingestion_batches",
        sa.Column("sequence_no", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("source_system", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at_utc", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("sequence_no"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_event_ingestion_batches_idempotency_key", "event_ingestion_batches", ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_event_ingestion_batches_idempotency_key", table_name="event_ingestion_batches")
    op.drop_table("event_ingestion_batches")
    op.drop_index("ix_decision_runs_twin_state_id", table_name="decision_runs")
    op.drop_index("ix_decision_runs_decision_kind", table_name="decision_runs")
    op.drop_index("ix_decision_runs_run_id", table_name="decision_runs")
    op.drop_table("decision_runs")
    op.drop_index("ix_manufacturing_events_event_timestamp", table_name="manufacturing_events")
    op.drop_index("ix_manufacturing_events_event_id", table_name="manufacturing_events")
    op.drop_table("manufacturing_events")
