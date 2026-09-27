"""Resource analysis. Reports observed metrics only — never performance judgements."""
from __future__ import annotations

import pandas as pd

from app.services.stats import round_or_none

DISCLAIMER = (
    "Observed operational metrics only. Differences between resources can reflect case mix, "
    "assignment rules, workload or data recording practices; they do not by themselves indicate "
    "individual performance."
)


def analyse_resources(ev: pd.DataFrame, traces: pd.DataFrame) -> dict:
    if "resource" not in ev or ev["resource"].isna().all():
        return {"available": False, "resources": [], "disclaimer": DISCLAIMER}
    r_ev = ev[ev["resource"].notna()]
    durations = traces.set_index("case_id")["duration_h"]
    g = r_ev.groupby("resource")
    agg = g.agg(
        events=("case_id", "size"),
        cases=("case_id", "nunique"),
        activities=("activity", "nunique"),
        avg_wait=("wait_h", "mean"),
        median_wait=("wait_h", "median"),
        avg_proc=("proc_h", "mean"),
        repeats=("occurrence", lambda s: int((s > 0).sum())),
    ).sort_values("events", ascending=False)
    case_dur = r_ev[["resource", "case_id"]].drop_duplicates().assign(
        d=lambda x: x["case_id"].map(durations)).groupby("resource")["d"].mean()
    top_acts = g["activity"].agg(lambda s: s.value_counts().head(3).index.tolist())
    dept = g["department"].agg(lambda s: s.dropna().mode().iloc[0] if s.notna().any() else None) \
        if "department" in r_ev else None
    rows = [{
        "resource": res,
        "department": (dept.get(res) if dept is not None else None),
        "events": int(r.events),
        "cases_handled": int(r.cases),
        "distinct_activities": int(r.activities),
        "top_activities": top_acts.get(res, []),
        "avg_waiting_time_hours": round_or_none(r.avg_wait),
        "median_waiting_time_hours": round_or_none(r.median_wait),
        "avg_processing_time_hours": round_or_none(r.avg_proc),
        "avg_case_duration_hours": round_or_none(case_dur.get(res)),
        "rework_rate_pct": round_or_none(100 * r.repeats / r.events) if r.events else None,
    } for res, r in agg.iterrows()]
    return {
        "available": True,
        "resources": rows,
        "definitions": {
            "rework_rate_pct": "Share of the resource's events that repeat an activity already executed in the same case.",
            "avg_waiting_time_hours": "Mean waiting time before events performed by this resource.",
        },
        "disclaimer": DISCLAIMER,
    }
