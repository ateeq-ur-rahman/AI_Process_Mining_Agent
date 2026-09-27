"""The analysis report. Written by the LLM when one is configured, from templates otherwise.

In both cases the evidence values shown next to a finding are looked up from the
engine's fact sheet by id, never taken from model output.
"""
from __future__ import annotations

import json
import logging
import time

from pydantic import ValidationError

from app.core.logging import log_event
from app.services.ai_analysis.context import (
    build_facts,
    build_llm_payload,
    drilldown_for,
    format_value,
)
from app.services.ai_analysis.guardrails import causal_language
from app.services.ai_analysis.llm import LLMClient, LLMUnavailable
from app.services.ai_analysis.prompts import PROMPT_VERSION, REPORT_SYSTEM
from app.services.ai_analysis.schemas import (
    REPORT_TOOL,
    AnalysisReport,
    Evidence,
    Finding,
    LLMReport,
)
from app.services.stats import trace_text

logger = logging.getLogger(__name__)

STANDARD_LIMITATIONS = [
    "Timing is derived from event timestamps. Without start timestamps, waiting and processing time "
    "cannot be separated; 'waiting time' is the time between consecutive events.",
    "The dominant path is the most frequent completed variant, not a normative or approved process model.",
    "Bottleneck scores rank activities relative to each other in this dataset; they are not causal.",
    "Event data shows where time is spent and how cases flow, not why. Causes require further investigation.",
]
ADDITIONAL_DATA = [
    "Activity start timestamps (to separate queueing time from work time).",
    "Case attributes such as order value, customer segment, channel and priority, for segment comparisons.",
    "Queue sizes or workload per team over time.",
    "Service-level targets per step, to distinguish expected from problematic delays.",
    "Business calendars (working hours, holidays) for business-time durations.",
]
GENERIC_EXPLANATIONS = [
    "Workload or queue length at this step",
    "Policies or approval rules governing when the step can proceed",
    "Dependencies on external parties (customers, carriers, other systems)",
    "Upstream data completeness or hand-off delays",
]
GENERIC_INVESTIGATIONS = [
    "Compare waiting time by week/month to see whether the delay is constant or episodic",
    "Segment affected cases by attributes (amount, priority, region) to see which wait longest",
    "Check backlog/queue size at this step over time",
    "Review the rules and hand-offs that determine when this step starts",
]


class ReportError(Exception):
    pass


def resolve_findings(llm_report: LLMReport, facts: dict) -> tuple[list[Finding], list[str]]:
    findings, flags = [], []
    for f in llm_report.key_findings:
        valid = [fid for fid in f.evidence_fact_ids if fid in facts]
        unknown = [fid for fid in f.evidence_fact_ids if fid not in facts]
        if unknown:
            flags.append(f"Finding '{f.title}': ignored unknown evidence ids {unknown}.")
        if not valid:
            flags.append(f"Finding '{f.title}' was dropped: it cited no verifiable evidence.")
            continue
        causal = causal_language(f.description)
        if causal:
            flags.append(f"Finding '{f.title}' uses causal wording ({', '.join(causal)}) that the data does "
                         "not establish; treat it as a hypothesis.")
        drill = next((d for d in (drilldown_for(fid) for fid in valid) if d and d["kind"] != "overview"), None) \
            or drilldown_for(valid[0])
        findings.append(Finding(
            title=f.title, description=f.description, severity=f.severity,
            evidence=[Evidence(fact_id=fid, metric=facts[fid]["label"], value=format_value(facts[fid])) for fid in valid],
            possible_explanations=f.possible_explanations,
            recommended_investigations=f.recommended_investigations,
            drilldown=drill,
        ))
    return findings, flags


MAX_REPORT_ATTEMPTS = 2  # first try, plus one retry that shows the model its validation error


def _build_llm_report(tool_input: dict, facts: dict, model: str) -> AnalysisReport:
    parsed = LLMReport.model_validate(tool_input)
    findings, flags = resolve_findings(parsed, facts)
    if not findings:
        raise ReportError("No findings with verifiable evidence.")
    summary_causal = causal_language(parsed.summary)
    if summary_causal:
        flags.append(f"Summary uses causal wording ({', '.join(summary_causal)}); "
                     "the data does not establish causes.")
    return AnalysisReport(
        summary=parsed.summary,
        key_findings=findings,
        data_quality_notes=parsed.data_quality_notes,
        limitations=list(dict.fromkeys(parsed.limitations + STANDARD_LIMITATIONS)),
        additional_data_suggestions=parsed.additional_data_suggestions or ADDITIONAL_DATA,
        guardrail_flags=flags,
        generated_by={"mode": "llm", "model": model, "prompt_version": PROMPT_VERSION},
    )


