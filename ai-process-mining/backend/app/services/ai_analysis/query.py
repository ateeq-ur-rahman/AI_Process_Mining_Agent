"""Answering questions in the AI analyst chat.

With an LLM, the model chooses which query tools to call and phrases the answer.
Without one (or when the call fails), a keyword router picks the same tools and fills
a template. Either way the numbers come from the tools.
"""
from __future__ import annotations

import json
import logging
import re
import time

from app.core.logging import log_event
from app.services.ai_analysis.guardrails import causal_language, unverified_numbers
from app.services.ai_analysis.llm import LLMClient, LLMUnavailable
from app.services.ai_analysis.prompts import PROMPT_VERSION, QUERY_SYSTEM
from app.services.ai_analysis.query_tools import QueryTools
from app.services.stats import trace_text

logger = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 5  # enough for "look up X, then compare with Y"; stops runaway loops

# Question keyword -> deviation type. First match wins, in this order.
DEVIATION_KEYWORDS = {
    "rework": "rework", "loop": "loop", "skip": "skipped_activity", "skipped": "skipped_activity",
    "unexpected": "unexpected_activity", "out of order": "out_of_order", "incomplete": "incomplete_case",
    "open case": "incomplete_case", "missing": "missing_activity", "delay": "long_transition",
    "late": "long_transition", "long transition": "long_transition", "cancel": "alternative_outcome",
    "reject": "alternative_outcome",
}


def _n_cases(n: int) -> str:
    return f"{n:,} case" + ("" if n == 1 else "s")


def _h(x) -> str:
    if x is None:
        return "n/a"
    return f"{x:,.1f} h" + (f" (~{x / 24:.1f} days)" if x >= 48 else "")


