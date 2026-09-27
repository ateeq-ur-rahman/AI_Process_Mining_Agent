"""Builds the compact, structured fact sheet given to the LLM.

The LLM receives aggregated metrics only — never raw events or case-level rows.
Each fact has a stable id that findings must cite; values are resolved server-side.
"""
from __future__ import annotations

from app.services.stats import trace_text

MAX_BOTTLENECKS = 8
MAX_TRANSITIONS = 6
MAX_VARIANTS = 8
MAX_RESOURCES = 10


def _fact(facts: dict, fid: str, label: str, value, unit: str = "") -> None:
    if value is None:
        return
    facts[fid] = {"label": label, "value": value, "unit": unit}


def build_facts(results: dict, validation: dict | None = None) -> dict:
    facts: dict[str, dict] = {}
    o = results["overview"]
    for key, label, unit in [
        ("total_cases", "Total cases", "cases"), ("total_events", "Total events", "events"),
        ("completed_cases", "Completed cases", "cases"), ("incomplete_cases", "Incomplete cases", "cases"),
        ("avg_case_duration_hours", "Average case duration", "hours"),
        ("median_case_duration_hours", "Median case duration", "hours"),
        ("p90_case_duration_hours", "P90 case duration", "hours"),
        ("p95_case_duration_hours", "P95 case duration", "hours"),
        ("unique_activities", "Unique activities", "activities"),
        ("unique_variants", "Unique variants", "variants"),
        ("conformance_rate_pct", "Cases exactly following the dominant path", "%"),
        ("deviation_rate_pct", "Cases with at least one deviation", "%"),
        ("top10_variant_coverage_pct", "Share of cases covered by the top 10 variants", "%"),
    ]:
        _fact(facts, f"overview.{key}", label, o.get(key), unit)
    _fact(facts, "overview.dominant_path", "Dominant path (most common completed variant)",
          trace_text(o.get("dominant_path") or []))
    _fact(facts, "overview.completion_activities", "Activities treated as case completion",
          ", ".join(o.get("completion_activities") or []))

    b = results["bottlenecks"]
    scored = [a for a in b["activities"] if a["score"] is not None]
    for rank, a in enumerate(scored[:MAX_BOTTLENECKS], start=1):
        p = f"bottleneck[{a['activity']}]"
        _fact(facts, f"{p}.rank", f"Bottleneck rank of {a['activity']}", f"{rank} of {len(scored)}")
        _fact(facts, f"{p}.score", f"Bottleneck score of {a['activity']} (0-1, relative)", a["score"])
        _fact(facts, f"{p}.indicator", f"Bottleneck indicator of {a['activity']}", a["indicator"])
        _fact(facts, f"{p}.median_wait_hours", f"Median waiting time before {a['activity']}",
              a["median_waiting_time_hours"], "hours")
        _fact(facts, f"{p}.p90_wait_hours", f"P90 waiting time before {a['activity']}",
              a["p90_waiting_time_hours"], "hours")
        _fact(facts, f"{p}.p95_wait_hours", f"P95 waiting time before {a['activity']}",
              a["p95_waiting_time_hours"], "hours")
        _fact(facts, f"{p}.affected_cases_pct", f"Share of cases passing through {a['activity']}",
              a["affected_cases_pct"], "%")
        _fact(facts, f"{p}.frequency", f"Executions of {a['activity']}", a["frequency"], "events")
        _fact(facts, f"{p}.wait_share_pct", f"Share of all waiting time spent before {a['activity']}",
              a["wait_share_pct"], "%")
        _fact(facts, f"{p}.long_wait_cases", f"Cases with a long wait (> log-wide P90) before {a['activity']}",
              a["long_wait_cases"], "cases")
        _fact(facts, f"{p}.median_processing_hours", f"Median processing time of {a['activity']}",
              a["median_processing_time_hours"], "hours")

    for t in b["slow_transitions"][:MAX_TRANSITIONS]:
        p = f"transition[{t['source']} → {t['target']}]"
        _fact(facts, f"{p}.median_hours", f"Median time {t['source']} → {t['target']}", t["median_transition_hours"], "hours")
        _fact(facts, f"{p}.p90_hours", f"P90 time {t['source']} → {t['target']}", t["p90_transition_hours"], "hours")
        _fact(facts, f"{p}.frequency", f"Occurrences of {t['source']} → {t['target']}", t["frequency"], "transitions")

    for v in results["variants"]["items"][:MAX_VARIANTS]:
        p = f"variant[{v['variant_id']}]"
        _fact(facts, f"{p}.trace", f"Activity sequence of {v['variant_id']}", v["trace_text"])
        _fact(facts, f"{p}.case_pct", f"Share of cases following {v['variant_id']}", v["percentage_of_cases"], "%")
        _fact(facts, f"{p}.case_count", f"Cases following {v['variant_id']}", v["case_count"], "cases")
        _fact(facts, f"{p}.avg_duration_hours", f"Average duration of {v['variant_id']}", v["avg_duration_hours"], "hours")

    d = results["deviations"]["summary"]
    for t in d["by_type"]:
        p = f"deviation[{t['type']}]"
        _fact(facts, f"{p}.cases", f"Cases with {t['type']}", t["cases"], "cases")
        _fact(facts, f"{p}.case_pct", f"Share of cases with {t['type']}", t["case_pct"], "%")
        _fact(facts, f"{p}.occurrences", f"Occurrences of {t['type']}", t["occurrences"], "occurrences")
        _fact(facts, f"{p}.top_activities", f"Most frequent activities involved in {t['type']}",
              ", ".join(f"{x['activity']} ({x['occurrences']})" for x in t["top_activities"][:3]))

    r = results["resources"]
    if r.get("available"):
        for res in r["resources"][:MAX_RESOURCES]:
            p = f"resource[{res['resource']}]"
            _fact(facts, f"{p}.cases_handled", f"Cases handled by {res['resource']}", res["cases_handled"], "cases")
            _fact(facts, f"{p}.median_wait_hours", f"Median wait before events of {res['resource']}",
                  res["median_waiting_time_hours"], "hours")
            _fact(facts, f"{p}.rework_rate_pct", f"Rework rate of {res['resource']}'s events", res["rework_rate_pct"], "%")
            _fact(facts, f"{p}.top_activities", f"Main activities of {res['resource']}", ", ".join(res["top_activities"]))

    if validation:
        for key in ("total_rows", "valid_rows", "invalid_rows", "duplicate_rows", "missing_case_ids",
                    "invalid_timestamps", "impossible_timestamps", "malformed_rows", "single_event_cases"):
            _fact(facts, f"data_quality.{key}", key.replace("_", " ").capitalize(), validation.get(key), "rows"
                  if "rows" in key or "ids" in key or "timestamps" in key else "cases")
        merges = validation.get("activity_name_merges") or {}
        if merges:
            _fact(facts, "data_quality.activity_name_merges", "Activity spellings merged during normalization",
                  "; ".join(f"{k} ← {', '.join(v)}" for k, v in merges.items()))
    return facts


