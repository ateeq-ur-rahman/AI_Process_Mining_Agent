"""Turn a flat event table into ordered cases.

Most event logs record one timestamp per event: when the step was *completed*.
From that alone we can't separate queueing from work, so the columns below are
named for what they actually measure:

    gap_h   hours since the previous event in the same case finished
    wait_h  hours from the previous event finishing until this one started.
            Without a start_timestamp column this is the same as gap_h.
    proc_h  hours between start_timestamp and timestamp (NaN when there is no start)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HOUR = np.timedelta64(1, "h")


def build_event_frame(events: pd.DataFrame) -> pd.DataFrame:
    # Two events in one case can share a timestamp (batch updates, second-level
    # precision). Falling back to file row order keeps the result deterministic and
    # usually matches how the source system wrote them. mergesort is stable.
    ev = events.sort_values(["case_id", "timestamp", "source_row"], kind="mergesort").reset_index(drop=True)
    by_case = ev.groupby("case_id", sort=False)

    ev["pos"] = by_case.cumcount()
    ev["prev_activity"] = by_case["activity"].shift(1)
    prev_finished = by_case["timestamp"].shift(1)
    ev["gap_h"] = (ev["timestamp"] - prev_finished) / HOUR

    start = ev["start_timestamp"] if "start_timestamp" in ev else pd.Series(pd.NaT, index=ev.index)
    has_start = start.notna()
    ev["proc_h"] = np.where(has_start, (ev["timestamp"] - start) / HOUR, np.nan)
    started = start.where(has_start, ev["timestamp"])
    # A start recorded slightly before the previous completion (overlapping work)
    # would give a negative wait; count it as no wait instead.
    ev["wait_h"] = ((started - prev_finished) / HOUR).clip(lower=0)

    # 0 the first time an activity happens in a case, 1 the second time, ...
    # Anything > 0 is a repeat, which the rework rates are built on.
    ev["occurrence"] = ev.groupby(["case_id", "activity"], sort=False).cumcount()
    return ev


def build_traces(ev: pd.DataFrame) -> pd.DataFrame:
    """One row per case with its activity sequence as a tuple (hashable, so it can
    be grouped on directly to form variants)."""
    by_case = ev.groupby("case_id", sort=False)
    traces = pd.DataFrame({
        "trace": by_case["activity"].agg(tuple),
        "timestamps": by_case["timestamp"].agg(list),
        "start": by_case["timestamp"].min(),
        "end": by_case["timestamp"].max(),
        "n_events": by_case.size(),
    })
    traces["duration_h"] = (traces["end"] - traces["start"]) / HOUR
    traces["first_activity"] = traces["trace"].map(lambda t: t[0])
    traces["last_activity"] = traces["trace"].map(lambda t: t[-1])
    return traces.reset_index()
