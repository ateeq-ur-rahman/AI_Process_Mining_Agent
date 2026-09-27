"""Variants: cases grouped by their exact activity sequence.

"Sufficiently similar" sequences are not merged. Any similarity rule (edit distance,
ignoring loops, ...) changes what the numbers mean, so it should be a deliberate,
visible choice rather than a default.
"""
from __future__ import annotations

import pandas as pd

from app.services.stats import round_or_none, trace_text


def compute_variants(traces: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    total = len(traces)
    # V1 is the most frequent variant; ties go to the faster one.
    g = traces.groupby("trace", sort=False).agg(
        case_count=("case_id", "size"),
        avg_duration_h=("duration_h", "mean"),
        median_duration_h=("duration_h", "median"),
    ).reset_index().sort_values(["case_count", "avg_duration_h"], ascending=[False, True]).reset_index(drop=True)
    g["variant_id"] = [f"V{i + 1}" for i in range(len(g))]
    g["pct"] = 100 * g["case_count"] / total
    g["cum_pct"] = g["pct"].cumsum()
    top10 = float(g["pct"].head(10).sum())
    n_for_80 = int((g["cum_pct"] < 80).sum() + 1) if len(g) else 0
    summary = {
        "unique_variants": int(len(g)),
        "most_common_variant": trace_text(g.loc[0, "trace"]) if len(g) else None,
        "most_common_variant_pct": round_or_none(g.loc[0, "pct"]) if len(g) else None,
        "top10_coverage_pct": round_or_none(top10),
        "variants_for_80pct_coverage": min(n_for_80, len(g)),
        "singleton_variants": int((g["case_count"] == 1).sum()),
        "coverage_statement": f"Top {min(10, len(g))} variants cover {top10:.1f}% of cases.",
        "definition": "A variant is a unique exact sequence of activities (no similarity clustering in the MVP).",
    }
    return g, summary


def variants_payload(vdf: pd.DataFrame, limit: int = 50) -> list[dict]:
    return [{
        "variant_id": r.variant_id,
        "trace": list(r.trace),
        "trace_text": trace_text(r.trace),
        "length": len(r.trace),
        "case_count": int(r.case_count),
        "percentage_of_cases": round_or_none(r.pct),
        "cumulative_pct": round_or_none(r.cum_pct),
        "avg_duration_hours": round_or_none(r.avg_duration_h),
        "median_duration_hours": round_or_none(r.median_duration_h),
    } for r in vdf.head(limit).itertuples()]
