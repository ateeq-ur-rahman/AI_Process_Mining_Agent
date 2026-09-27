"""Initial schema: datasets, events, invalid_rows, analysis_results, ai_runs

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("stored_path", sa.String(512), nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("validation_report", _json(), nullable=True),
        sa.Column("column_mapping", _json(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("dataset_id", sa.String(32), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_row", sa.Integer, nullable=False),
        sa.Column("case_id", sa.String(255), nullable=False),
        sa.Column("original_activity", sa.String(255), nullable=False),
        sa.Column("activity", sa.String(255), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resource", sa.String(255)),
        sa.Column("department", sa.String(255)),
        sa.Column("status", sa.String(255)),
        sa.Column("amount", sa.Float),
        sa.Column("customer_id", sa.String(255)),
        sa.Column("location", sa.String(255)),
        sa.Column("priority", sa.String(255)),
        sa.Column("extra", _json(), nullable=True),
    )
    op.create_index("ix_events_dataset_case_ts", "events", ["dataset_id", "case_id", "timestamp"])
    op.create_index("ix_events_dataset_activity", "events", ["dataset_id", "activity"])
    op.create_table(
        "invalid_rows",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("dataset_id", sa.String(32), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_row", sa.Integer, nullable=False),
        sa.Column("issue", sa.String(64), nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("raw", _json(), nullable=True),
    )
    op.create_index("ix_invalid_rows_dataset", "invalid_rows", ["dataset_id"])
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("dataset_id", sa.String(32), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("result", _json(), nullable=False),
        sa.Column("processing_ms", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analysis_dataset_cfg", "analysis_results", ["dataset_id", "config_hash"])
    op.create_table(
        "ai_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("dataset_id", sa.String(32), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("model", sa.String(128)),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("input_chars", sa.Integer, nullable=False),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("llm_calls", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float),
        sa.Column("question", sa.Text),
        sa.Column("output", _json(), nullable=True),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_runs_dataset", "ai_runs", ["dataset_id", "created_at"])


def downgrade() -> None:
    for t in ("ai_runs", "analysis_results", "invalid_rows", "events", "datasets"):
        op.drop_table(t)
