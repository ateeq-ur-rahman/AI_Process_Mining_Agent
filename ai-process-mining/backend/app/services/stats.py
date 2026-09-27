"""Formatting helpers the engine modules share when turning pandas output into JSON."""
from __future__ import annotations

import math


def round_or_none(value, digits: int = 2) -> float | None:
    """Round for JSON output. NaN/inf/None become None, since JSON has no NaN."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


def percentile(p: float):
    """Aggregation function for groupby().agg(). pandas' default linear interpolation."""
    def _percentile(series):
        return series.quantile(p)
    _percentile.__name__ = f"p{int(p * 100)}"
    return _percentile


def trace_text(trace) -> str:
    return " → ".join(trace)
