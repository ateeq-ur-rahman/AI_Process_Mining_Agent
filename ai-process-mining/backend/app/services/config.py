"""Every threshold and weight the engine uses. Results are cached per config hash, so
changing any value here (or via the API) produces a separate, reproducible result."""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field


class BottleneckWeights(BaseModel):
    median_wait: float = Field(0.30, ge=0)
    p90_wait: float = Field(0.20, ge=0)
    processing: float = Field(0.10, ge=0, description="Ignored (re-weighted) when start timestamps are absent.")
    case_coverage: float = Field(0.20, ge=0, description="Share of cases that pass through the activity.")
    wait_share: float = Field(0.20, ge=0, description="Share of all waiting time in the log spent before this activity.")


class AnalysisConfig(BaseModel):
    bottleneck_weights: BottleneckWeights = BottleneckWeights()
    bottleneck_high_threshold: float = 0.60
    bottleneck_medium_threshold: float = 0.35
    min_activity_support: int = Field(10, description="Activities with fewer events are not scored.")

    long_transition_iqr_k: float = Field(3.0, description="Flag if transition time > Q3 + k*IQR for that transition.")
    long_transition_min_hours: float = Field(1.0, description="Never flag transitions shorter than this.")
    min_transition_support: int = Field(20, description="Transitions seen fewer times are not checked for delays.")

    completion_activities: list[str] | None = Field(
        None, description="Activities that mark a completed case. Default: derived from data (see end_activity_min_share).")
    end_activity_min_share: float = Field(0.02, description="End activities covering >= this share of cases count as completion.")

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()[:16]