def generate_llm_report(client: LLMClient, results: dict, validation: dict | None, focus: str | None = None
                        ) -> tuple[AnalysisReport, dict]:
    payload = build_llm_payload(results, validation)
    facts = payload["facts"]
    user = "Analyse this process. Facts and methodology (JSON):\n" + json.dumps(payload, default=str)
    if focus:
        user += f"\n\nThe user asked to focus on: {focus[:500]}"
    messages: list[dict] = [{"role": "user", "content": user}]
    meta = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0, "input_chars": len(user)}
    problem = "LLM output failed validation."

    for _ in range(MAX_REPORT_ATTEMPTS):
        resp = client.create(system=REPORT_SYSTEM, messages=messages, tools=[REPORT_TOOL],
                             tool_choice={"type": "tool", "name": "submit_report"})
        meta["llm_calls"] += 1
        meta["input_tokens"] += resp.input_tokens
        meta["output_tokens"] += resp.output_tokens
        meta["latency_ms"] += resp.latency_ms

        tool_uses = resp.tool_uses()
        if not tool_uses:
            problem = "Model did not call submit_report."
            messages += [{"role": "assistant", "content": resp.content or [{"type": "text", "text": "."}]},
                         {"role": "user", "content": "Call submit_report now."}]
            continue

        call = tool_uses[0]
        try:
            return _build_llm_report(call.get("input", {}), facts, client.model), meta
        except (ValidationError, ReportError) as exc:
            problem = str(exc)[:1500]
            messages += [
                {"role": "assistant", "content": resp.content},
                {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": call["id"], "is_error": True,
                    "content": f"Invalid report: {problem}. Resubmit following the schema "
                               "and cite only fact ids that exist.",
                }]},
            ]
    raise ReportError(problem)


def generate_deterministic_report(results: dict, validation: dict | None, reason: str | None = None) -> AnalysisReport:
    """Template-based report from engine outputs — used when no LLM is configured or it fails."""
    facts = build_facts(results, validation)
    o = results["overview"]
    findings: list[Finding] = []

    def evidence_for(*ids):
        return [Evidence(fact_id=i, metric=facts[i]["label"], value=format_value(facts[i])) for i in ids if i in facts]

    scored = [a for a in results["bottlenecks"]["activities"] if a["score"] is not None]
    for rank, a in enumerate(scored[:3], start=1):
        if a["indicator"] == "LOW":
            continue
        p = f"bottleneck[{a['activity']}]"
        findings.append(Finding(
            title=f"{a['activity']} is a {a['indicator'].lower()}-ranked bottleneck candidate",
            description=(f"{a['activity']} ranks {rank} of {len(scored)} by bottleneck score. The median waiting time "
                         f"before it is {a['median_waiting_time_hours']} h (P90 {a['p90_waiting_time_hours']} h); it "
                         f"occurs in {a['affected_cases_pct']}% of cases and accounts for {a['wait_share_pct']}% of all "
                         "waiting time in the log. The event data does not establish why."),
            evidence=evidence_for(f"{p}.rank", f"{p}.median_wait_hours", f"{p}.p90_wait_hours", f"{p}.affected_cases_pct",
                        f"{p}.wait_share_pct", f"{p}.score"),
            severity="high" if a["indicator"] == "HIGH" else "medium",
            possible_explanations=GENERIC_EXPLANATIONS,
            recommended_investigations=GENERIC_INVESTIGATIONS,
            drilldown={"kind": "activity", "activity": a["activity"]},
        ))

    for t in results["deviations"]["summary"]["by_type"]:
        if t["case_pct"] is None or t["case_pct"] < 5:
            continue
        p = f"deviation[{t['type']}]"
        top = ", ".join(x["activity"] for x in t["top_activities"][:3])
        findings.append(Finding(
            title=f"{t['type'].replace('_', ' ').capitalize()} in {t['case_pct']}% of cases",
            description=(f"{t['cases']:,} cases ({t['case_pct']}%) show {t['type'].replace('_', ' ')} relative to the "
                         f"dominant path, most often involving: {top}."),
            evidence=evidence_for(f"{p}.cases", f"{p}.case_pct", f"{p}.occurrences", f"{p}.top_activities"),
            severity="high" if t["case_pct"] >= 20 else "medium" if t["case_pct"] >= 10 else "low",
            possible_explanations=["Legitimate alternative handling paths (e.g. policy exceptions)",
                                   "Corrections or changes requested during the case",
                                   "Recording practices (events logged late, in a different order, or not at all)"],
            recommended_investigations=["Review a sample of affected cases end to end",
                                        "Check whether these paths are permitted by policy",
                                        "Compare durations of affected vs. unaffected cases"],
            drilldown={"kind": "deviation", "deviation_type": t["type"]},
        ))

    v = results["variants"]["summary"]
    findings.append(Finding(
        title="Process variant concentration",
        description=(f"The dominant path ({trace_text(o['dominant_path'])}) is followed exactly by "
                     f"{o['conformance_rate_pct']}% of cases. There are {v['unique_variants']} variants; "
                     f"{v['coverage_statement']}"),
        evidence=evidence_for("overview.conformance_rate_pct", "overview.unique_variants", "overview.top10_variant_coverage_pct",
                    "variant[V1].case_pct"),
        severity="low",
        possible_explanations=[],
        recommended_investigations=["Decide which variants are acceptable alternatives vs. exceptions",
                                    "Compare average durations across the top variants"],
        drilldown={"kind": "variant", "variant_id": "V1"},
    ))

    dq = []
    if validation:
        if validation.get("invalid_rows"):
            dq.append(f"{validation['invalid_rows']} of {validation['total_rows']} rows were excluded "
                      f"({validation.get('duplicate_rows', 0)} duplicates, {validation.get('invalid_timestamps', 0)} "
                      f"invalid timestamps, {validation.get('missing_case_ids', 0)} missing case ids).")
        for k, vs in (validation.get("activity_name_merges") or {}).items():
            dq.append(f"Activity spellings {vs} were merged as '{k}'.")
        dq.extend(validation.get("warnings") or [])

    summary = (f"The log contains {o['total_cases']:,} cases and {o['total_events']:,} events across "
               f"{o['unique_activities']} activities. Median case duration is {o['median_case_duration_hours']} h "
               f"(P95 {o['p95_case_duration_hours']} h). {o['conformance_rate_pct']}% of cases follow the dominant path "
               f"exactly and {o['deviation_rate_pct']}% show at least one deviation. "
               + (f"The highest-ranked bottleneck candidate is {scored[0]['activity']}." if scored else ""))
    limitations = list(STANDARD_LIMITATIONS)
    if reason:
        limitations.insert(0, f"Generated without an LLM ({reason}); text is template-based from computed metrics.")
    return AnalysisReport(
        summary=summary, key_findings=findings, data_quality_notes=dq, limitations=limitations,
        additional_data_suggestions=ADDITIONAL_DATA, guardrail_flags=[],
        generated_by={"mode": "deterministic", "model": None, "prompt_version": PROMPT_VERSION},
    )


