import json

import pytest
from conftest import make_events

from app.services.ai_analysis.context import build_llm_payload
from app.services.ai_analysis.llm import LLMResponse, LLMUnavailable
from app.services.ai_analysis.query import answer_question
from app.services.ai_analysis.query_tools import QueryTools
from app.services.ai_analysis.report import generate_report
from app.services.ai_analysis.schemas import AnalysisReport
from app.services.engine import run_engine


class MockLLM:
    model = "mock-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, *, system, messages, tools=None, tool_choice=None, max_tokens=None):
        self.calls.append({"system": system, "messages": messages, "tools": tools, "tool_choice": tool_choice})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tool_use(name, inp, id_="tu1"):
    return LLMResponse(content=[{"type": "tool_use", "id": id_, "name": name, "input": inp}],
                       stop_reason="tool_use", input_tokens=100, output_tokens=50, latency_ms=5)


@pytest.fixture
def er(simple_log):
    return run_engine(make_events(simple_log))


GOOD_REPORT = {
    "summary": "Ten cases were observed; most follow the dominant path.",
    "key_findings": [{
        "title": "C has the longest waits",
        "description": "Waiting before C is the highest observed in the log.",
        "evidence_fact_ids": ["bottleneck[C].median_wait_hours", "made.up.fact"],
        "severity": "medium",
        "possible_explanations": ["Workload at C (to be verified)"],
        "recommended_investigations": ["Check queue size at C"],
    }],
    "data_quality_notes": [], "limitations": ["Small sample."],
}


def test_ai_receives_structured_metrics_not_raw_events(er):
    llm = MockLLM([tool_use("submit_report", GOOD_REPORT)])
    generate_report(llm, er.results, {"total_rows": 30, "invalid_rows": 0})
    sent = llm.calls[0]["messages"][0]["content"]
    payload = json.loads(sent.split("\n", 1)[1])
    assert set(payload) == {"facts", "methodology"}
    assert "overview.total_cases" in payload["facts"]
    # No case ids or event-level rows are sent.
    for cid in er.traces["case_id"]:
        assert f'"{cid}"' not in sent
    assert "timestamp" not in json.dumps(payload["facts"])
    assert llm.calls[0]["tool_choice"] == {"type": "tool", "name": "submit_report"}


def test_ai_output_follows_schema_and_evidence_is_server_resolved(er):
    llm = MockLLM([tool_use("submit_report", GOOD_REPORT)])
    report, meta = generate_report(llm, er.results, None)
    AnalysisReport.model_validate(report.model_dump())
    f = report.key_findings[0]
    assert [e.fact_id for e in f.evidence] == ["bottleneck[C].median_wait_hours"]
    assert f.evidence[0].value.endswith("hours")
    assert any("unknown evidence" in x for x in report.guardrail_flags)
    assert f.drilldown.kind == "activity" and f.drilldown.activity == "C"
    assert meta["mode"] == "llm" and meta["llm_calls"] == 1


def test_invalid_ai_output_is_retried_then_falls_back(er):
    bad = {"summary": "x", "key_findings": []}
    llm = MockLLM([tool_use("submit_report", bad), tool_use("submit_report", bad, "tu2")])
    report, meta = generate_report(llm, er.results, None)
    assert meta["mode"] == "deterministic" and meta["error"]
    assert report.generated_by["mode"] == "deterministic"
    assert len(llm.calls) == 2


def test_causal_claims_are_flagged(er):
    r = json.loads(json.dumps(GOOD_REPORT))
    r["key_findings"][0]["description"] = "C is slow because the team is understaffed."
    report, _ = generate_report(MockLLM([tool_use("submit_report", r)]), er.results, None)
    assert any("causal wording" in x for x in report.guardrail_flags)


def test_engine_works_when_llm_unavailable(er):
    llm = MockLLM([LLMUnavailable("down")])
    report, meta = generate_report(llm, er.results, None)
    assert meta["mode"] == "deterministic"
    assert report.key_findings and all(f.evidence for f in report.key_findings)


def test_no_llm_configured_report(er):
    report, meta = generate_report(None, er.results, None)
    assert meta["llm_calls"] == 0
    assert report.summary.startswith("The log contains 10 cases")


def test_query_with_llm_uses_tools_and_flags_invented_numbers(er):
    tools = QueryTools(er)
    llm = MockLLM([
        tool_use("count_cases", {"deviation_type": "rework"}),
        LLMResponse(content=[{"type": "text", "text": "2 cases (20.0%) had rework; about 999 hours were lost."}],
                    stop_reason="end_turn"),
    ])
    out, meta = answer_question(llm, tools, "How many orders experienced rework?")
    assert out["mode"] == "llm" and out["tools_used"] == ["count_cases"]
    assert any("999" in f for f in out["flags"])
    assert out["evidence"]
    assert llm.calls[0]["tool_choice"] == {"type": "any"}


def test_deterministic_query_answers(er):
    tools = QueryTools(er)
    out, _ = answer_question(None, tools, "How many orders experienced rework?")
    assert out["answer"].startswith("2 cases, representing 20.0% of all cases")
    out, _ = answer_question(None, tools, "Where is the biggest bottleneck?")
    assert "bottleneck candidate" in out["answer"] and out["evidence"]
    out, _ = answer_question(None, tools, "Why is it slow?")
    assert "not why" in out["answer"]


def test_payload_size_is_bounded(er):
    payload = build_llm_payload(er.results, None)
    assert len(json.dumps(payload)) < 60_000


def test_deviation_count_scoped_to_activity(er):
    out, _ = answer_question(None, QueryTools(er), "How many cases skipped B?")
    assert out["answer"].startswith("1 case,")
    assert "'B'" in out["answer"]


def test_partial_activity_mentions(er):
    out, _ = answer_question(None, QueryTools(er), "Why is C so slow?")
    assert out["answer"].startswith("C: median wait") and "not why" in out["answer"]


def test_llm_http_errors_become_readable_messages(monkeypatch):
    import httpx

    from app.core.config import load_settings
    from app.services.ai_analysis.llm import AnthropicClient

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    client = AnthropicClient(load_settings())
    client._client = httpx.Client(base_url="https://llm.test",
                                  transport=httpx.MockTransport(lambda req: httpx.Response(401, json={})))
    with pytest.raises(LLMUnavailable, match="API key was rejected"):
        client.create(system="s", messages=[{"role": "user", "content": "hi"}])
