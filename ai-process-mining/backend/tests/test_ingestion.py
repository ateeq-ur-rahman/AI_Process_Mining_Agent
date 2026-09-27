import pytest

from app.core.errors import UploadRejected
from app.repositories.datasets import escape_formula, to_csv_bytes
from app.services.dataset_service import check_upload, safe_display_name
from app.services.ingestion.csv_validator import parse_and_validate

VALID = b"""case_id,activity,timestamp,resource,amount
O1,Order Created,2026-09-01 09:00:00,Alice,1200
O1,Order Approved,2026-09-01 10:15:00,Bob,1200
O2,Order Created,2026-09-01T11:00:00Z,Alice,50
O2,Order Approved,2026-09-01T13:00:00+02:00,Bob,50
"""


def test_valid_csv():
    r = parse_and_validate(VALID)
    assert r.report["total_rows"] == 4
    assert r.report["valid_rows"] == 4
    assert r.report["invalid_rows"] == 0
    assert r.report["total_cases"] == 2
    assert set(r.events.columns) >= {"case_id", "original_activity", "timestamp", "resource", "amount"}
    # Offsets are converted to UTC: 13:00+02:00 == 11:00Z
    o2 = r.events[r.events["case_id"] == "O2"].sort_values("timestamp")
    assert str(o2.iloc[1]["timestamp"]) == "2026-09-01 11:00:00+00:00"


def test_missing_required_columns():
    with pytest.raises(UploadRejected) as e:
        parse_and_validate(b"case_id,activity\nA,B\n")
    assert e.value.message == "CSV is missing required column: timestamp. Found: case_id, activity."


def test_header_aliases():
    r = parse_and_validate(b"Case ID,Activity Name,Event Time\n1,A,2026-01-01 10:00\n1,B,2026-01-01 11:00\n")
    assert r.report["valid_rows"] == 2


def test_invalid_timestamps_are_reported_not_dropped_silently():
    data = VALID + b"O3,Order Created,not a date,Alice,1\nO3,Order Created,2099-01-01 00:00:00,Alice,1\n"
    r = parse_and_validate(data)
    assert r.report["invalid_timestamps"] == 1
    assert r.report["impossible_timestamps"] == 1
    assert r.report["invalid_rows"] == 2
    by_issue = {x["issue"]: x for x in r.invalid_rows}
    assert set(by_issue) == {"invalid_timestamp", "impossible_timestamp"}
    assert by_issue["invalid_timestamp"]["source_row"] == 6  # line number in the file
    assert by_issue["impossible_timestamp"]["detail"] == "Timestamp '2099-01-01 00:00:00' is in the future."
    # Raw values are the file's columns, not internal parsing columns.
    assert set(by_issue["invalid_timestamp"]["raw"]) == {"case_id", "activity", "timestamp", "resource", "amount"}


def test_duplicates_missing_ids_and_malformed():
    data = VALID + (b"O1,Order Created,2026-09-01 09:00:00,Alice,1200\n"
                    b",Order Created,2026-09-01 09:00:00,Alice,1\n"
                    b"O9,,2026-09-01 09:00:00,Alice,1\n"
                    b"O9,Too,few\n")
    r = parse_and_validate(data)
    rep = r.report
    assert rep["duplicate_rows"] == 1
    assert rep["missing_case_ids"] == 1
    assert rep["missing_activities"] == 1
    assert rep["malformed_rows"] == 1
    assert rep["valid_rows"] + rep["invalid_rows"] == rep["total_rows"]


def test_single_event_case_warning():
    r = parse_and_validate(VALID + b"O5,Order Created,2026-09-02 09:00:00,Alice,1\n")
    assert r.report["single_event_cases"] == 1
    assert any("only one event" in w for w in r.report["warnings"])


def test_binary_and_empty_rejected():
    with pytest.raises(UploadRejected):
        parse_and_validate(b"\x00\x01\x02binary")
    with pytest.raises(UploadRejected):
        parse_and_validate(b"   ")


def test_upload_checks_and_path_traversal():
    with pytest.raises(UploadRejected):
        check_upload("evil.exe", "application/octet-stream", 10)
    with pytest.raises(UploadRejected):
        check_upload("big.csv", "text/csv", 10 ** 12)
    assert safe_display_name("../../etc/passwd.csv") == "passwd.csv"
    assert "/" not in safe_display_name("..\\..\\x.csv")


def test_formula_injection_escaped_on_export():
    assert escape_formula("=HYPERLINK(\"x\")").startswith("'=")
    assert escape_formula("+1") == "'+1"
    assert escape_formula("normal") == "normal"
    out = to_csv_bytes([{"a": "@SUM(A1)"}], ["a"]).decode()
    assert "'@SUM(A1)" in out
