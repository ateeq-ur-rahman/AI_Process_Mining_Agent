import { useState } from "react";
import { useApp } from "../components/AppContext";
import { ErrorState, Indicator, Loading, Note, PageHeader } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import { fmtHours, fmtInt, fmtPct } from "../services/format";

const WEIGHT_LABELS: Record<string, string> = {
  median_wait: "Median wait", p90_wait: "P90 wait", processing: "Processing time",
  case_coverage: "Share of cases affected", wait_share: "Share of total waiting time",
};

export function Bottlenecks() {
  const { datasetId, drill } = useApp();
  const [weights, setWeights] = useState<Record<string, number> | undefined>();
  const [draft, setDraft] = useState<Record<string, number> | null>(null);
  const b = useAsync(() => api.bottlenecks(datasetId!, weights), [datasetId, JSON.stringify(weights)]);
  const res = useAsync(() => api.resources(datasetId!), [datasetId]);
  if (b.error) return <ErrorState message={b.error} onRetry={b.reload} />;
  if (!b.data) return <Loading label="Scoring activities…" />;
  const m = b.data.methodology;
  const current = draft ?? m.weights_used;

  return (
    <>
      <PageHeader title="Bottlenecks"
        lede="Activities ranked by where cases wait. The score combines several measures; adjust the weights to see how the ranking changes." />
      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Activity</th><th className="num">Frequency</th><th className="num">Median wait</th>
                <th className="num">P95 wait</th><th className="num">Affected cases</th>
                <th className="num">Share of waiting</th><th className="num">Score</th><th>Indicator</th>
              </tr>
            </thead>
            <tbody>
              {b.data.activities.map((a) => (
                <tr key={a.activity} className="clickable"
                  onClick={() => drill({ kind: "events", title: `Waiting before ${a.activity}`, activity: a.activity })}>
                  <td><button className="link">{a.activity}</button></td>
                  <td className="num">{fmtInt(a.frequency)}</td>
                  <td className="num">{fmtHours(a.median_waiting_time_hours)}</td>
                  <td className="num">{fmtHours(a.p95_waiting_time_hours)}</td>
                  <td className="num">{fmtPct(a.affected_cases_pct)}</td>
                  <td className="num">{fmtPct(a.wait_share_pct)}</td>
                  <td className="num">
                    {a.score == null ? "—" : (
                      <span className="score"><i style={{ width: `${a.score * 100}%` }} />{a.score.toFixed(2)}</span>
                    )}
                  </td>
                  <td title={a.not_scored_reason ?? undefined}><Indicator level={a.indicator} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="two-col">
        <section className="panel">
          <h2>How the score works</h2>
          <p><code>{m.formula}</code></p>
          <div className="weights">
            {Object.keys(WEIGHT_LABELS).map((k) => (
              <label key={k} className={k === "processing" && !m.processing_time_available ? "is-disabled" : undefined}>
                <span>{WEIGHT_LABELS[k]}</span>
                <input type="range" min={0} max={1} step={0.05} value={current[k] ?? 0}
                  disabled={k === "processing" && !m.processing_time_available}
                  onChange={(e) => setDraft({ ...current, [k]: Number(e.target.value) })} />
                <output>{(current[k] ?? 0).toFixed(2)}</output>
              </label>
            ))}
          </div>
          <div className="row-actions">
            <button className="btn btn-primary" disabled={!draft} onClick={() => { setWeights(draft ?? undefined); setDraft(null); }}>
              Recalculate
            </button>
            <button className="btn" onClick={() => { setWeights(undefined); setDraft(null); }}>Reset to defaults</button>
          </div>
          <Note>
            High ≥ {m.thresholds.HIGH}, Medium ≥ {m.thresholds.MEDIUM}. {m.caveat}
            {!m.processing_time_available && " Processing time is unavailable without start timestamps, so its weight is set to 0."}
          </Note>
        </section>
        <section className="panel">
          <h2>Slowest transitions</h2>
          <ul className="plain">
            {b.data.slow_transitions.map((t) => (
              <li key={`${t.source}-${t.target}`}>
                <button className="link" onClick={() => drill({ kind: "events", title: `${t.source} → ${t.target}`,
                  source: t.source, target: t.target })}>{t.source} → {t.target}</button>
                <span className="muted"> median {fmtHours(t.median_transition_hours)}, P90 {fmtHours(t.p90_transition_hours)}, {fmtInt(t.frequency)} times</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {res.data?.available && (
        <section className="panel">
          <h2>Resources</h2>
          <Note>{res.data.disclaimer}</Note>
          <div className="table-wrap tall">
            <table>
              <thead><tr><th>Resource</th><th>Department</th><th className="num">Cases</th><th className="num">Events</th>
                <th>Main activities</th><th className="num">Median wait before</th><th className="num">Avg case duration</th>
                <th className="num">Rework rate</th></tr></thead>
              <tbody>
                {res.data.resources.map((r) => (
                  <tr key={r.resource} className="clickable" onClick={() =>
                    drill({ kind: "events", title: `Events by ${r.resource}`, resource: r.resource })}>
                    <td><button className="link">{r.resource}</button></td><td>{r.department ?? "—"}</td>
                    <td className="num">{fmtInt(r.cases_handled)}</td><td className="num">{fmtInt(r.events)}</td>
                    <td>{r.top_activities.join(", ")}</td>
                    <td className="num">{fmtHours(r.median_waiting_time_hours)}</td>
                    <td className="num">{fmtHours(r.avg_case_duration_hours)}</td>
                    <td className="num">{fmtPct(r.rework_rate_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
