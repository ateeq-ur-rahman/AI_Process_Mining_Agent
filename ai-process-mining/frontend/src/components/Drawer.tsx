import { useEffect, useState } from "react";
import { api } from "../services/api";
import { fmtDate, fmtHours, humanize } from "../services/format";
import type { CaseDetail, EventRow } from "../types/api";
import { useApp, type DrillTarget } from "./AppContext";
import { ErrorState, Loading, Trace } from "./ui";

export function Drawer({ target, onClose }: { target: DrillTarget | null; onClose: () => void }) {
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  if (!target) return null;
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <button className="drawer-close" onClick={onClose} aria-label="Close">×</button>
        {target.kind === "case" && <CasePanel caseId={target.caseId} />}
        {target.kind === "events" && <EventsPanel target={target} />}
        {target.kind === "variant" && <VariantPanel variantId={target.variantId} trace={target.trace} />}
      </aside>
    </div>
  );
}

function CasePanel({ caseId }: { caseId: string }) {
  const { datasetId } = useApp();
  const [data, setData] = useState<CaseDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setData(null); setErr(null);
    if (datasetId) api.caseDetail(datasetId, caseId).then(setData, (e: Error) => setErr(e.message));
  }, [datasetId, caseId]);
  if (err) return <ErrorState message={err} />;
  if (!data) return <Loading />;
  const devActs = new Set(data.deviations.map((d) => d.activity));
  return (
    <>
      <h2>Case {data.case_id}</h2>
      <p className="muted">Variant {data.variant_id}, {fmtHours(data.duration_hours)} end to end</p>
      <Trace steps={data.trace} highlight={devActs} />
      <h3>Deviations ({data.deviations.length})</h3>
      {data.deviations.length === 0 ? <p className="muted">This case follows the dominant path.</p> : (
        <ul className="plain">
          {data.deviations.map((d, i) => <li key={i}><strong>{humanize(d.type)}</strong> — {d.description}</li>)}
        </ul>
      )}
      <h3>Events</h3>
      <EventTable rows={data.events} showCase={false} />
    </>
  );
}

function EventsPanel({ target }: { target: Extract<DrillTarget, { kind: "events" }> }) {
  const { datasetId, drill } = useApp();
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setRows(null); setErr(null);
    if (!datasetId) return;
    api.events(datasetId, { activity: target.activity, source: target.source, target: target.target,
      resource: target.resource }).then((r) => { setRows(r.items); setTotal(r.total); }, (e: Error) => setErr(e.message));
  }, [datasetId, target]);
  if (err) return <ErrorState message={err} />;
  if (!rows) return <Loading />;
  return (
    <>
      <h2>{target.title}</h2>
      <p className="muted">{total.toLocaleString()} events. Showing the 100 longest waits. Select a case to inspect it.</p>
      <EventTable rows={rows} showCase onCase={(c) => drill({ kind: "case", caseId: c })} />
    </>
  );
}

function VariantPanel({ variantId, trace }: { variantId: string; trace: string }) {
  const { datasetId, drill } = useApp();
  const [rows, setRows] = useState<{ case_id: string; duration_hours: number; start: string; n_events: number }[] | null>(null);
  const [total, setTotal] = useState(0);
  useEffect(() => {
    if (datasetId) api.variantCases(datasetId, variantId).then((r) => { setRows(r.items); setTotal(r.total); });
  }, [datasetId, variantId]);
  return (
    <>
      <h2>Variant {variantId}</h2>
      <Trace steps={trace.split(" → ")} />
      <p className="muted">{total.toLocaleString()} cases. Longest first.</p>
      {!rows ? <Loading /> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Case</th><th>Started</th><th className="num">Events</th><th className="num">Duration</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.case_id}>
              <td><button className="link" onClick={() => drill({ kind: "case", caseId: r.case_id })}>{r.case_id}</button></td>
              <td>{fmtDate(r.start)}</td><td className="num">{r.n_events}</td><td className="num">{fmtHours(r.duration_hours)}</td>
            </tr>))}
          </tbody></table></div>
      )}
    </>
  );
}

function EventTable({ rows, showCase, onCase }: { rows: EventRow[]; showCase: boolean; onCase?: (c: string) => void }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {showCase && <th>Case</th>}
            <th>Activity</th><th>Timestamp</th><th className="num">Wait</th><th>Resource</th><th className="num">Row</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.case_id}-${r.source_row}-${i}`}>
              {showCase && <td><button className="link" onClick={() => onCase?.(r.case_id)}>{r.case_id}</button></td>}
              <td title={r.original_activity !== r.activity ? `Original: "${r.original_activity}"` : undefined}>
                {r.activity}{r.original_activity !== r.activity && <span className="muted"> *</span>}
              </td>
              <td>{fmtDate(r.timestamp)}</td>
              <td className="num">{fmtHours(r.wait_h)}</td>
              <td>{r.resource ?? "—"}</td>
              <td className="num muted">{r.source_row}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