def answer_deterministic(tools: QueryTools, question: str) -> dict:
    """Keyword routing, checked top to bottom. Crude on purpose: it only has to cover
    the common questions well enough that the app is useful with no LLM configured.
    More specific patterns (a case id, "slow" + an activity name) come before general ones."""
    q = question.lower()
    used: list[tuple[str, dict]] = []

    def call(name, **args):
        res = tools.call(name, args)
        used.append((name, res))
        return res["data"]

    case_match = re.search(r"\b([A-Za-z]{2,}[-_]?\d{3,})\b", question)
    if case_match and (tools.er.traces["case_id"] == case_match.group(1)).any():
        d = call("get_case", case_id=case_match.group(1))
        devs = " ".join(x["description"] for x in d["deviations"][:5]) or "none."
        answer = (f"Case {d['case_id']} followed {d['variant_id']}: {d['trace']}. It took {_h(d['duration_hours'])}. "
                  f"Deviations: {devs}")
    elif any(w in q for w in ("data quality", "invalid", "duplicate", "bad rows", "validation")):
        d = call("get_data_quality")
        answer = (f"{d['invalid_rows']:,} of {d['total_rows']:,} rows were excluded: {d['duplicate_rows']} duplicates, "
                  f"{d['missing_case_ids']} missing case ids, {d['invalid_timestamps']} invalid and "
                  f"{d['impossible_timestamps']} impossible timestamps, {d['malformed_rows']} malformed rows.")
    elif any(w in q for w in ("slow", "wait", "delay", "long", "stuck")) and \
            (acts := tools.activities_mentioned(question)) and "bottleneck" not in q:
        parts = []
        for a_name in acts:
            d = call("get_activity_stats", activity=a_name)
            a, b = d["activity"], d["bottleneck"]
            parts.append(f"{a_name}: median wait before it {_h(a['median_duration_hours'])} (P90 "
                         f"{_h(a['p90_duration_hours'])}), {a['case_pct']}% of cases"
                         + (f", bottleneck score {b['score']} ({b['indicator']})" if b.get("score") is not None else ""))
        answer = "; ".join(parts) + "."
    elif any(w in q for w in ("bottleneck", "slowest", "biggest delay", "where do cases wait", "wait the longest",
                              "most time")):
        d = call("get_bottlenecks", limit=3)
        top = d["activities"][0]
        others = ", ".join(f"{a['activity']} (score {a['score']})" for a in d["activities"][1:3])
        answer = (f"{top['activity']} is the top-ranked bottleneck candidate (score {top['score']}, {top['indicator']}). "
                  f"Median waiting time before it is {_h(top['median_waiting_time_hours'])} "
                  f"(P90 {_h(top['p90_waiting_time_hours'])}); it affects {top['affected_cases_pct']}% of cases and "
                  f"accounts for {top['wait_share_pct']}% of all waiting time. Next: {others}. "
                  "The score is a relative ranking; the data does not establish why the wait occurs.")
    elif (dt := next((v for k, v in DEVIATION_KEYWORDS.items() if k in q), None)) and any(
            w in q for w in ("how many", "number", "count", "cases", "orders", "%", "percent", "share", "which")):
        act = tools.find_activity_in_text(question)
        if act:
            d = call("count_cases", deviation_type=dt, deviation_activity=act)
            answer = (f"{_n_cases(d['count'])}, representing {d['pct']}% of all cases, have a "
                      f"{dt.replace('_', ' ')} deviation involving '{act}'.")
        else:
            d = call("count_cases", deviation_type=dt)
            s = call("get_deviation_summary", deviation_type=dt)
            top = ", ".join(f"{x['activity']} ({x['occurrences']})" for x in (s["by_type"][0]["top_activities"][:3]
                                                                                if s["by_type"] else []))
            answer = (f"{_n_cases(d['count'])}, representing {d['pct']}% of all cases, have "
                      f"{dt.replace('_', ' ')} deviations." + (f" Most frequent activities involved: {top}." if top else ""))
    elif any(w in q for w in ("deviat", "conform", "happy path", "dominant path", "standard path")):
        d = call("get_deviation_summary")
        parts = ", ".join(f"{t['type'].replace('_', ' ')} {t['case_pct']}%" for t in d["by_type"][:6])
        answer = (f"{d['conformance']['conformance_rate_pct']}% of cases follow the dominant path exactly "
                  f"({d['conformance']['dominant_path_text']}); {d['rate_pct']}% have at least one deviation. "
                  f"By type (share of cases): {parts}.")
    elif any(w in q for w in ("variant", "path", "most common", "typical flow", "sequence")):
        d = call("get_variants", limit=3)
        v = d["variants"]
        answer = (f"There are {d['summary']['unique_variants']} variants. The most common ({v[0]['variant_id']}, "
                  f"{v[0]['percentage_of_cases']}% of cases) is: {v[0]['trace_text']}. "
                  f"{d['summary']['coverage_statement']}")
    elif any(w in q for w in ("resource", "employee", "who ", "team", "staff", "person")):
        d = call("get_resource_stats", limit=5)
        if "error" in d:
            answer = d["error"]
        else:
            top = "; ".join(f"{r['resource']}: {r['cases_handled']:,} cases, median wait "
                            f"{_h(r['median_waiting_time_hours'])}" for r in d["resources"][:5])
            answer = f"Resources by event volume — {top}. {d['disclaimer']}"
    elif (act := tools.find_activity_in_text(question)):
        d = call("get_activity_stats", activity=act)
        a, b = d["activity"], d["bottleneck"]
        answer = (f"{act} runs {a['frequency']:,} times in {a['case_pct']}% of cases. Median waiting time before it is "
                  f"{_h(a['median_duration_hours'])} (P90 {_h(a['p90_duration_hours'])})."
                  + (f" Bottleneck score {b['score']} ({b['indicator']})." if b.get("score") is not None else ""))
    elif any(w in q for w in ("how long", "duration", "cycle time", "lead time", "average", "median", "p95", "take")):
        d = call("get_overview")
        answer = (f"Average case duration is {_h(d['avg_case_duration_hours'])}; median {_h(d['median_case_duration_hours'])}, "
                  f"P90 {_h(d['p90_case_duration_hours'])}, P95 {_h(d['p95_case_duration_hours'])}.")
    elif any(w in q for w in ("how many", "total", "cases", "orders", "overview", "summary", "summar")):
        d = call("get_overview")
        answer = (f"The log has {d['total_cases']:,} cases ({d['completed_cases']:,} completed, {d['incomplete_cases']:,} "
                  f"incomplete) and {d['total_events']:,} events across {d['unique_activities']} activities, with "
                  f"{d['unique_variants']} variants. Median case duration is {_h(d['median_case_duration_hours'])}.")
    else:
        d = call("get_overview")
        answer = ("I can answer questions about bottlenecks, durations, variants, deviations (rework, loops, skipped "
                  "steps, delays), specific activities, resources, individual cases and data quality. "
                  f"For context: {d['total_cases']:,} cases, dominant path {trace_text(d['dominant_path'])}.")

    if q.strip().startswith("why") or " why " in f" {q} ":
        answer += (" Note: event data shows where and how often this happens, not why. Factors worth investigating "
                   "include workload, rules/policies, external dependencies and data recording practices.")
    evidence = [e for _, res in used for e in res["evidence"]]
    return {"answer": answer, "evidence": evidence, "tools_used": [n for n, _ in used], "mode": "deterministic",
            "flags": []}


