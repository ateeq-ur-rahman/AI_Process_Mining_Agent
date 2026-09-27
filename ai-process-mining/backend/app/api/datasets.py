from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.serialize import events_to_records
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import NotFoundError, UploadRejected
from app.repositories.datasets import DatasetRepository, to_csv_bytes
from app.schemas.api import DatasetOut
from app.services.analysis_service import cache, get_analysis
from app.services.dataset_service import check_upload, ingest
from app.services.engine import deviation_records
from app.services.stats import round_or_none, trace_text

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _out(ds) -> DatasetOut:
    return DatasetOut.model_validate(ds, from_attributes=True)


@router.post("/upload", response_model=DatasetOut, status_code=201)
def upload(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """Upload an event-log CSV (required columns: case_id, activity, timestamp)."""
    limit = get_settings().max_upload_bytes
    content = file.file.read(limit + 1)
    check_upload(file.filename, file.content_type, len(content))
    return _out(ingest(session, file.filename, content))


@router.post("/sample", response_model=DatasetOut, status_code=201)
def load_sample(session: Session = Depends(get_session)):
    """Load the bundled SYNTHETIC Order-to-Cash demonstration dataset."""
    path = os.environ.get("SAMPLE_DATA_PATH", "/app/data/sample_order_to_cash.csv")
    if not os.path.isfile(path):
        raise UploadRejected("Sample dataset is not available on the server.", status_code=404)
    with open(path, "rb") as fh:
        content = fh.read()
    return _out(ingest(session, "sample_order_to_cash (synthetic).csv", content))


@router.get("", response_model=list[DatasetOut])
def list_datasets(session: Session = Depends(get_session)):
    return [_out(d) for d in DatasetRepository(session).list()]


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, session: Session = Depends(get_session)):
    return _out(DatasetRepository(session).get(dataset_id))


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, session: Session = Depends(get_session)):
    repo = DatasetRepository(session)
    ds = repo.get(dataset_id)
    upload_dir = os.path.realpath(get_settings().upload_dir)
    path = os.path.realpath(ds.stored_path)
    if path.startswith(upload_dir + os.sep) and os.path.isfile(path):
        os.remove(path)
    repo.delete(ds)
    cache.drop_dataset(dataset_id)
    return Response(status_code=204)


@router.get("/{dataset_id}/validation")
def validation(dataset_id: str, session: Session = Depends(get_session)):
    ds = DatasetRepository(session).get(dataset_id)
    return {"dataset_id": ds.id, "status": ds.status, "error": ds.error, "report": ds.validation_report,
            "column_mapping": ds.column_mapping}


@router.get("/{dataset_id}/validation/invalid-rows")
def invalid_rows(dataset_id: str, issue: str | None = None, offset: int = Query(0, ge=0),
                 limit: int = Query(100, ge=1, le=1000), session: Session = Depends(get_session)):
    repo = DatasetRepository(session)
    repo.get(dataset_id)
    total, rows = repo.invalid_rows(dataset_id, issue, offset, limit)
    return {"total": total, "offset": offset, "limit": limit,
            "items": [{"source_row": r.source_row, "issue": r.issue, "detail": r.detail, "raw": r.raw} for r in rows]}


@router.get("/{dataset_id}/validation/invalid-rows.csv")
def invalid_rows_csv(dataset_id: str, session: Session = Depends(get_session)):
    repo = DatasetRepository(session)
    repo.get(dataset_id)
    rows = repo.all_invalid_rows(dataset_id)
    raw_cols: list[str] = []
    for r in rows:
        for k in (r.raw or {}):
            if k not in raw_cols and k != "fields":
                raw_cols.append(k)
    records = []
    for r in rows:
        raw = r.raw or {}
        rec = {"source_row": r.source_row, "issue": r.issue, "detail": r.detail} | {k: raw.get(k) for k in raw_cols}
        if "fields" in raw:
            rec["raw_fields"] = " | ".join(map(str, raw["fields"]))
        records.append(rec)
    cols = ["source_row", "issue", "detail", *raw_cols, "raw_fields"]
    return Response(to_csv_bytes(records, cols), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="invalid_rows_{dataset_id[:8]}.csv"'})


@router.get("/{dataset_id}/cases/{case_id}")
def case_detail(dataset_id: str, case_id: str, session: Session = Depends(get_session)):
    er = get_analysis(session, dataset_id)
    ev = er.ev[er.ev["case_id"] == case_id]
    if ev.empty:
        raise NotFoundError(f"Case '{case_id}' not found.")
    tr = er.traces[er.traces["case_id"] == case_id].iloc[0]
    devs = er.deviations[er.deviations["case_id"] == case_id]
    return {"case_id": case_id, "variant_id": tr["variant_id"], "trace": list(tr["trace"]),
            "trace_text": trace_text(tr["trace"]), "duration_hours": round_or_none(tr["duration_h"]),
            "events": events_to_records(ev), "deviations": deviation_records(devs)}


@router.get("/{dataset_id}/events")
def events(dataset_id: str, activity: str | None = None, source: str | None = None, target: str | None = None,
           resource: str | None = None, sort: str = Query("wait_desc", pattern="^(wait_desc|time_asc)$"),
           offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
           session: Session = Depends(get_session)):
    """Underlying events for drill-down (by activity, transition source→target, or resource)."""
    er = get_analysis(session, dataset_id)
    ev = er.ev
    if activity:
        ev = ev[ev["activity"] == activity]
    if target:
        ev = ev[ev["activity"] == target]
    if source:
        ev = ev[ev["prev_activity"] == source]
    if resource:
        ev = ev[ev["resource"] == resource]
    ev = ev.sort_values("wait_h", ascending=False, na_position="last") if sort == "wait_desc" \
        else ev.sort_values("timestamp")
    return {"total": int(len(ev)), "offset": offset, "limit": limit,
            "items": events_to_records(ev.iloc[offset:offset + limit])}
