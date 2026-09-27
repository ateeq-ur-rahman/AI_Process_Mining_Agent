from __future__ import annotations

import pandas as pd

from app.services.stats import round_or_none

EVENT_FIELDS = ["case_id", "activity", "original_activity", "timestamp", "prev_activity", "wait_h", "gap_h",
                "resource", "department", "amount", "priority", "location", "source_row"]


def events_to_records(df: pd.DataFrame) -> list[dict]:
    out = []
    cols = [c for c in EVENT_FIELDS if c in df.columns]
    for rec in df[cols].to_dict("records"):
        row = {}
        for k, v in rec.items():
            if isinstance(v, pd.Timestamp):
                row[k] = v.isoformat()
            elif k in ("wait_h", "gap_h", "amount"):
                row[k] = round_or_none(v)
            elif v is None or (not isinstance(v, str) and pd.isna(v)):
                row[k] = None
            else:
                row[k] = v.item() if hasattr(v, "item") else v
        out.append(row)
    return out
