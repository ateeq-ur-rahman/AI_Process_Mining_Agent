import { useEffect, useState } from "react";
import { useApp } from "../components/AppContext";
import { ErrorState, Loading, Note, PageHeader } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import { fmtDate, fmtInt, fmtPct, humanize } from "../services/format";

export function Deviations({ initialType }: { initialType?: string }) {
  const { datasetId, drill } = useApp();
  const [type, setType] = useState<string | undefined>(initialType);
  const [caseQuery, setCaseQuery] = useState("");
  const [caseFilter, setCaseFilter] = useState<string | undefined>();
  const [offset, setOffset] = useState(0);
  useEffect(() => { setType(initialType); setOffset(0); }, [initialType]);
  const d = useAsync(() => api.deviations(datasetId!, { type, case_id: caseFilter, offset }),
    [datasetId, type, caseFilter, offset]);
  if (d.error) return <ErrorState message={d.error} onRetry={d.reload} />;
  if (!d.data) return <Loading label="Comparing cases with the dominant path…" />;
  const { summary, conformance, items, total, limit } = d.data;

  return (
    <>
      <PageHeader title="Deviations"
        lede={<>Each case is compared with the dominant path: <em>{conformance.dominant_path_text}</em>. {fmtPct(conformance.conformance_rate_pct)} follow it exactly.</>} />
      <div className="dev-types">
        {summary.by_type.map((t) => (
          <button key={t.type} className={`dev-type${type === t.type ? " is-active" : ""}`}
            onClick={() => { setType(type === t.type ? undefined : t.type); setOffset(0); }}>
            <span className="dev-type-pct">{fmtPct(t.case_pct)}</span>
            <span className="dev-type-name">{humanize(t.type)}</span>
            <span className="muted">{fmtInt(t.cases)} cases, mostly {t.top_activities.slice(0, 2).map((a) => a.activity).join(" and ")}</span>
          </button>
        ))}
      </div>
      <Note>{conformance.method} {summary.delay_rule}</Note>

      <section className="panel">
        <div className="panel-head">
          <h2>{type ? humanize(type) : "All deviations"} <span className="muted">({fmtInt(total)})</span></h2>
          <form className="inline-form" onSubmit={(e) => { e.preventDefault(); setCaseFilter(caseQuery.trim() || undefined); setOffset(0); }}>
            <label htmlFor="caseq" className="sr-only">Filter by case ID</label>
            <input id="caseq" placeholder="Filter by case ID" value={caseQuery} onChange={(e) => setCaseQuery(e.target.value)} />
            <button className="btn" type="submit">Filter</button>
          </form>
        </div>
        {items.length === 0 ? <p className="muted">No deviations match this filter.</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Case ID</th><th>Deviation type</th><th>Activity</th><th>Description</th><th>Timestamp</th></tr></thead>
              <tbody>
                {items.map((r, i) => (
                  <tr key={`${r.case_id}-${i}`}>
                    <td><button className="link" onClick={() => drill({ kind: "case", caseId: r.case_id })}>{r.case_id}</button></td>
                    <td>{humanize(r.type)}</td><td>{r.activity}</td><td>{r.description}</td><td>{fmtDate(r.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="pager">
          <button className="btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
          <span className="muted">{fmtInt(Math.min(total, offset + 1))}–{fmtInt(Math.min(total, offset + limit))} of {fmtInt(total)}</span>
          <button className="btn" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button>
        </div>
      </section>
    </>
  );
}
