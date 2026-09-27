"""Compare every case with the dominant path.

This is deliberately *not* called conformance checking. Formal conformance needs a
normative model (BPMN, Petri net) that someone agreed is correct. We only have the
log, so the reference is the most common way completed cases actually run, and a
"deviation" means "differs from that", not "wrong".

Each distinct variant is analysed once and the result copied to its cases: the
sample log has 10,000 cases but under 200 variants.
"""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

from app.services.config import AnalysisConfig
from app.services.stats import percentile, round_or_none, trace_text

DEVIATION_TYPES = (
    "skipped_activity", "missing_activity", "unexpected_activity", "out_of_order",
    "rework", "loop", "long_transition", "alternative_outcome", "incomplete_case",
)
EXTRA_STEP_TYPES = ("unexpected_activity", "out_of_order", "rework", "loop")
FRAME_COLUMNS = ["case_id", "type", "activity", "timestamp", "description", "hours"]


def pick_dominant_path(variants: pd.DataFrame, completion: list[str] | None = None) -> tuple:
    """Most frequent variant among completed cases (variants are sorted by frequency).

    Restricting to completed cases stops a large pile of open cases, which all end
    early in the same place, from becoming the reference.
    """
    if variants.empty:
        return tuple()
    if completion:
        completed = variants[variants["trace"].map(lambda t: t[-1] in completion)]
        if not completed.empty:
            return tuple(completed.iloc[0]["trace"])
    return tuple(variants.iloc[0]["trace"])


def analyse_trace(trace: tuple, dominant: tuple, dominant_set: frozenset,
                  completion: frozenset = frozenset()) -> list[tuple]:
    """Structural deviations of one variant, as (type, activity, position, description).

    `position` indexes into the trace so the caller can attach that event's timestamp;
    it is None for activities that never happened.
    """
    found: list[tuple] = []

    # Repeats first, straight from the sequence. A -> B -> B is a loop;
    # A -> B -> C -> B is rework (we came back to B after doing something else).
    last_seen: dict[str, int] = {}
    for i, activity in enumerate(trace):
        if i > 0 and trace[i - 1] == activity:
            found.append(("loop", activity, i, f"'{activity}' repeated consecutively (self-loop)."))
        elif activity in last_seen:
            between = trace[last_seen[activity] + 1:i]
            around = "/".join(dict.fromkeys((activity, *between)))
            found.append(("rework", activity, i,
                          f"Returned to '{activity}' after '{trace[i - 1]}' — rework around {around}."))
        last_seen[activity] = i

    if not dominant:
        return found

    # Align against the dominant path with difflib's longest-common-subsequence matcher.
    # "delete" opcodes are dominant steps the case doesn't have; "insert" opcodes are
    # steps the case has that the dominant path doesn't.
    matcher = SequenceMatcher(None, dominant, trace, autojunk=False)
    matched_positions = [j for block in matcher.get_matching_blocks() for j in range(block.b, block.b + block.size)]
    last_matched = max(matched_positions) if matched_positions else -1
    first_position: dict[str, int] = {}
    for i, activity in enumerate(trace):
        first_position.setdefault(activity, i)
    times_executed = Counter(trace)
    ended_at_completion = bool(trace) and trace[-1] in completion

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace"):
            for activity in dominant[i1:i2]:
                if activity in first_position:
                    continue  # it did happen, just elsewhere; handled as out_of_order below
                if j1 <= last_matched:
                    # The case carried on past the point where this step belongs.
                    next_activity = trace[j1] if j1 < len(trace) else None
                    found.append(("skipped_activity", activity, j1 if j1 < len(trace) else None,
                                  f"'{activity}' skipped"
                                  + (f" (went straight to '{next_activity}')." if next_activity else ".")))
                elif not ended_at_completion:
                    found.append(("missing_activity", activity, None,
                                  f"'{activity}' never reached (case ended before it)."))
                # A case that finished with a different outcome (e.g. rejected) would
                # otherwise list every remaining step as missing. It gets a single
                # alternative_outcome record from detect_deviations instead.
        if tag in ("insert", "replace"):
            for j in range(j1, j2):
                activity = trace[j]
                if first_position[activity] != j:
                    continue  # a repeat, already reported as rework/loop
                if activity not in dominant_set:
                    found.append(("unexpected_activity", activity, j,
                                  f"Unexpected activity '{activity}' (not on the dominant path)."))
                elif times_executed[activity] > 1:
                    # The matcher paired a later execution with the dominant path, so this
                    # first one looks inserted. It's the rework case, already reported.
                    continue
                else:
                    found.append(("out_of_order", activity, j,
                                  f"'{activity}' occurred out of the dominant-path order."))
    return found


def _structural_deviations(traces: pd.DataFrame, variants: pd.DataFrame, completion: frozenset,
                           dominant: tuple) -> list[dict]:
    dominant_set = frozenset(dominant)
    by_variant = {t: analyse_trace(t, dominant, dominant_set, completion) for t in variants["trace"]}

    records: list[dict] = []
    for case_id, trace, timestamps in zip(traces["case_id"], traces["trace"], traces["timestamps"]):
        for dev_type, activity, position, description in by_variant[trace]:
            records.append({"case_id": case_id, "type": dev_type, "activity": activity,
                            "timestamp": timestamps[position] if position is not None else None,
                            "description": description})
        last = trace[-1]
        if last not in completion:
            records.append({"case_id": case_id, "type": "incomplete_case", "activity": last,
                            "timestamp": timestamps[-1],
                            "description": f"Case ended at '{last}', not at a completion activity."})
        elif dominant and last != dominant[-1]:
            records.append({"case_id": case_id, "type": "alternative_outcome", "activity": last,
                            "timestamp": timestamps[-1],
                            "description": f"Case ended at '{last}' instead of the dominant end '{dominant[-1]}'."})
    return records


