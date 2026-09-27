"""Database tables. Column types stay portable so the same models run on PostgreSQL
and on SQLite (tests, and quick local runs without a database server)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# JSONB on PostgreSQL (indexable, compact), plain JSON elsewhere.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="processing")  # processing | ready | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_report: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    column_mapping: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Event(Base):
    """One valid, normalized event. Original activity text and extra columns are preserved."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(32), ForeignKey("datasets.id", ondelete="CASCADE"))
    source_row: Mapped[int] = mapped_column(Integer)
    case_id: Mapped[str] = mapped_column(String(255))
    original_activity: Mapped[str] = mapped_column(String(255))
    activity: Mapped[str] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    start_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resource: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    __table_args__ = (
        Index("ix_events_dataset_case_ts", "dataset_id", "case_id", "timestamp"),
        Index("ix_events_dataset_activity", "dataset_id", "activity"),
    )


class InvalidRow(Base):
    """A source row excluded from analysis, with the reason. Nothing is dropped silently."""
    __tablename__ = "invalid_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(32), ForeignKey("datasets.id", ondelete="CASCADE"))
    source_row: Mapped[int] = mapped_column(Integer)
    issue: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    __table_args__ = (Index("ix_invalid_rows_dataset", "dataset_id"),)


class AnalysisResult(Base):
    """Engine output per dataset and config. Pages are served from the in-memory cache;
    this is the persisted record of what was computed, with which engine version."""
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(32), ForeignKey("datasets.id", ondelete="CASCADE"))
    config_hash: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict] = mapped_column(JSONType)
    processing_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_analysis_dataset_cfg", "dataset_id", "config_hash"),)


class AIRun(Base):
    """One row per report or chat answer, whether the LLM wrote it or the rule-based fallback did."""
    __tablename__ = "ai_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(String(32), ForeignKey("datasets.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # report | query
    mode: Mapped[str] = mapped_column(String(16))  # llm | deterministic
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_ai_runs_dataset", "dataset_id", "created_at"),)
