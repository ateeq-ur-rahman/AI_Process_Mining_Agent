"""Duration and frequency metrics at case, activity and transition level.

Percentiles use pandas' default linear interpolation.
"""
from __future__ import annotations

import pandas as pd

from app.services.config import AnalysisConfig
from app.services.stats import percentile, round_or_none


def completion_activities(traces: pd.DataFrame, cfg: AnalysisConfig) -> list[str]:
    """Activities that mean "this case is finished".

    Unless configured, any activity that ends at least `end_activity_min_share` of cases
    counts. That picks up alternative outcomes such as rejections and cancellations
    while leaving out cases that simply stopped somewhere in the middle.
    """
    if cfg.completion_activities:
        return list(cfg.completion_activities)
    end_share = traces["last_activity"].value_counts(normalize=True)
    return [activity for activity, share in end_share.items() if share >= cfg.end_activity_min_share]


def case_metrics(traces: pd.DataFrame, completion: list[str]) -> dict:
    durations = traces["duration_h"]
    completed = traces["last_activity"].isin(completion)
    completed_durations = durations[completed]
    return {
        "total_cases": int(len(traces)),
        "completed_cases": int(completed.sum()),
        "incomplete_cases": int((~completed).sum()),
        "completion_activities": completion,
        "completion_rule": "A case is complete when its last event is one of completion_activities.",
        "avg_case_duration_hours": round_or_none(durations.mean()),
        "median_case_duration_hours": round_or_none(durations.median()),
        "p90_case_duration_hours": round_or_none(durations.quantile(0.9)),
        "p95_case_duration_hours": round_or_none(durations.quantile(0.95)),
        "completed_avg_case_duration_hours": round_or_none(completed_durations.mean()),
        "completed_median_case_duration_hours": round_or_none(completed_durations.median()),
        "avg_events_per_case": round_or_none(traces["n_events"].mean()),
        "first_event": traces["start"].min().isoformat() if len(traces) else None,
        "last_event": traces["end"].max().isoformat() if len(traces) else None,
    }


def activity_metrics(ev: pd.DataFrame) -> list[dict]:
    """Per-activity counts and waits. "duration" here is the wait before the activity
    (see traces.py); processing time only exists when start timestamps were provided."""
    total_cases = ev["case_id"].nunique()
    g = ev.groupby("activity").agg(
        frequency=("case_id", "size"),
        cases=("case_id", "nunique"),
        avg_wait=("wait_h", "mean"),
        median_wait=("wait_h", "median"),
        p90_wait=("wait_h", percentile(0.9)),
        avg_proc=("proc_h", "mean"),
        median_proc=("proc_h", "median"),
        repeats=("occurrence", lambda s: int((s > 0).sum())),
    ).reset_index().sort_values("frequency", ascending=False)
    return [{
        "activity": r.activity,
        "frequency": int(r.frequency),
        "cases": int(r.cases),
        "case_pct": round_or_none(100 * r.cases / total_cases),
        "avg_duration_hours": round_or_none(r.avg_wait),
        "median_duration_hours": round_or_none(r.median_wait),
        "p90_duration_hours": round_or_none(r.p90_wait),
        "avg_processing_hours": round_or_none(r.avg_proc),
        "median_processing_hours": round_or_none(r.median_proc),
        "repeat_executions": int(r.repeats),
    } for r in g.itertuples()]


def transition_metrics(ev: pd.DataFrame) -> list[dict]:
    transitions = ev[ev["prev_activity"].notna()]
    g = transitions.groupby(["prev_activity", "activity"]).agg(
        frequency=("case_id", "size"),
        avg=("gap_h", "mean"),
        median=("gap_h", "median"),
        p90=("gap_h", percentile(0.9)),
    ).reset_index().sort_values("frequency", ascending=False)
    return [{
        "source": r.prev_activity, "target": r.activity, "frequency": int(r.frequency),
        "avg_transition_hours": round_or_none(r.avg), "median_transition_hours": round_or_none(r.median),
        "p90_transition_hours": round_or_none(r.p90),
    } for r in g.itertuples()]