def _long_transitions(ev: pd.DataFrame, cfg: AnalysisConfig) -> list[dict]:
    """Flag transitions that are slow *for that particular transition*.

    A fixed limit doesn't work: two minutes is slow for an automatic hand-off and a
    day is normal for a customer payment. So each A→B pair gets its own threshold,
    max(Q3 + k·IQR, min_hours), and pairs seen fewer than min_transition_support times
    are skipped because their quartiles are too noisy.
    """
    transitions = ev[ev["prev_activity"].notna()][["case_id", "prev_activity", "activity", "timestamp", "gap_h"]]
    limits = transitions.groupby(["prev_activity", "activity"])["gap_h"].agg(
        n="size", median="median", q1=percentile(0.25), q3=percentile(0.75)).reset_index()
    iqr = limits["q3"] - limits["q1"]
    limits["threshold"] = np.maximum(limits["q3"] + cfg.long_transition_iqr_k * iqr, cfg.long_transition_min_hours)
    limits = limits[limits["n"] >= cfg.min_transition_support]

    checked = transitions.merge(limits, on=["prev_activity", "activity"], how="inner")
    slow = checked[checked["gap_h"] > checked["threshold"]]
    return [{
        "case_id": r.case_id, "type": "long_transition", "activity": r.activity, "timestamp": r.timestamp,
        "description": (f"{r.prev_activity} → {r.activity} took {r.gap_h:.1f}h "
                        f"(typical median {r.median:.1f}h; flag threshold {r.threshold:.1f}h)."),
        "hours": float(r.gap_h),
    } for r in slow.itertuples()]


def _path_coverage(trace: tuple, dominant: tuple) -> float:
    """Share of dominant-path steps the trace contains in the same order (LCS length)."""
    if not dominant:
        return 0.0
    matcher = SequenceMatcher(None, dominant, trace, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks()) / len(dominant)


def detect_deviations(ev: pd.DataFrame, traces: pd.DataFrame, variants: pd.DataFrame,
                      completion: list[str], cfg: AnalysisConfig, dominant: tuple) -> dict:
    records = _structural_deviations(traces, variants, frozenset(completion), dominant)
    records += _long_transitions(ev, cfg)
    frame = pd.DataFrame.from_records(records, columns=FRAME_COLUMNS)

    total_cases = len(traces)

    def cases_with(*types: str) -> int:
        return int(frame.loc[frame["type"].isin(types), "case_id"].nunique())

    by_type = []
    for dev_type in DEVIATION_TYPES:
        of_type = frame[frame["type"] == dev_type]
        if of_type.empty:
            continue
        n_cases = of_type["case_id"].nunique()
        by_type.append({
            "type": dev_type,
            "occurrences": int(len(of_type)),
            "cases": int(n_cases),
            "case_pct": round_or_none(100 * n_cases / total_cases),
            "top_activities": [{"activity": a, "occurrences": int(c)}
                               for a, c in Counter(of_type["activity"]).most_common(5)],
        })

    coverage_by_variant = {t: _path_coverage(t, dominant) for t in variants["trace"]}
    # Series.map(dict) and == both treat tuple keys as list-likes, hence the lambdas.
    follows_dominant = traces["trace"].map(lambda t: t == dominant)
    coverage = traces["trace"].map(lambda t: coverage_by_variant[t])
    conformance = {
        "method": "Dominant-path deviation analysis (not formal BPMN conformance checking).",
        "dominant_path": list(dominant),
        "dominant_path_text": trace_text(dominant),
        "conformance_rate_pct": round_or_none(100 * follows_dominant.mean()),
        "avg_dominant_path_coverage_pct": round_or_none(100 * coverage.mean()),
        "cases_with_missing_activities": cases_with("skipped_activity", "missing_activity"),
        "cases_with_unexpected_activities": cases_with("unexpected_activity"),
        "cases_with_rework": cases_with("rework"),
        "cases_with_loops": cases_with("loop"),
        "cases_with_extra_steps": cases_with(*EXTRA_STEP_TYPES),
        "coverage_definition": "Share of dominant-path activities matched in order (LCS) per case, averaged.",
    }

    cases_with_any = int(frame["case_id"].nunique())
    summary = {
        "total_deviations": int(len(frame)),
        "cases_with_deviations": cases_with_any,
        "deviation_rate_pct": round_or_none(100 * cases_with_any / total_cases) if total_cases else 0,
        "by_type": by_type,
        "delay_rule": (f"long_transition: transition time > max(Q3 + {cfg.long_transition_iqr_k}·IQR, "
                       f"{cfg.long_transition_min_hours}h) for that transition; transitions with "
                       f"< {cfg.min_transition_support} occurrences are not checked."),
    }
    frame = frame.sort_values(["case_id", "timestamp"], na_position="last").reset_index(drop=True)
    return {"frame": frame, "summary": summary, "conformance": conformance}
