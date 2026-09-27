"""Rank activities by how much waiting builds up in front of them.

No single number identifies a bottleneck. A step with a 3-day median wait that 1% of
cases reach matters less than a 20-hour wait that every case goes through. So each
activity gets five components:

    median_wait    typical wait before the activity
    p90_wait       how bad the slow tail gets
    processing     median work time (only if start timestamps exist)
    case_coverage  share of cases that pass through the activity
    wait_share     share of *all* waiting time in the log spent before this activity

Each component is min-max scaled across the scored activities, and the score is their
weighted average:

    score = Σ weight_i · scaled_i / Σ weight_i

Because of the scaling, the score only ranks activities against each other in this
dataset: the top activity scores close to 1 even in a healthy process. It is a way to
decide where to look first, and the API says so alongside every result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.config import AnalysisConfig
from app.services.stats import percentile, round_or_none

COMPONENTS = ("median_wait", "p90_wait", "processing", "case_coverage", "wait_share")


def scale_0_to_1(values: pd.Series) -> pd.Series:
    """Min-max scale. If every activity has the same value, the component can't tell
    them apart, so it contributes 0 rather than dividing by zero."""
    values = values.astype(float)
    lowest, highest = values.min(), values.max()
    if pd.isna(lowest) or highest - lowest < 1e-12:
        return pd.Series(np.where(values.notna(), 0.0, np.nan), index=values.index)
    return (values - lowest) / (highest - lowest)


def _indicator(score: float, cfg: AnalysisConfig) -> str:
    if score >= cfg.bottleneck_high_threshold:
        return "HIGH"
    if score >= cfg.bottleneck_medium_threshold:
        return "MEDIUM"
    return "LOW"


def detect_bottlenecks(ev: pd.DataFrame, cfg: AnalysisConfig) -> dict:
    total_cases = ev["case_id"].nunique()
    waits = ev[ev["wait_h"].notna()]  # first events of a case have nothing to wait for
    total_wait_h = float(waits["wait_h"].sum()) or 1.0
    log_p90_wait = float(waits["wait_h"].quantile(0.9)) if len(waits) else 0.0

    stats = ev.groupby("activity").agg(
        frequency=("case_id", "size"),
        affected_cases=("case_id", "nunique"),
        avg_proc=("proc_h", "mean"),
        median_proc=("proc_h", "median"),
    )
    wait_stats = waits.groupby("activity").agg(
        avg_wait=("wait_h", "mean"),
        median_wait=("wait_h", "median"),
        p90_wait=("wait_h", percentile(0.9)),
        p95_wait=("wait_h", percentile(0.95)),
        sum_wait=("wait_h", "sum"),
    )
    long_wait_cases = (waits[waits["wait_h"] > log_p90_wait]
                       .groupby("activity")["case_id"].nunique().rename("long_wait_cases"))
    stats = stats.join(wait_stats, how="left").join(long_wait_cases, how="left").fillna({"long_wait_cases": 0})
    stats["case_coverage"] = stats["affected_cases"] / total_cases
    stats["wait_share"] = stats["sum_wait"] / total_wait_h
    # Too few events and the percentiles mean little; no waits means it only ever starts cases.
    stats["scored"] = (stats["frequency"] >= cfg.min_activity_support) & stats["median_wait"].notna()

    has_processing = bool(ev["proc_h"].notna().any())
    weights = cfg.bottleneck_weights.model_dump()
    if not has_processing:
        weights["processing"] = 0.0  # the remaining weights are renormalised by the division below
    weight_total = sum(weights.values()) or 1.0

    scored = stats[stats["scored"]].copy()
    scaled = {
        "median_wait": scale_0_to_1(scored["median_wait"]),
        "p90_wait": scale_0_to_1(scored["p90_wait"]),
        "processing": scale_0_to_1(scored["median_proc"] if has_processing
                                   else pd.Series(0.0, index=scored.index)),
        "case_coverage": scale_0_to_1(scored["case_coverage"]),
        "wait_share": scale_0_to_1(scored["wait_share"]),
    }
    scaled = {name: component.fillna(0.0) for name, component in scaled.items()}
    scored["score"] = sum(weights[name] * scaled[name] for name in COMPONENTS) / weight_total

    rows = []
    for activity, r in stats.iterrows():
        is_scored = bool(r["scored"])
        score = float(scored.loc[activity, "score"]) if is_scored else None
        if is_scored:
            not_scored_reason = None
        elif pd.isna(r["median_wait"]):
            not_scored_reason = "No waiting time (only occurs as first event)"
        else:
            not_scored_reason = f"Fewer than {cfg.min_activity_support} events"
        rows.append({
            "activity": activity,
            "frequency": int(r["frequency"]),
            "affected_cases": int(r["affected_cases"]),
            "affected_cases_pct": round_or_none(100 * r["case_coverage"]),
            "long_wait_cases": int(r["long_wait_cases"]),
            "average_waiting_time_hours": round_or_none(r["avg_wait"]),
            "median_waiting_time_hours": round_or_none(r["median_wait"]),
            "p90_waiting_time_hours": round_or_none(r["p90_wait"]),
            "p95_waiting_time_hours": round_or_none(r["p95_wait"]),
            "average_processing_time_hours": round_or_none(r["avg_proc"]),
            "median_processing_time_hours": round_or_none(r["median_proc"]),
            "wait_share_pct": round_or_none(100 * r["wait_share"]) if pd.notna(r["wait_share"]) else None,
            "score": round_or_none(score, 3),
            "indicator": _indicator(score, cfg) if score is not None else "NOT_SCORED",
            "components": ({name: round_or_none(scaled[name].get(activity), 3) for name in COMPONENTS}
                           if is_scored else None),
            "not_scored_reason": not_scored_reason,
        })
    rows.sort(key=lambda row: (row["score"] is None, -(row["score"] or 0)))

    return {
        "activities": rows,
        "slow_transitions": _slowest_transitions(ev, cfg, total_wait_h),
        "methodology": {
            "formula": "score = Σ w_i · minmax(component_i) / Σ w_i  (computed across scored activities)",
            "weights_used": weights,
            "processing_time_available": has_processing,
            "thresholds": {"HIGH": cfg.bottleneck_high_threshold, "MEDIUM": cfg.bottleneck_medium_threshold},
            "long_wait_definition_hours": round_or_none(log_p90_wait),
            "long_wait_rule": "long_wait_cases = cases whose wait before the activity exceeds the log-wide P90 wait.",
            "caveat": ("Scores rank activities relative to each other within this dataset. They indicate where "
                       "to investigate, not an objective or causal judgement."),
        },
    }


def _slowest_transitions(ev: pd.DataFrame, cfg: AnalysisConfig, total_wait_h: float, limit: int = 10) -> list[dict]:
    transitions = ev[ev["prev_activity"].notna()]
    stats = transitions.groupby(["prev_activity", "activity"]).agg(
        frequency=("gap_h", "size"), median=("gap_h", "median"), p90=("gap_h", percentile(0.9)), total=("gap_h", "sum"),
    ).reset_index()
    stats = stats[stats["frequency"] >= cfg.min_activity_support].sort_values("median", ascending=False).head(limit)
    return [{
        "source": r.prev_activity,
        "target": r.activity,
        "frequency": int(r.frequency),
        "median_transition_hours": round_or_none(r.median),
        "p90_transition_hours": round_or_none(r.p90),
        "total_wait_share_pct": round_or_none(100 * r.total / total_wait_h),
    } for r in stats.itertuples()]
