"""Deterministic query tools over engine results. Used by both the LLM and the rule-based router.

Each tool returns {"data": ..., "evidence": [{"metric", "value", "source"}]}.
"""
from __future__ import annotations

import difflib
import re

import pandas as pd

from app.services.engine import EngineResult
from app.services.normalization.normalizer import activity_key
from app.services.stats import round_or_none, trace_text


def _evidence(metric: str, value, source: str, unit: str = "") -> dict:
    if isinstance(value, float):
        value = f"{value:,.2f}".rstrip("0").rstrip(".")
    elif isinstance(value, int):
        value = f"{value:,}"
    return {"metric": metric, "value": f"{value}{(' ' + unit) if unit and unit != '%' else unit}", "source": source}


class QueryTools:
    def __init__(self, er: EngineResult, validation: dict | None = None):
        self.er = er
        self.results = er.results
        self.validation = validation or {}
        self.activities = sorted(er.ev["activity"].unique().tolist())
        self._act_by_key = {activity_key(a): a for a in self.activities}

    # ---- helpers
    def resolve_activity(self, name: str | None) -> str | None:
        if not name:
            return None
        k = activity_key(name)
        if k in self._act_by_key:
            return self._act_by_key[k]
        m = difflib.get_close_matches(k, list(self._act_by_key), n=1, cutoff=0.75)
        return self._act_by_key[m[0]] if m else None

    def find_activity_in_text(self, text: str) -> str | None:
        k = " " + activity_key(re.sub(r"[^\w\s-]", " ", text)) + " "
        hits = [a for key, a in self._act_by_key.items() if f" {key} " in k]
        if hits:
            return max(hits, key=len)
        words = activity_key(text).split()
        grams = {" ".join(words[i:i + n]) for n in (2, 3) for i in range(len(words) - n + 1)}
        best, score = None, 0.0
        for g in grams:
            for key, a in self._act_by_key.items():
                s = difflib.SequenceMatcher(None, g, key).ratio()
                if s > score:
                    best, score = a, s
        return best if score >= 0.85 else None

    STOP = {"which", "where", "cases", "orders", "order", "process", "about", "there", "their", "what",
            "does", "slow", "slower", "long", "longer", "delay", "delayed", "delays", "waiting", "how"}

    def activities_mentioned(self, text: str, limit: int = 3) -> list[str]:
        """Exact activity mentions first; otherwise activities sharing a distinctive word with the text."""
        exact = self.find_activity_in_text(text)
        if exact:
            return [exact]
        words = {w for w in activity_key(re.sub(r"[^\w\s-]", " ", text)).split() if len(w) >= 4 and w not in self.STOP}
        hits = [a for key, a in self._act_by_key.items() if words & set(key.split())]
        score = {a["activity"]: a["score"] or 0 for a in self.results["bottlenecks"]["activities"]}
        return sorted(hits, key=lambda a: -score.get(a, 0))[:limit]

    # ---- tools
    def get_overview(self) -> dict:
        o = self.results["overview"]
        ev = [_evidence("Total cases", o["total_cases"], "overview"),
              _evidence("Completed cases", o["completed_cases"], "overview"),
              _evidence("Average case duration", o["avg_case_duration_hours"], "overview", "hours"),
              _evidence("Median case duration", o["median_case_duration_hours"], "overview", "hours"),
              _evidence("P95 case duration", o["p95_case_duration_hours"], "overview", "hours"),
              _evidence("Unique variants", o["unique_variants"], "overview"),
              _evidence("Deviation rate", o["deviation_rate_pct"], "overview", "%"),
              _evidence("Conformance to dominant path", o["conformance_rate_pct"], "overview", "%")]
        data = {k: o[k] for k in ("total_cases", "total_events", "completed_cases", "incomplete_cases",
                                  "avg_case_duration_hours", "median_case_duration_hours",
                                  "p90_case_duration_hours", "p95_case_duration_hours", "unique_activities",
                                  "unique_variants", "deviation_rate_pct", "conformance_rate_pct",
                                  "dominant_path", "completion_activities", "first_event", "last_event")}
        return {"data": data, "evidence": ev}

    def get_bottlenecks(self, limit: int = 5) -> dict:
        rows = [a for a in self.results["bottlenecks"]["activities"] if a["score"] is not None][:max(1, min(limit, 20))]
        ev = []
        for a in rows[:3]:
            ev += [_evidence(f"{a['activity']} — bottleneck score", a["score"], "bottlenecks"),
                   _evidence(f"{a['activity']} — median waiting time", a["median_waiting_time_hours"], "bottlenecks", "hours"),
                   _evidence(f"{a['activity']} — affected cases", a["affected_cases_pct"], "bottlenecks", "%")]
        return {"data": {"activities": rows, "slow_transitions": self.results["bottlenecks"]["slow_transitions"][:5],
                         "methodology": self.results["bottlenecks"]["methodology"]}, "evidence": ev}

    def get_activity_stats(self, activity: str) -> dict:
        a = self.resolve_activity(activity)
        if not a:
            return {"data": {"error": f"No activity matching '{activity}'.", "known_activities": self.activities},
                    "evidence": []}
        stats = next(x for x in self.results["activities"] if x["activity"] == a)
        b = next((x for x in self.results["bottlenecks"]["activities"] if x["activity"] == a), {})
        ev = [_evidence(f"{a} — executions", stats["frequency"], "activities"),
              _evidence(f"{a} — cases", stats["case_pct"], "activities", "%"),
              _evidence(f"{a} — median waiting time", stats["median_duration_hours"], "activities", "hours"),
              _evidence(f"{a} — P90 waiting time", stats["p90_duration_hours"], "activities", "hours")]
        if b.get("score") is not None:
            ev.append(_evidence(f"{a} — bottleneck score", b["score"], "bottlenecks"))
        return {"data": {"activity": stats, "bottleneck": b}, "evidence": ev}

    def get_transition_stats(self, source: str, target: str) -> dict:
        s, t = self.resolve_activity(source), self.resolve_activity(target)
        row = next((x for x in self.results["transitions"] if x["source"] == s and x["target"] == t), None)
        if not row:
            return {"data": {"error": f"No directly-follows transition '{source}' → '{target}' in this log."},
                    "evidence": []}
        return {"data": row, "evidence": [
            _evidence(f"{s} → {t} — occurrences", row["frequency"], "transitions"),
            _evidence(f"{s} → {t} — median time", row["median_transition_hours"], "transitions", "hours"),
            _evidence(f"{s} → {t} — P90 time", row["p90_transition_hours"], "transitions", "hours")]}

    def get_variants(self, limit: int = 5) -> dict:
        items = self.results["variants"]["items"][:max(1, min(limit, 20))]
        s = self.results["variants"]["summary"]
        ev = [_evidence("Unique variants", s["unique_variants"], "variants"),
              _evidence("Top 10 variant coverage", s["top10_coverage_pct"], "variants", "%")]
        ev += [_evidence(f"{v['variant_id']} share of cases", v["percentage_of_cases"], "variants", "%") for v in items[:3]]
        return {"data": {"summary": s, "variants": items}, "evidence": ev}

    def get_deviation_summary(self, deviation_type: str | None = None) -> dict:
        d = self.results["deviations"]
        by_type = d["summary"]["by_type"]
        if deviation_type:
            by_type = [t for t in by_type if t["type"] == deviation_type]
        ev = [_evidence(f"Cases with {t['type'].replace('_', ' ')}", t["cases"], "deviations") for t in by_type[:6]]
        ev += [_evidence(f"Share of cases with {t['type'].replace('_', ' ')}", t["case_pct"], "deviations", "%")
               for t in by_type[:6]]
        if not deviation_type:
            ev.append(_evidence("Deviation rate", d["summary"]["deviation_rate_pct"], "deviations", "%"))
        return {"data": {"by_type": by_type, "rate_pct": d["summary"]["deviation_rate_pct"],
                         "conformance": d["conformance"], "delay_rule": d["summary"]["delay_rule"]}, "evidence": ev}

    def count_cases(self, has_activity: str | None = None, deviation_type: str | None = None,
                    min_duration_hours: float | None = None, max_duration_hours: float | None = None,
                    variant_id: str | None = None, deviation_activity: str | None = None) -> dict:
        tr = self.er.traces
        mask = pd.Series(True, index=tr.index)
        desc = []
        if has_activity:
            a = self.resolve_activity(has_activity)
            if not a:
                return {"data": {"error": f"No activity matching '{has_activity}'."}, "evidence": []}
            mask &= tr["trace"].map(lambda t: a in t)
            desc.append(f"containing '{a}'")
        if deviation_type or deviation_activity:
            d = self.er.deviations
            if deviation_type:
                d = d[d["type"] == deviation_type]
            if deviation_activity:
                a = self.resolve_activity(deviation_activity)
                if not a:
                    return {"data": {"error": f"No activity matching '{deviation_activity}'."}, "evidence": []}
                d = d[d["activity"] == a]
            mask &= tr["case_id"].isin(set(d["case_id"]))
            desc.append(f"with {(deviation_type or 'any deviation').replace('_', ' ')}"
                        + (f" on '{a}'" if deviation_activity else ""))
        if min_duration_hours is not None:
            mask &= tr["duration_h"] >= float(min_duration_hours)
            desc.append(f"lasting ≥ {min_duration_hours} h")
        if max_duration_hours is not None:
            mask &= tr["duration_h"] <= float(max_duration_hours)
            desc.append(f"lasting ≤ {max_duration_hours} h")
        if variant_id:
            mask &= tr["variant_id"] == variant_id
            desc.append(f"following {variant_id}")
        n, total = int(mask.sum()), int(len(tr))
        label = "Cases " + (" and ".join(desc) if desc else "(all)")
        return {"data": {"count": n, "total_cases": total, "pct": round_or_none(100 * n / total) if total else 0,
                         "filter": desc},
                "evidence": [_evidence(label, n, "case filter"), _evidence(f"{label} — share", round_or_none(100 * n / total), "case filter", "%")]}

    def get_resource_stats(self, resource: str | None = None, limit: int = 10) -> dict:
        r = self.results["resources"]
        if not r.get("available"):
            return {"data": {"error": "No resource column in this dataset."}, "evidence": []}
        rows = r["resources"]
        if resource:
            names = {x["resource"].casefold(): x for x in rows}
            m = difflib.get_close_matches(resource.casefold(), list(names), n=1, cutoff=0.6)
            rows = [names[m[0]]] if m else []
        rows = rows[:max(1, min(limit, 50))]
        ev = []
        for x in rows[:3]:
            ev += [_evidence(f"{x['resource']} — cases handled", x["cases_handled"], "resources"),
                   _evidence(f"{x['resource']} — median wait before their events", x["median_waiting_time_hours"],
                       "resources", "hours")]
        return {"data": {"resources": rows, "disclaimer": r["disclaimer"]}, "evidence": ev}

    def get_case(self, case_id: str) -> dict:
        tr = self.er.traces
        row = tr[tr["case_id"] == str(case_id)]
        if row.empty:
            return {"data": {"error": f"Case '{case_id}' not found."}, "evidence": []}
        row = row.iloc[0]
        devs = self.er.deviations[self.er.deviations["case_id"] == str(case_id)]
        return {"data": {"case_id": case_id, "trace": trace_text(row["trace"]), "variant_id": row["variant_id"],
                         "duration_hours": round_or_none(row["duration_h"]),
                         "deviations": devs[["type", "activity", "description"]].to_dict("records")},
                "evidence": [_evidence(f"Case {case_id} — duration", round_or_none(row["duration_h"]), "cases", "hours"),
                             _evidence(f"Case {case_id} — deviations", int(len(devs)), "deviations")]}

    def get_data_quality(self) -> dict:
        v = self.validation
        keys = ("total_rows", "valid_rows", "invalid_rows", "duplicate_rows", "missing_case_ids",
                "invalid_timestamps", "impossible_timestamps", "malformed_rows", "single_event_cases")
        return {"data": {k: v.get(k) for k in keys} | {"warnings": v.get("warnings", []),
                                                       "activity_name_merges": v.get("activity_name_merges", {})},
                "evidence": [_evidence(k.replace("_", " ").capitalize(), v.get(k), "validation") for k in keys
                             if v.get(k) is not None][:6]}

    # ---- LLM tool specs
    def specs(self) -> list[dict]:
        s = lambda **p: {"type": "object", "properties": p}  # noqa: E731
        return [
            {"name": "get_overview", "description": "Case counts, durations, variants, deviation and conformance rates.",
             "input_schema": s()},
            {"name": "get_bottlenecks", "description": "Activities ranked by bottleneck score, plus slowest transitions.",
             "input_schema": s(limit={"type": "integer"})},
            {"name": "get_activity_stats", "description": "Frequency and waiting-time statistics for one activity.",
             "input_schema": {**s(activity={"type": "string"}), "required": ["activity"]}},
            {"name": "get_transition_stats", "description": "Statistics for a directly-follows transition A → B.",
             "input_schema": {**s(source={"type": "string"}, target={"type": "string"}),
                              "required": ["source", "target"]}},
            {"name": "get_variants", "description": "Most common process variants and coverage.",
             "input_schema": s(limit={"type": "integer"})},
            {"name": "get_deviation_summary", "description": "Deviation counts by type vs. the dominant path.",
             "input_schema": s(deviation_type={"type": "string", "enum": [
                 "skipped_activity", "missing_activity", "unexpected_activity", "out_of_order", "rework", "loop",
                 "long_transition", "alternative_outcome", "incomplete_case"]})},
            {"name": "count_cases", "description": "Count cases matching filters (all optional, combined with AND).",
             "input_schema": s(has_activity={"type": "string"}, deviation_type={"type": "string"},
                               min_duration_hours={"type": "number"}, max_duration_hours={"type": "number"},
                               variant_id={"type": "string"},
                               deviation_activity={"type": "string",
                                                   "description": "Only deviations involving this activity."})},
            {"name": "get_resource_stats", "description": "Observed metrics per resource (not performance ratings).",
             "input_schema": s(resource={"type": "string"}, limit={"type": "integer"})},
            {"name": "get_case", "description": "Trace, duration and deviations of a single case id.",
             "input_schema": {**s(case_id={"type": "string"}), "required": ["case_id"]}},
            {"name": "get_data_quality", "description": "Validation report for the uploaded file.", "input_schema": s()},
        ]

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if name not in {t["name"] for t in self.specs()} or fn is None:
            return {"data": {"error": f"Unknown tool {name}"}, "evidence": []}
        try:
            return fn(**(args or {}))
        except TypeError as exc:
            return {"data": {"error": f"Bad arguments: {exc}"}, "evidence": []}
