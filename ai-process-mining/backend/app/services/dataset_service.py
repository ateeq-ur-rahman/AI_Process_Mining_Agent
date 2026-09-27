"""What happens when a file is uploaded: save it, validate, normalize, store the events,
and run the engine once so the first page load is fast.

It all happens inside the request. A 100k-event file takes a few seconds, which
didn't justify a job queue.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import UploadRejected
from app.core.logging import log_event
from app.models import Dataset
from app.repositories.datasets import DatasetRepository
from app.services.analysis_service import compute_and_store
from app.services.ingestion.csv_validator import parse_and_validate
from app.services.normalization.normalizer import normalize_events

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = (".csv", ".txt")
# Browsers label CSVs inconsistently (Windows machines with Excel send vnd.ms-excel).
# This only filters out obvious non-CSV uploads; the parser decides what's valid.
ALLOWED_CONTENT_TYPES = {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel",
                         "application/octet-stream", ""}


def safe_display_name(filename: str | None) -> str:
    """Strip any path components and unsafe characters; never used to build file paths."""
    base = os.path.basename((filename or "upload.csv").replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._ ()-]", "_", base).strip(" .") or "upload.csv"
    return base[:200]


def check_upload(filename: str | None, content_type: str | None, size: int) -> None:
    settings = get_settings()
    name = (filename or "").lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        raise UploadRejected(f"Expected a .csv file, got '{safe_display_name(filename)}'.")
    if (content_type or "").split(";")[0].strip().lower() not in ALLOWED_CONTENT_TYPES:
        raise UploadRejected(f"Unsupported content type '{content_type}'. Upload a CSV file.")
    if size > settings.max_upload_bytes:
        raise UploadRejected(f"File is larger than the {settings.max_upload_mb:g} MB limit.", status_code=413)
    if size == 0:
        raise UploadRejected("The file is empty.")


def ingest(session: Session, filename: str | None, content: bytes) -> Dataset:
    settings = get_settings()
    repo = DatasetRepository(session)
    t0 = time.perf_counter()

    dataset_id = uuid.uuid4().hex
    os.makedirs(settings.upload_dir, exist_ok=True)
    # Server-generated path inside the upload dir; the client filename never touches the filesystem.
    stored_path = os.path.join(settings.upload_dir, f"{dataset_id}.csv")
    with open(stored_path, "wb") as fh:
        fh.write(content)
    os.chmod(stored_path, 0o600)  # data file only; never executed

    ds = repo.create(id=dataset_id, name=safe_display_name(filename), stored_path=stored_path,
                     file_size_bytes=len(content), status="processing")
    try:
        parsed = parse_and_validate(content, default_tz=settings.default_timezone, max_rows=settings.max_rows)
        if parsed.events.empty:
            raise UploadRejected("No valid events remain after validation.", details={"validation": parsed.report})
        events, notes = normalize_events(parsed.events)
        report = parsed.report | notes
        repo.insert_invalid_rows(dataset_id, parsed.invalid_rows)
        repo.insert_events(dataset_id, events)
        repo.update(ds, validation_report=report, column_mapping=parsed.column_mapping)
        compute_and_store(session, dataset_id, events)
        repo.update(ds, status="ready")
    except UploadRejected as exc:
        repo.update(ds, status="failed", error=exc.message,
                    validation_report=exc.details.get("validation") if exc.details else None)
        raise
    except Exception as exc:  # noqa: BLE001 — record and surface a clean error
        logger.exception("ingest.failed")
        # Keep internals out of a message the UI shows; the log has the traceback.
        repo.update(ds, status="failed",
                    error=f"Processing failed with an unexpected {type(exc).__name__}. See the backend log.")
        raise
    finally:
        log_event(logger, "dataset.ingest", dataset_id=dataset_id, bytes=len(content), status=ds.status,
                  rows_processed=(ds.validation_report or {}).get("total_rows"),
                  processing_ms=int((time.perf_counter() - t0) * 1000))
    return ds
