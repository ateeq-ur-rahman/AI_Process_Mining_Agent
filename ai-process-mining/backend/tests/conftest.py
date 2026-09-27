import os
import tempfile

import pandas as pd
import pytest

# Set before any app module reads settings. Tests never talk to a real LLM.
_tmp = tempfile.mkdtemp(prefix="apm_test_")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["UPLOAD_DIR"] = os.path.join(_tmp, "uploads")
os.environ["LLM_PROVIDER"] = "none"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["LOG_LEVEL"] = "WARNING"

from app.services.normalization.normalizer import normalize_events  # noqa: E402


def make_events(rows):
    """rows: [(case_id, activity, 'YYYY-mm-dd HH:MM[:SS]', resource?)] -> normalized events frame."""
    recs = []
    for i, r in enumerate(rows):
        recs.append({"source_row": i + 2, "case_id": r[0], "original_activity": r[1],
                     "timestamp": pd.Timestamp(r[2], tz="UTC"), "start_timestamp": pd.NaT,
                     "resource": r[3] if len(r) > 3 else None, "department": None, "status": None,
                     "amount": float("nan"), "customer_id": None, "location": None, "priority": None, "extra": None})
    df = pd.DataFrame(recs)
    df["start_timestamp"] = pd.to_datetime(df["start_timestamp"], utc=True)
    ev, _ = normalize_events(df)
    return ev


def hours(base: str, *offsets):
    t0 = pd.Timestamp(base)
    return [(t0 + pd.Timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S") for h in offsets]


@pytest.fixture
def simple_log():
    """10 cases A→B→C→D (2 have rework, 1 skips B, 1 has unexpected X, 1 loops C)."""
    rows = []
    for i in range(6):
        t = hours("2026-01-01 08:00", 0, 1, 3, 4)
        rows += [(f"C{i}", a, ts) for a, ts in zip("ABCD", t)]
    t = hours("2026-01-02 08:00", 0, 1, 2, 3, 4, 5)
    rows += [("R1", a, ts) for a, ts in zip(["A", "B", "C", "B", "C", "D"], t)]
    rows += [("R2", a, ts) for a, ts in zip(["A", "B", "C", "B", "C", "D"], t)]
    t = hours("2026-01-03 08:00", 0, 2, 3)
    rows += [("S1", a, ts) for a, ts in zip(["A", "C", "D"], t)]
    t = hours("2026-01-03 08:00", 0, 1, 2, 3, 4)
    rows += [("U1", a, ts) for a, ts in zip(["A", "B", "X", "C", "D"], t)]
    return rows


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.core.db import Base, init_engine
    from app.main import app
    from app.services.analysis_service import cache

    engine = init_engine("sqlite://")
    Base.metadata.create_all(engine)
    cache._items.clear()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
