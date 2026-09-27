from conftest import hours, make_events

from app.services.deviations.deviations import analyse_trace
from app.services.engine import run_engine

DOM = ("A", "B", "C", "D")
S = frozenset(DOM)
DONE = frozenset({"D"})


def types(trace):
    return types_with(trace, DONE)


def types_with(trace, completion):
    return [(t, a) for t, a, _, _ in analyse_trace(tuple(trace), DOM, S, completion)]


def test_conforming_trace_has_no_deviation():
    assert types("ABCD") == []


def test_skipped_activity():
    assert types("ACD") == [("skipped_activity", "B")]


def test_missing_activity_in_incomplete_case():
    assert types("AB") == [("missing_activity", "C"), ("missing_activity", "D")]


def test_unexpected_activity():
    assert types("ABXCD") == [("unexpected_activity", "X")]


def test_rework():
    t = types("ABCBCD")
    assert ("rework", "B") in t and ("rework", "C") in t
    desc = [d for ty, _, _, d in analyse_trace(tuple("ABCBCD"), DOM, S, DONE) if ty == "rework"][0]
    assert "rework around B/C" in desc


def test_loop():
    t = types("ABCCD")
    assert ("loop", "C") in t
    assert all(ty != "rework" for ty, _ in t)


def test_loop_and_rework_example_from_spec():
    t = types(["A", "B", "C", "B", "B", "C", "D"])
    assert ("loop", "B") in t and ("rework", "B") in t


def test_out_of_order():
    # LCS keeps A, B, D in place, so C is the step that moved.
    assert types("ACBD") == [("out_of_order", "C")]


def test_alternative_outcome_is_not_reported_as_missing_steps():
    done = frozenset({"D", "R"})
    assert types_with("ABR", done) == [("unexpected_activity", "R")]


def test_fully_conforming_log_has_no_deviations():
    rows = []
    for i in range(5):
        t = hours("2026-01-01 08:00", 0, 1, 2)
        rows += [(f"C{i}", a, ts) for a, ts in zip("ABC", t)]
    res = run_engine(make_events(rows)).results
    assert res["deviations"]["summary"]["total_deviations"] == 0
    assert res["overview"]["conformance_rate_pct"] == 100.0
    assert res["deviations"]["conformance"]["cases_with_extra_steps"] == 0


def test_long_transition_flagged():
    rows = []
    for i in range(30):
        t = hours("2026-01-01 08:00", 0, 1, 2)
        rows += [(f"N{i}", a, ts) for a, ts in zip("ABC", t)]
    t = hours("2026-01-05 08:00", 0, 60, 61)
    rows += [("SLOW", a, ts) for a, ts in zip("ABC", t)]
    er = run_engine(make_events(rows))
    d = er.deviations
    late = d[d["type"] == "long_transition"]
    assert list(late["case_id"]) == ["SLOW"]
    assert late.iloc[0]["activity"] == "B"
    assert "60.0h" in late.iloc[0]["description"]


def test_engine_deviation_summary(simple_log):
    res = run_engine(make_events(simple_log)).results["deviations"]
    by = {t["type"]: t for t in res["summary"]["by_type"]}
    assert by["rework"]["cases"] == 2
    assert by["skipped_activity"]["cases"] == 1
    assert by["unexpected_activity"]["cases"] == 1
    assert res["conformance"]["conformance_rate_pct"] == 60.0
    assert "not formal BPMN" in res["conformance"]["method"]
