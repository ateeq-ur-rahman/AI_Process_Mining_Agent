"""Runs the deterministic analysis: normalized events in, JSON-ready results out.

Nothing here knows about the LLM. The AI layer reads these results; it never
feeds anything back into them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd

from app.services.bottlenecks.bottlenecks import detect_bottlenecks
from app.services.config import AnalysisConfig
from app.services.deviations.deviations import detect_deviations, pick_dominant_path
from app.services.metrics.metrics import (
    activity_metrics,
    case_metrics,
    completion_activities,
    transition_metrics,
)
from app.services.process_discovery.dfg import discover_dfg
from app.services.process_discovery.traces import build_event_frame, build_traces
from app.services.resources.resources import analyse_resources
from app.services.stats import round_or_none
from app.services.variants.variants import compute_variants, variants_payload

# Bump when a change alters computed numbers, so stored results can be told apart.
ENGINE_VERSION = "1.0.0"


@dataclass
class EngineResult:
    ev: pd.DataFrame          # one row per event, sorted, with timing columns
    traces: pd.DataFrame      # one row per case
    variants: pd.DataFrame    # one row per distinct activity sequence
    deviations: pd.DataFrame  # one row per detected deviation
    results: dict             # everything the API serves, JSON-safe
    config: AnalysisConfig
    processing_ms: int = 0


def run_engine(events: pd.DataFrame, cfg: AnalysisConfig | None = None) -> EngineResult:
    cfg = cfg or AnalysisConfig()
    started = time.perf_counter()
    if events.empty:
        raise ValueError("No valid events to analyse.")

    ev = build_event_frame(events)
    traces = build_traces(ev)
    variants, variant_summary = compute_variants(traces)

    completion = completion_activities(traces, cfg)
    dominant = pick_dominant_path(variants, completion)
    # If no end activity reaches the share threshold, the dominant path was taken from
    # all cases. Its last step is still the best guess at what "done" looks like.
    if not cfg.completion_activities and dominant and dominant[-1] not in completion:
        completion.append(dominant[-1])

    variant_id_by_trace = dict(zip(variants["trace"], variants["variant_id"]))
    traces["variant_id"] = traces["trace"].map(lambda t: variant_id_by_trace[t])

    cases = case_metrics(traces, completion)
    graph = discover_dfg(ev, traces)
    bottlenecks = detect_bottlenecks(ev, cfg)
    deviations = detect_deviations(ev, traces, variants, completion, cfg, dominant)
    resources = analyse_resources(ev, traces)

    overview = {
        **cases,
        "total_events": int(len(ev)),
        "unique_activities": int(ev["activity"].nunique()),
        "unique_variants": variant_summary["unique_variants"],
        "deviation_rate_pct": deviations["summary"]["deviation_rate_pct"],
        "conformance_rate_pct": deviations["conformance"]["conformance_rate_pct"],
        "dominant_path": deviations["conformance"]["dominant_path"],
        "top10_variant_coverage_pct": variant_summary["top10_coverage_pct"],
        "resources_available": resources["available"],
        "processing_time_available": bottlenecks["methodology"]["processing_time_available"],
        "start_activities": graph["start_activities"][:5],
        "end_activities": graph["end_activities"][:5],
        "engine_version": ENGINE_VERSION,
    }
    processing_ms = int((time.perf_counter() - started) * 1000)
    overview["engine_processing_ms"] = processing_ms

    results = {
        "overview": overview,
        "graph": graph,
        "activities": activity_metrics(ev),
        "transitions": transition_metrics(ev),
        "variants": {"summary": variant_summary, "items": variants_payload(variants, limit=200)},
        "bottlenecks": bottlenecks,
        "deviations": {"summary": deviations["summary"], "conformance": deviations["conformance"]},
        "resources": resources,
        "config": cfg.model_dump(),
    }
    return EngineResult(ev=ev, traces=traces, variants=variants, deviations=deviations["frame"],
                        results=results, config=cfg, processing_ms=processing_ms)


def deviation_records(frame: pd.DataFrame) -> list[dict]:
    records = []
    for row in frame.itertuples(index=False):
        ts = row.timestamp
        records.append({
            "case_id": row.case_id,
            "type": row.type,
            "activity": row.activity,
            "timestamp": ts.isoformat() if isinstance(ts, pd.Timestamp) and not pd.isna(ts) else None,
            "description": row.description,
            "hours": round_or_none(row.hours),  # only set for long_transition
        })
    return records
