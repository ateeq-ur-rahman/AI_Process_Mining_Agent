"""Persistence for datasets, events and invalid rows. No business logic here."""
from __future__ import annotations

import io
import json

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import AIRun, AnalysisResult, Dataset, Event, InvalidRow

EVENT_COLUMNS = ["source_row", "case_id", "original_activity", "activity", "timestamp", "start_timestamp",
                 "resource", "department", "status", "amount", "customer_id", "location", "priority", "extra"]


def _db_value(value):
    """pandas uses NaN/NaT/pd.NA for missing values; the database wants NULL."""
    if isinstance(value, (dict, list)):  # the `extra` column; pd.isna would test it element-wise
        return value
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


class DatasetRepository:
    """All database access for datasets and the rows that hang off them."""

    def __init__(self, session: Session):
        self.s = session

    # datasets
    def create(self, **kwargs) -> Dataset:
        ds = Dataset(**kwargs)
        self.s.add(ds)
        self.s.commit()
        return ds

    def get(self, dataset_id: str) -> Dataset:
        ds = self.s.get(Dataset, dataset_id)
        if ds is None:
            raise NotFoundError(f"Dataset '{dataset_id}' not found.")
        return ds

    def list(self) -> list[Dataset]:
        return list(self.s.scalars(select(Dataset).order_by(Dataset.created_at.desc())))

    def update(self, ds: Dataset, **fields) -> Dataset:
        for k, v in fields.items():
            setattr(ds, k, v)
        self.s.commit()
        return ds

    def delete(self, ds: Dataset) -> None:
        for model in (Event, InvalidRow, AnalysisResult, AIRun):
            self.s.execute(delete(model).where(model.dataset_id == ds.id))
        self.s.delete(ds)
        self.s.commit()

    # events
    def insert_events(self, dataset_id: str, events: pd.DataFrame, chunk: int = 5000) -> int:
        df = events.reindex(columns=EVENT_COLUMNS)
        bind = self.s.get_bind()
        if bind.dialect.name == "postgresql":
            return self._copy_events_pg(dataset_id, df)
        records = df.to_dict("records")
        for i in range(0, len(records), chunk):
            batch = [{k: _db_value(v) for k, v in r.items()} | {"dataset_id": dataset_id} for r in records[i:i + chunk]]
            self.s.execute(insert(Event), batch)
        self.s.commit()
        return len(records)

    def _copy_events_pg(self, dataset_id: str, df: pd.DataFrame) -> int:
        """Fast path for PostgreSQL: COPY instead of row-by-row INSERT."""
        cols = ["dataset_id", *EVENT_COLUMNS]
        conn = self.s.connection().connection  # DBAPI (psycopg3) connection
        with conn.cursor() as cur:
            with cur.copy(f"COPY events ({', '.join(cols)}) FROM STDIN") as cp:
                for r in df.itertuples(index=False):
                    row = [dataset_id]
                    for c, v in zip(EVENT_COLUMNS, r):
                        v = _db_value(v)
                        if c == "extra" and v is not None:
                            v = json.dumps(v)
                        row.append(v)
                    cp.write_row(row)
        self.s.commit()
        return len(df)

    def load_events(self, dataset_id: str) -> pd.DataFrame:
        stmt = select(*[getattr(Event, c) for c in EVENT_COLUMNS if c != "extra"]).where(
            Event.dataset_id == dataset_id)
        with self.s.get_bind().connect() as conn:
            df = pd.read_sql(stmt, conn)
        for c in ("timestamp", "start_timestamp"):
            df[c] = pd.to_datetime(df[c], utc=True)
        df["case_id"] = df["case_id"].astype(str)
        return df

    # invalid rows
    def insert_invalid_rows(self, dataset_id: str, rows: list[dict], chunk: int = 5000) -> None:
        for i in range(0, len(rows), chunk):
            self.s.execute(insert(InvalidRow), [r | {"dataset_id": dataset_id} for r in rows[i:i + chunk]])
        self.s.commit()

    def invalid_rows(self, dataset_id: str, issue: str | None, offset: int, limit: int) -> tuple[int, list[InvalidRow]]:
        base = select(InvalidRow).where(InvalidRow.dataset_id == dataset_id)
        if issue:
            base = base.where(InvalidRow.issue == issue)
        total = self.s.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = list(self.s.scalars(base.order_by(InvalidRow.source_row).offset(offset).limit(limit)))
        return total, rows

    def all_invalid_rows(self, dataset_id: str) -> list[InvalidRow]:
        return list(self.s.scalars(select(InvalidRow).where(InvalidRow.dataset_id == dataset_id)
                                   .order_by(InvalidRow.source_row)))

    # analysis results
    def save_analysis(self, dataset_id: str, config_hash: str, engine_version: str, result: dict, ms: int) -> None:
        self.s.execute(delete(AnalysisResult).where(AnalysisResult.dataset_id == dataset_id,
                                                    AnalysisResult.config_hash == config_hash))
        self.s.add(AnalysisResult(dataset_id=dataset_id, config_hash=config_hash, engine_version=engine_version,
                                  result=result, processing_ms=ms))
        self.s.commit()

    # AI runs
    def save_ai_run(self, **fields) -> AIRun:
        run = AIRun(**fields)
        self.s.add(run)
        self.s.commit()
        return run

    def latest_ai_run(self, dataset_id: str, kind: str) -> AIRun | None:
        return self.s.scalars(select(AIRun).where(AIRun.dataset_id == dataset_id, AIRun.kind == kind,
                                                  AIRun.output.isnot(None))
                              .order_by(AIRun.created_at.desc()).limit(1)).first()

    def ai_runs(self, dataset_id: str, limit: int = 50) -> list[AIRun]:
        return list(self.s.scalars(select(AIRun).where(AIRun.dataset_id == dataset_id)
                                   .order_by(AIRun.created_at.desc()).limit(limit)))


def to_csv_bytes(rows: list[dict], columns: list[str]) -> bytes:
    """CSV export with spreadsheet formula-injection protection."""
    import csv

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    for r in rows:
        w.writerow([escape_formula(r.get(c)) for c in columns])
    return buf.getvalue().encode("utf-8")


def escape_formula(value) -> str:
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s
