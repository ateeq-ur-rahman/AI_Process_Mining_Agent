import { useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import { fmtInt, humanize } from "../services/format";
import type { ValidationReport } from "../types/api";
import { Loading } from "./ui";

const ISSUES: [keyof ValidationReport, string, string][] = [
  ["duplicate_rows", "duplicate", "Duplicate rows"],
  ["missing_case_ids", "missing_case_id", "Missing case ID"],
  ["missing_activities", "missing_activity", "Missing activity"],
  ["invalid_timestamps", "invalid_timestamp", "Unreadable timestamp"],
  ["impossible_timestamps", "impossible_timestamp", "Impossible timestamp"],
  ["malformed_rows", "malformed_row", "Malformed row"],
];

export function ValidationPanel({ datasetId, report }: { datasetId: string; report: ValidationReport }) {
  const [issue, setIssue] = useState<string | undefined>();
  const [open, setOpen] = useState(false);
  const rows = useAsync(() => (open ? api.invalidRows(datasetId, issue) : Promise.resolve(null)), [datasetId, issue, open]);
  const validPct = report.total_rows ? (100 * report.valid_rows) / report.total_rows : 0;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Data quality</h2>
        <a className="btn" href={api.invalidRowsCsvUrl(datasetId)} download>Download excluded rows (CSV)</a>
      </div>
      <p className="dq-line">
        <strong>{fmtInt(report.valid_rows)}</strong> of {fmtInt(report.total_rows)} rows used ({validPct.toFixed(2)}%).{" "}
        {report.invalid_rows > 0 ? <>{fmtInt(report.invalid_rows)} excluded, each with a recorded reason.</> : "No rows excluded."}
      </p>
      <div className="dq-bar" aria-hidden="true"><span style={{ width: `${validPct}%` }} /></div>
      <div className="dq-grid">
        {ISSUES.map(([key, code, label]) => (
          <button key={code} className={`dq-item${issue === code ? " is-active" : ""}`}
            disabled={!report[key]} onClick={() => { setIssue(issue === code ? undefined : code); setOpen(true); }}>
            <span className="dq-num">{fmtInt(report[key] as number)}</span>
            <span>{label}</span>
          </button>
        ))}
        <div className="dq-item is-static">
          <span className="dq-num">{fmtInt(report.single_event_cases)}</span><span>Single-event cases (kept)</span>
        </div>
      </div>
      {report.activity_name_merges && Object.keys(report.activity_name_merges).length > 0 && (
        <p className="note pre">Activity spellings merged: {Object.entries(report.activity_name_merges).map(([k, v]) =>
          `${v.map((x) => JSON.stringify(x)).join(", ")} as "${k}"`).join("; ")}. Original names are preserved.</p>
      )}
      {report.warnings.map((w) => <p key={w} className="note">{w}</p>)}
      <p className="note">{report.counting_rule}. Timestamps without an offset were read as {report.timezone_assumed_for_naive_timestamps}.</p>
      {!open ? (
        report.invalid_rows > 0 && <button className="btn" onClick={() => setOpen(true)}>Show excluded rows</button>
      ) : rows.loading ? <Loading /> : rows.data && (
        <div className="table-wrap tall">
          <table>
            <thead><tr><th className="num">Row</th><th>Issue</th><th>Detail</th><th>Raw values</th></tr></thead>
            <tbody>
              {rows.data.items.map((r) => (
                <tr key={`${r.source_row}-${r.issue}`}>
                  <td className="num">{r.source_row}</td><td>{humanize(r.issue)}</td><td>{r.detail}</td>
                  <td className="raw">{r.raw ? Object.values(r.raw).flat().map(String).join(", ") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.data.total > rows.data.items.length && (
            <p className="muted">Showing {rows.data.items.length} of {fmtInt(rows.data.total)}. Download the CSV for all rows.</p>
          )}
        </div>
      )}
    </section>
  );
}
