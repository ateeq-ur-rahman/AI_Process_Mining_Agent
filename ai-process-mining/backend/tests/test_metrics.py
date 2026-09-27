import pytest
from conftest import make_events

from app.services.config import AnalysisConfig
from app.services.engine import run_engine


@pytest.fixture
def result(simple_log):
    return run_engine(make_events(simple_log))


def test_case_duration(result):
    o = result.results["overview"]
    assert o["total_cases"] == 10
    # 6 cases x 4h, 2 rework x 5h, S1 3h, U1 4h -> mean = (24+10+3+4)/10 = 4.1
    assert o["avg_case_duration_hours"] == pytest.approx(4.1)
    assert o["median_case_duration_hours"] == pytest.approx(4.0)
    assert o["completed_cases"] == 10


def test_activity_frequency(result):
    acts = {a["activity"]: a for a in result.results["activities"]}
    assert acts["A"]["frequency"] == 10
    assert acts["B"]["frequency"] == 6 + 4 + 1   # rework cases execute B twice
    assert acts["B"]["repeat_executions"] == 2
    assert acts["X"]["frequency"] == 1


def test_waiting_time(result):
    acts = {a["activity"]: a for a in result.results["activities"]}
    # Standard cases wait 2h before C; rework/U1 wait 1h; S1 waits 2h
    assert acts["C"]["median_duration_hours"] == pytest.approx(2.0)
    assert acts["A"]["median_duration_hours"] is None  # first event has no waiting time


def test_variants(result):
    v = result.results["variants"]
    assert v["summary"]["unique_variants"] == 4
    assert v["items"][0]["trace"] == ["A", "B", "C", "D"]
    assert v["items"][0]["percentage_of_cases"] == 60.0


def test_bottleneck_scoring_is_transparent(result):
    b = result.results["bottlenecks"]
    assert "formula" in b["methodology"] and "caveat" in b["methodology"]
    assert b["methodology"]["weights_used"]["processing"] == 0.0  # no start timestamps
    scored = [a for a in b["activities"] if a["score"] is not None]
    assert all(0 <= a["score"] <= 1 for a in scored)
    assert scored == sorted(scored, key=lambda a: -a["score"])
    assert all(set(a["components"]) == {"median_wait", "p90_wait", "processing", "case_coverage", "wait_share"}
               for a in scored)


def test_bottleneck_weights_configurable(simple_log):
    ev = make_events(simple_log)
    cfg = AnalysisConfig(min_activity_support=1)
    cfg.bottleneck_weights.median_wait = 1.0
    for k in ("p90_wait", "case_coverage", "wait_share"):
        setattr(cfg.bottleneck_weights, k, 0.0)
    b = run_engine(ev, cfg).results["bottlenecks"]["activities"]
    top = b[0]
    assert top["median_waiting_time_hours"] == max(a["median_waiting_time_hours"] or 0 for a in b)
