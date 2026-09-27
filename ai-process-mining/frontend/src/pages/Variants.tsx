import { useApp } from "../components/AppContext";
import { ErrorState, Loading, Note, PageHeader } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import { fmtHours, fmtInt, fmtPct } from "../services/format";

export function Variants() {
  const { datasetId, drill } = useApp();
  const v = useAsync(() => api.variants(datasetId!), [datasetId]);
  if (v.error) return <ErrorState message={v.error} onRetry={v.reload} />;
  if (!v.data) return <Loading />;
  const { summary, items } = v.data;
  const dominant = new Set(items[0]?.trace ?? []);
  return (
    <>
      <PageHeader title="Variants"
        lede={<>{fmtInt(summary.unique_variants)} distinct activity sequences. {summary.coverage_statement} {summary.variants_for_80pct_coverage} variants are enough to cover 80%.</>} />
      <section className="panel">
        <div className="table-wrap">
          <table className="variants">
            <thead><tr><th>Variant</th><th className="num">Cases</th><th className="num">%</th>
              <th className="num">Average duration</th><th>Trace</th></tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.variant_id} className="clickable"
                  onClick={() => drill({ kind: "variant", variantId: r.variant_id, trace: r.trace_text })}>
                  <td><button className="link">{r.variant_id}</button></td>
                  <td className="num">{fmtInt(r.case_count)}</td>
                  <td className="num"><span className="share"><i style={{ width: `${Math.min(100, r.percentage_of_cases)}%` }} />{fmtPct(r.percentage_of_cases)}</span></td>
                  <td className="num">{fmtHours(r.avg_duration_hours)}</td>
                  <td>
                    <span className="chips">
                      {r.trace.map((s, i) => <span key={i} className={dominant.has(s) ? "chip" : "chip chip-off"}>{s}</span>)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Note>{summary.definition} Activities with a dashed outline do not appear in the most common variant.</Note>
      </section>
    </>
  );
}
