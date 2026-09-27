from __future__ import annotations

from app.services.config import AnalysisConfig, BottleneckWeights


def bottleneck_config(w_median_wait: float | None = None, w_p90_wait: float | None = None,
                      w_processing: float | None = None, w_case_coverage: float | None = None,
                      w_wait_share: float | None = None) -> AnalysisConfig | None:
    """Query-string weight overrides for /bottlenecks. None means "use the defaults"."""
    overrides = {
        "median_wait": w_median_wait,
        "p90_wait": w_p90_wait,
        "processing": w_processing,
        "case_coverage": w_case_coverage,
        "wait_share": w_wait_share,
    }
    overrides = {name: weight for name, weight in overrides.items() if weight is not None}
    if not overrides:
        return None
    weights = BottleneckWeights().model_dump() | overrides
    return AnalysisConfig(bottleneck_weights=BottleneckWeights(**weights))