def answer_with_llm(client: LLMClient, tools: QueryTools, question: str, history: list[dict] | None = None
                    ) -> tuple[dict, dict]:
    messages: list[dict] = []
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            messages.append({"role": h["role"], "content": h["content"][:2000]})
    messages.append({"role": "user", "content": question[:2000]})
    specs = tools.specs()
    used: list[tuple[str, dict, dict]] = []
    meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
            "input_chars": len(question)}
    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.create(system=QUERY_SYSTEM, messages=messages, tools=specs,
                             tool_choice={"type": "any"} if not used else None, max_tokens=1200)
        meta["llm_calls"] += 1
        meta["input_tokens"] += resp.input_tokens
        meta["output_tokens"] += resp.output_tokens
        meta["latency_ms"] += resp.latency_ms
        calls = resp.tool_uses()
        if not calls:
            answer = resp.text()
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for c in calls:
            res = tools.call(c["name"], c.get("input") or {})
            used.append((c["name"], c.get("input") or {}, res))
            results.append({"type": "tool_result", "tool_use_id": c["id"],
                            "content": json.dumps(res["data"], default=str)[:12000]})
        messages.append({"role": "user", "content": results})
    else:
        answer = ""
    if not used or not answer:
        raise LLMUnavailable("LLM did not produce a grounded answer.")
    source_text = json.dumps([r["data"] for _, _, r in used], default=str)
    flags = []
    bad = unverified_numbers(answer, source_text)
    if bad:
        flags.append(f"Numbers not found in tool results (verify before use): {', '.join(bad)}")
    causal = causal_language(answer)
    if causal:
        flags.append(f"Answer uses causal wording ({', '.join(causal)}); the event data does not establish causes.")
    return ({"answer": answer, "evidence": [e for _, _, r in used for e in r["evidence"]],
             "tools_used": [n for n, _, _ in used], "mode": "llm", "flags": flags}, meta)


def answer_question(client: LLMClient | None, tools: QueryTools, question: str,
                    history: list[dict] | None = None) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    meta = {"mode": "deterministic", "llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
            "input_chars": len(question), "error": None}
    out = None
    if client is not None:
        try:
            out, llm_meta = answer_with_llm(client, tools, question, history)
            meta |= llm_meta | {"mode": "llm"}
        except LLMUnavailable as exc:
            meta["error"] = str(exc)[:300]
    if out is None:
        out = answer_deterministic(tools, question)
        if meta["error"]:
            out["flags"].append("LLM unavailable; answered with the rule-based engine.")
    out["prompt_version"] = PROMPT_VERSION
    meta["total_ms"] = int((time.perf_counter() - t0) * 1000)
    log_event(logger, "ai.query", mode=meta["mode"], llm_calls=meta["llm_calls"], llm_latency_ms=meta["latency_ms"],
              input_tokens=meta["input_tokens"], output_tokens=meta["output_tokens"], tools=out["tools_used"],
              error=meta["error"])
    return out, meta
