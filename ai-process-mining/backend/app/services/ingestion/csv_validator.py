"""Read an uploaded CSV and sort its rows into usable events and rejected rows.

Nothing is dropped silently: every rejected row is kept with its line number, the
reason, and its raw values, so the user can see exactly what was left out.

A row with several problems is reported once, under the first check it fails:
malformed -> missing_case_id -> missing_activity -> invalid_timestamp
-> impossible_timestamp -> duplicate. That keeps valid + invalid == total.

`source_row` is the line number in the file (header is line 1), i.e. what you'd
see in a text editor.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.core.errors import UploadRejected

REQUIRED_COLUMNS = ("case_id", "activity", "timestamp")
OPTIONAL_COLUMNS = (
    "start_timestamp", "resource", "department", "status", "amount",
    "customer_id", "location", "priority",
)

# Header spellings seen in real exports, including XES names (concept:name etc.)
# after canonical_header() has turned punctuation into underscores.
HEADER_ALIASES = {
    "caseid": "case_id", "case": "case_id", "case_concept_name": "case_id", "order_id": "case_id",
    "activity_name": "activity", "event": "activity", "concept_name": "activity", "event_name": "activity",
    "time_timestamp": "timestamp", "event_time": "timestamp", "time": "timestamp", "datetime": "timestamp",
    "complete_timestamp": "timestamp", "end_timestamp": "timestamp",
    "start_time": "start_timestamp", "start": "start_timestamp",
    "org_resource": "resource", "user": "resource",
}

ISSUE_ORDER = (
    "malformed_row", "missing_case_id", "missing_activity",
    "invalid_timestamp", "impossible_timestamp", "duplicate",
)

_TZ_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)
MIN_PLAUSIBLE = pd.Timestamp("1970-01-01", tz="UTC")


@dataclass
class IngestionResult:
    events: pd.DataFrame                      # valid rows, canonical columns + source_row + extra
    invalid_rows: list[dict] = field(default_factory=list)
    report: dict = field(default_factory=dict)
    column_mapping: dict = field(default_factory=dict)


def canonical_header(name: str) -> str:
    key = re.sub(r"[^0-9a-z]+", "_", name.strip().lower()).strip("_")
    return HEADER_ALIASES.get(key, key)


def decode_upload(content: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if b"\x00" in content[:8192]:
        raise UploadRejected("The file looks binary, not a CSV text file.")
    try:
        return content.decode("utf-8-sig"), warnings
    except UnicodeDecodeError:
        warnings.append("File is not valid UTF-8; decoded as Latin-1. Check special characters.")
        return content.decode("latin-1"), warnings


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _parse_timestamps(values: pd.Series, default_tz: str) -> pd.Series:
    """Parse to UTC.

    Everything is stored in UTC so durations are plain subtraction, even across DST
    changes or when one export mixes offsets. Values without an offset are read in
    `default_tz` (UTC unless configured), and the validation report says so.
    """
    text = values.fillna("").astype(str).str.strip()
    out = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns, UTC]")
    has_tz = text.str.contains(_TZ_SUFFIX) & text.ne("")
    naive = ~has_tz & text.ne("")
    if has_tz.any():
        out.loc[has_tz] = pd.to_datetime(text[has_tz], errors="coerce", utc=True, format="mixed")
    if naive.any():
        parsed = pd.to_datetime(text[naive], errors="coerce", format="mixed")
        if getattr(parsed.dt, "tz", None) is None:
            parsed = parsed.dt.tz_localize(default_tz, ambiguous="NaT", nonexistent="NaT")
        out.loc[naive] = parsed.dt.tz_convert("UTC")
    return out


def parse_and_validate(content: bytes, *, default_tz: str = "UTC", max_rows: int = 1_000_000,
                       now: datetime | None = None) -> IngestionResult:
    text, warnings = decode_upload(content)
    if not text.strip():
        raise UploadRejected("The file is empty.")

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=_sniff_delimiter(text[:4096]))
    try:
        raw_header = next(reader)
    except StopIteration as exc:
        raise UploadRejected("The file has no header row.") from exc

    header = [canonical_header(h) for h in raw_header]
    mapping = {orig: canon for orig, canon in zip(raw_header, header) if orig.strip()}
    if len(set(header)) != len(header):
        dupes = sorted({h for h in header if header.count(h) > 1})
        raise UploadRejected(f"More than one column maps to {', '.join(dupes)} "
                             "(e.g. 'Case ID' and 'case_id'). Rename or remove one of them.")
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        noun = "column" if len(missing) == 1 else "columns"
        raise UploadRejected(
            f"CSV is missing required {noun}: {', '.join(missing)}. "
            f"Found: {', '.join(h for h in raw_header if h.strip()) or 'no columns'}.",
            details={"columns_found": raw_header, "missing": missing},
        )

    invalid: list[dict] = []
    good_rows: list[list[str]] = []
    source_rows: list[int] = []
    blank_lines = 0
    total = 0
    for row in reader:
        line = reader.line_num
        if not row or all(not c.strip() for c in row):
            blank_lines += 1
            continue
        total += 1
        if total > max_rows:
            raise UploadRejected(f"File exceeds the row limit of {max_rows:,} rows.")
        if len(row) != len(header):
            invalid.append({"source_row": line, "issue": "malformed_row",
                            "detail": f"Expected {len(header)} fields, found {len(row)}.",
                            "raw": {"fields": row[:50]}})
            continue
        good_rows.append(row)
        source_rows.append(line)

    df = pd.DataFrame(good_rows, columns=header, dtype="object")
    df.insert(0, "source_row", source_rows)
    for col in header:
        df[col] = df[col].astype("string").str.strip()

    # Each check removes the rows it rejects, so later checks never see them and a row
    # is only ever reported once.
    def reject(mask: pd.Series, issue: str, detail_fn) -> None:
        nonlocal df
        if not mask.any():
            return
        bad = df[mask]
        for rec in bad.to_dict("records"):
            invalid.append({"source_row": int(rec["source_row"]), "issue": issue, "detail": detail_fn(rec),
                            "raw": {k: (None if pd.isna(v) else str(v)) for k, v in rec.items()
                                    if k != "source_row" and not k.startswith("_")}})
        df = df[~mask]

    reject(df["case_id"].isna() | df["case_id"].eq(""), "missing_case_id", lambda r: "case_id is empty.")
    reject(df["activity"].isna() | df["activity"].eq(""), "missing_activity", lambda r: "activity is empty.")

    ts = _parse_timestamps(df["timestamp"], default_tz)
    df = df.assign(_ts=ts)
    reject(df["_ts"].isna(), "invalid_timestamp", lambda r: f"Unable to parse timestamp '{r['timestamp']}'.")

    now_utc = pd.Timestamp(now or datetime.now(timezone.utc))
    now_utc = now_utc.tz_localize("UTC") if now_utc.tzinfo is None else now_utc.tz_convert("UTC")
    upper = now_utc + timedelta(days=1)
    impossible = (df["_ts"] < MIN_PLAUSIBLE) | (df["_ts"] > upper)
    reject(impossible, "impossible_timestamp",
           lambda r: (f"Timestamp '{r['timestamp']}' is before 1970." if r["_ts"] < MIN_PLAUSIBLE
                      else f"Timestamp '{r['timestamp']}' is in the future."))

    start_invalid = 0
    if "start_timestamp" in df.columns:
        st = _parse_timestamps(df["start_timestamp"], default_tz)
        df = df.assign(_start=st)
        reject(df["_start"].notna() & (df["_start"] > df["_ts"]), "impossible_timestamp",
               lambda r: "start_timestamp is after timestamp (completion).")
        unparsable = df["start_timestamp"].notna() & df["start_timestamp"].ne("") & df["_start"].isna()
        start_invalid = int(unparsable.sum())
        if start_invalid:
            warnings.append(f"{start_invalid} start_timestamp values could not be parsed; "
                            "processing time is unavailable for those events.")

    dup_mask = df.duplicated(subset=header, keep="first")
    reject(dup_mask, "duplicate", lambda r: "Exact duplicate of an earlier row (all columns identical).")

    events = pd.DataFrame({
        "source_row": df["source_row"].astype(int),
        "case_id": df["case_id"].astype(str),
        "original_activity": df["activity"].astype(str),
        "timestamp": df["_ts"],
    })
    events["start_timestamp"] = df["_start"] if "_start" in df.columns else pd.NaT
    events["start_timestamp"] = pd.to_datetime(events["start_timestamp"], utc=True)
    for col in ("resource", "department", "status", "customer_id", "location", "priority"):
        events[col] = df[col].replace("", pd.NA) if col in df.columns else pd.NA
    non_numeric_amount = 0
    if "amount" in df.columns:
        amount = pd.to_numeric(df["amount"].str.replace(",", "", regex=False), errors="coerce")
        non_numeric_amount = int((amount.isna() & df["amount"].notna() & df["amount"].ne("")).sum())
        events["amount"] = amount
        if non_numeric_amount:
            warnings.append(f"{non_numeric_amount} amount values were not numeric and were left empty.")
    else:
        events["amount"] = float("nan")
    known = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
    extra_cols = [c for c in header if c not in known]
    if extra_cols:
        events["extra"] = df[extra_cols].to_dict("records")
    else:
        events["extra"] = None
    events = events.reset_index(drop=True)

    case_sizes = events.groupby("case_id").size()
    single_event_cases = int((case_sizes == 1).sum())
    if single_event_cases:
        warnings.append(f"{single_event_cases} case(s) contain only one event. They are kept, "
                        "but contribute no transitions.")
    if blank_lines:
        warnings.append(f"{blank_lines} blank line(s) were ignored.")

    counts = {k: 0 for k in ISSUE_ORDER}
    for r in invalid:
        counts[r["issue"]] += 1
    invalid.sort(key=lambda r: r["source_row"])

    report = {
        "total_rows": total,
        "valid_rows": int(len(events)),
        "invalid_rows": len(invalid),
        "duplicate_rows": counts["duplicate"],
        "missing_case_ids": counts["missing_case_id"],
        "missing_activities": counts["missing_activity"],
        "invalid_timestamps": counts["invalid_timestamp"],
        "impossible_timestamps": counts["impossible_timestamp"],
        "malformed_rows": counts["malformed_row"],
        "single_event_cases": single_event_cases,
        "total_cases": int(case_sizes.size),
        "columns_detected": raw_header,
        "optional_columns_present": [c for c in OPTIONAL_COLUMNS if c in header],
        "extra_columns": extra_cols,
        "timezone_assumed_for_naive_timestamps": default_tz,
        "counting_rule": "Each excluded row is counted once, under its first issue: " + " > ".join(ISSUE_ORDER),
        "warnings": warnings,
    }
    return IngestionResult(events=events, invalid_rows=invalid, report=report, column_mapping=mapping)
