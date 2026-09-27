import pandas as pd
from conftest import make_events

from app.services.engine import run_engine
from app.services.normalization.normalizer import normalize_events
from app.services.process_discovery.dfg import discover_dfg
from app.services.process_discovery.traces import build_event_frame, build_traces


def test_events_sorted_within_case_regardless_of_input_order():
    ev = make_events([("1", "C", "2026-01-01 12:00"), ("1", "A", "2026-01-01 10:00"),
                      ("2", "A", "2026-01-01 09:00"), ("1", "B", "2026-01-01 11:00")])
    tr = build_traces(build_event_frame(ev)).set_index("case_id")
    assert tr.loc["1", "trace"] == ("A", "B", "C")
    assert tr.loc["2", "trace"] == ("A",)
    assert tr.loc["1", "duration_h"] == 2.0


def test_case_grouping_and_waiting_time():
    ev = build_event_frame(make_events([("1", "A", "2026-01-01 10:00"), ("1", "B", "2026-01-01 13:30")]))
    b = ev[ev["activity"] == "B"].iloc[0]
    assert b["prev_activity"] == "A"
    assert b["wait_h"] == 3.5
    assert pd.isna(ev[ev["activity"] == "A"].iloc[0]["wait_h"])


def test_activity_name_normalization_preserves_original():
    ev = make_events([("1", "Order Approved", "2026-01-01 10:00"), ("2", "order  approved ", "2026-01-01 10:00"),
                      ("3", "order_approved", "2026-01-01 10:00")])
    assert ev["activity"].nunique() == 1
    assert ev["activity"].iloc[0] == "Order Approved"
    assert set(ev["original_activity"]) == {"Order Approved", "order  approved ", "order_approved"}


def test_dfg_node_count_and_edge_frequency(simple_log):
    ev = build_event_frame(make_events(simple_log))
    tr = build_traces(ev)
    g = discover_dfg(ev, tr)
    assert {n["id"] for n in g["nodes"]} == {"A", "B", "C", "D", "X"}
    e = {(x["source"], x["target"]): x for x in g["edges"]}
    # A→B: 6 standard + 2 rework + 1 unexpected-X case = 9
    assert e[("A", "B")]["frequency"] == 9
    # B→C: 6 + 2*2 (rework cases pass B→C twice) = 10, in 8 distinct cases
    assert e[("B", "C")]["frequency"] == 10
    assert e[("B", "C")]["cases"] == 8
    assert e[("C", "B")]["frequency"] == 2
    assert e[("A", "C")]["frequency"] == 1
    assert g["start_activities"][0]["activity"] == "A"
    assert g["end_activities"][0]["activity"] == "D"


def test_not_hardcoded_process():
    """A process unrelated to O2C is discovered just the same."""
    ev = make_events([("t1", "Ticket Opened", "2026-01-01 10:00"), ("t1", "Triage", "2026-01-01 11:00"),
                      ("t1", "Resolved", "2026-01-01 15:00")])
    res = run_engine(ev).results
    assert res["overview"]["dominant_path"] == ["Ticket Opened", "Triage", "Resolved"]


def test_normalize_case_ids_to_string():
    df = pd.DataFrame({"source_row": [2], "case_id": [123], "original_activity": ["A"],
                       "timestamp": [pd.Timestamp("2026-01-01", tz="UTC")]})
    ev, _ = normalize_events(df)
    assert ev["case_id"].iloc[0] == "123"
