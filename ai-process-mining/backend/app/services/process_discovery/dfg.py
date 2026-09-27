"""Directly-follows graph: an edge A→B for every time B came straight after A in a case.

Written by hand instead of calling PM4Py: it's a single groupby, and keeping it here
means the counts shown in the UI can be traced to one readable function.
"""
from __future__ import annotations

import pandas as pd

from app.services.stats import percentile, round_or_none


def discover_dfg(ev: pd.DataFrame, traces: pd.DataFrame) -> dict:
    total_cases = int(len(traces))
    transitions = ev[ev["prev_activity"].notna()]

    edges_df = transitions.groupby(["prev_activity", "activity"]).agg(
        frequency=("case_id", "size"),
        cases=("case_id", "nunique"),
        avg_h=("gap_h", "mean"),
        median_h=("gap_h", "median"),
        p90_h=("gap_h", percentile(0.9)),
    ).reset_index().sort_values("frequency", ascending=False)

    edges = [{
        "id": f"{r.prev_activity}→{r.activity}",
        "source": r.prev_activity,
        "target": r.activity,
        "frequency": int(r.frequency),
        "cases": int(r.cases),
        "case_pct": round_or_none(100 * r.cases / total_cases),
        "avg_transition_hours": round_or_none(r.avg_h),
        "median_transition_hours": round_or_none(r.median_h),
        "p90_transition_hours": round_or_none(r.p90_h),
    } for r in edges_df.itertuples()]

    nodes_df = ev.groupby("activity").agg(
        count=("case_id", "size"),
        cases=("case_id", "nunique"),
        avg_wait=("wait_h", "mean"),
        median_wait=("wait_h", "median"),
        avg_proc=("proc_h", "mean"),
        median_proc=("proc_h", "median"),
        avg_pos=("pos", "mean"),
    ).reset_index().sort_values("count", ascending=False)

    start_counts = traces["first_activity"].value_counts()
    end_counts = traces["last_activity"].value_counts()
    nodes = [{
        "id": r.activity,
        "activity": r.activity,
        "count": int(r.count),
        "cases": int(r.cases),
        "case_pct": round_or_none(100 * r.cases / total_cases),
        # "duration" of an activity = waiting time before it completes (see README: timing semantics)
        "avg_duration_hours": round_or_none(r.avg_wait),
        "median_duration_hours": round_or_none(r.median_wait),
        "avg_processing_hours": round_or_none(r.avg_proc),
        "median_processing_hours": round_or_none(r.median_proc),
        "avg_position": round_or_none(r.avg_pos),  # mean index within cases; used for layout ordering
        "is_start": bool(r.activity in start_counts.index),
        "is_end": bool(r.activity in end_counts.index),
        "start_count": int(start_counts.get(r.activity, 0)),
        "end_count": int(end_counts.get(r.activity, 0)),
    } for r in nodes_df.itertuples()]

    return {
        "nodes": nodes,
        "edges": edges,
        "start_activities": [{"activity": a, "cases": int(c), "case_pct": round_or_none(100 * c / total_cases)}
                             for a, c in start_counts.items()],
        "end_activities": [{"activity": a, "cases": int(c), "case_pct": round_or_none(100 * c / total_cases)}
                           for a, c in end_counts.items()],
        "total_cases": total_cases,
        "timing_semantics": (
            "Node duration = waiting time from the previous event's completion to this activity "
            "(plus processing time when start_timestamp is present). Edge time = time between the two events."
        ),
    }