def build_llm_payload(results: dict, validation: dict | None = None) -> dict:
    """The complete, bounded payload sent to the LLM for report generation."""
    b = results["bottlenecks"]["methodology"]
    return {
        "facts": build_facts(results, validation),
        "methodology": {
            "bottleneck_score": b["formula"],
            "bottleneck_weights": b["weights_used"],
            "processing_time_available": b["processing_time_available"],
            "bottleneck_caveat": b["caveat"],
            "deviation_method": results["deviations"]["conformance"]["method"],
            "delay_rule": results["deviations"]["summary"]["delay_rule"],
            "timing_semantics": results["graph"]["timing_semantics"],
            "variant_definition": results["variants"]["summary"]["definition"],
        },
    }


def drilldown_for(fact_id: str) -> dict | None:
    import re
    m = re.match(r"^(bottleneck|transition|deviation|variant|resource)\[(.+?)\]\.", fact_id)
    if not m:
        return {"kind": "overview"} if fact_id.startswith("overview.") else None
    kind, key = m.groups()
    if kind == "bottleneck":
        return {"kind": "activity", "activity": key}
    if kind == "transition":
        src, _, tgt = key.partition(" → ")
        return {"kind": "transition", "source": src, "target": tgt}
    if kind == "deviation":
        return {"kind": "deviation", "deviation_type": key}
    if kind == "variant":
        return {"kind": "variant", "variant_id": key}
    return {"kind": "resource", "resource": key}


def format_value(fact: dict) -> str:
    v, unit = fact["value"], fact.get("unit") or ""
    if isinstance(v, float):
        v = f"{v:,.2f}".rstrip("0").rstrip(".")
    elif isinstance(v, int):
        v = f"{v:,}"
    return f"{v} {unit}".strip() if unit not in ("", "%") else f"{v}{unit}"