def generate_report(client: LLMClient | None, results: dict, validation: dict | None,
                    focus: str | None = None) -> tuple[AnalysisReport, dict]:
    t0 = time.perf_counter()
    meta = {"mode": "deterministic", "llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
            "input_chars": 0, "error": None}
    if client is None:
        report = generate_deterministic_report(results, validation, reason="no LLM configured")
    else:
        try:
            report, llm_meta = generate_llm_report(client, results, validation, focus)
            meta |= llm_meta | {"mode": "llm"}
        except (LLMUnavailable, ReportError) as exc:
            meta["error"] = str(exc)[:500]
            report = generate_deterministic_report(results, validation, reason=f"LLM failed: {type(exc).__name__}")
    meta["total_ms"] = int((time.perf_counter() - t0) * 1000)
    log_event(logger, "ai.report", mode=meta["mode"], llm_calls=meta["llm_calls"], llm_latency_ms=meta["latency_ms"],
              input_tokens=meta["input_tokens"], output_tokens=meta["output_tokens"], prompt_version=PROMPT_VERSION,
              error=meta["error"])
    return report, meta


def report_to_markdown(report: AnalysisReport, dataset_name: str = "") -> str:
    lines = [f"# Process analysis report{(' — ' + dataset_name) if dataset_name else ''}", "",
             f"_Generated by: {report.generated_by.get('mode')}"
             + (f" ({report.generated_by.get('model')})" if report.generated_by.get("model") else "")
             + f", prompt version {report.generated_by.get('prompt_version')}_", "", "## Summary", "", report.summary, "",
             "## Key findings", ""]
    for i, f in enumerate(report.key_findings, 1):
        lines += [f"### {i}. {f.title}  `severity: {f.severity}`", "", f.description, "", "**Evidence**", ""]
        lines += [f"- {e.metric}: **{e.value}** (`{e.fact_id}`)" for e in f.evidence]
        if f.possible_explanations:
            lines += ["", "**Possible explanations (hypotheses, not established by the data)**", ""]
            lines += [f"- {x}" for x in f.possible_explanations]
        if f.recommended_investigations:
            lines += ["", "**Recommended investigations**", ""]
            lines += [f"- {x}" for x in f.recommended_investigations]
        lines.append("")
    for title, items in (("Data quality notes", report.data_quality_notes), ("Limitations", report.limitations),
                         ("Additional data that would help", report.additional_data_suggestions),
                         ("Guardrail flags", report.guardrail_flags)):
        if items:
            lines += [f"## {title}", ""] + [f"- {x}" for x in items] + [""]
    return "\n".join(lines)
