from pathlib import Path

import pytest

SAMPLE = b"""case_id,activity,timestamp,resource,amount
O1,Order Created,2026-09-01 09:00:00,Alice,=HYPERLINK("x")
O1,Order Approved,2026-09-01 10:15:00,Bob,1200
O1,Shipped,2026-09-02 10:15:00,John,1200
O2,Order Created,2026-09-01 11:00:00,Alice,50
O2,Order Approved,2026-09-01 13:00:00,Bob,50
O2,Shipped,2026-09-03 13:00:00,John,50
O3,Order Created,2026-09-01 11:00:00,Alice,50
O3,Shipped,2026-09-01 18:00:00,John,50
O3,Shipped,2026-09-01 18:00:00,John,50
O4,Order Created,bad-date,Alice,50
"""


def upload(client, content=SAMPLE, name="log.csv"):
    return client.post("/api/datasets/upload", files={"file": (name, content, "text/csv")})


def test_end_to_end_flow(client):
    r = upload(client)
    assert r.status_code == 201, r.text
    ds = r.json()
    assert ds["status"] == "ready"
    did = ds["id"]

    v = client.get(f"/api/datasets/{did}/validation").json()["report"]
    assert v["duplicate_rows"] == 1 and v["invalid_timestamps"] == 1

    inv = client.get(f"/api/datasets/{did}/validation/invalid-rows").json()
    assert inv["total"] == 2
    csv_text = client.get(f"/api/datasets/{did}/validation/invalid-rows.csv").text
    assert "duplicate" in csv_text

    o = client.get(f"/api/process/{did}/overview").json()
    assert o["total_cases"] == 3
    g = client.get(f"/api/process/{did}/graph").json()
    assert {n["id"] for n in g["nodes"]} == {"Order Created", "Order Approved", "Shipped"}
    g2 = client.get(f"/api/process/{did}/graph", params={"min_case_pct": 50}).json()
    assert all(e["case_pct"] >= 50 for e in g2["edges"])

    assert client.get(f"/api/process/{did}/variants").json()["summary"]["unique_variants"] == 2
    b = client.get(f"/api/process/{did}/bottlenecks").json()
    assert "methodology" in b
    b2 = client.get(f"/api/process/{did}/bottlenecks", params={"w_median_wait": 1, "w_p90_wait": 0}).json()
    assert b2["methodology"]["weights_used"]["median_wait"] == 1
    d = client.get(f"/api/process/{did}/deviations", params={"type": "skipped_activity"}).json()
    assert d["total"] == 1 and d["items"][0]["case_id"] == "O3"
    assert client.get(f"/api/process/{did}/resources").json()["available"] is True

    case = client.get(f"/api/datasets/{did}/cases/O1").json()
    assert case["trace"] == ["Order Created", "Order Approved", "Shipped"]
    evs = client.get(f"/api/datasets/{did}/events", params={"source": "Order Approved", "target": "Shipped"}).json()
    assert evs["total"] == 2

    rep = client.post(f"/api/research/{did}/analyze", json={}).json()
    assert rep["report"]["key_findings"] and rep["meta"]["mode"] == "deterministic"
    assert client.get(f"/api/research/{did}/latest").status_code == 200
    assert client.get(f"/api/research/{did}/report.md").text.startswith("# Process analysis report")

    q = client.post(f"/api/query/{did}", json={"question": "How many cases are there?"}).json()
    assert "3 cases" in q["answer"] and q["evidence"]
    runs = client.get(f"/api/research/{did}/runs").json()
    assert {r["kind"] for r in runs} == {"report", "query"}


def test_upload_rejections(client):
    assert upload(client, b"a,b\n1,2\n").status_code == 422
    assert upload(client, SAMPLE, name="x.exe").status_code == 422
    r = client.get("/api/process/doesnotexist/overview")
    assert r.status_code == 404 and "request_id" in r.json()


def test_request_id_header(client):
    r = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


def test_sample_dataset_endpoint(client, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "data" / "sample_order_to_cash.csv"
    if not path.exists():
        pytest.skip("sample CSV not present")
    monkeypatch.setenv("SAMPLE_DATA_PATH", str(path))
    r = client.post("/api/datasets/sample")
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    o = client.get(f"/api/process/{did}/overview").json()
    assert o["total_cases"] == 10_000
    assert o["unique_activities"] >= 15
