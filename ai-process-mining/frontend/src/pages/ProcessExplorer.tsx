import { useState } from "react";
import { useApp } from "../components/AppContext";
import { ProcessGraph, type Selection } from "../components/ProcessGraph";
import { ErrorState, Loading, PageHeader } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../services/api";
import { fmtHours, fmtInt, fmtPct } from "../services/format";

const STEPS = [0, 1, 5, 10, 20];

export function ProcessExplorer() {
  const { datasetId, drill } = useApp();
  const g = useAsync(() => api.graph(datasetId!), [datasetId]);
  const [step, setStep] = useState(2);
  const [sel, setSel] = useState<Selection>(null);
  if (g.error) return <ErrorState message={g.error} onRetry={g.reload} />;
  if (g.loading || !g.data) return <Loading label="Discovering the process…" />;
  const min = STEPS[step];

  return (
    <>
      <PageHeader title="Process map"
        lede="Discovered from the log as a directly-follows graph: an arrow means one activity was immediately followed by another in at least one case." />
      <div className="toolbar">
        <label htmlFor="thr">Show transitions occurring in at least <strong>{min === 0 ? "any" : `${min}%`}</strong> of cases</label>
        <input id="thr" type="range" min={0} max={STEPS.length - 1} step={1} value={step}
          onChange={(e) => { setStep(Number(e.target.value)); setSel(null); }} list="thr-steps" />
        <datalist id="thr-steps">{STEPS.map((s, i) => <option key={s} value={i} label={`${s}%`} />)}</datalist>
        <span className="muted">{fmtInt(g.data.nodes.length)} activities, {fmtInt(g.data.edges.length)} transitions in total</span>
      </div>
      <div className="explorer">
        <ProcessGraph graph={g.data} minCasePct={min} selection={sel} onSelect={setSel} />
        <aside className="inspector" aria-live="polite">
          {!sel && (
            <>
              <h2>Inspect</h2>
              <p className="muted">Select an activity or an arrow to see its numbers and the events behind them.</p>
              <p className="note">{g.data.timing_semantics}</p>
            </>
          )}
          {sel?.kind === "node" && (
            <>
              <h2>{sel.node.activity}</h2>
              <dl className="facts">
                <dt>Executions</dt><dd>{fmtInt(sel.node.count)}</dd>
                <dt>Cases</dt><dd>{fmtInt(sel.node.cases)} ({fmtPct(sel.node.case_pct)})</dd>
                <dt>Average duration</dt><dd>{fmtHours(sel.node.avg_duration_hours)}</dd>
                <dt>Median duration</dt><dd>{fmtHours(sel.node.median_duration_hours)}</dd>
                {sel.node.start_count > 0 && <><dt>Starts a case</dt><dd>{fmtInt(sel.node.start_count)}</dd></>}
                {sel.node.end_count > 0 && <><dt>Ends a case</dt><dd>{fmtInt(sel.node.end_count)}</dd></>}
              </dl>
              <button className="btn btn-primary" onClick={() =>
                drill({ kind: "events", title: `${sel.node.activity} events`, activity: sel.node.activity })}>
                View events
              </button>
            </>
          )}
          {sel?.kind === "edge" && (
            <>
              <h2>{sel.edge.source} <span className="muted">to</span> {sel.edge.target}</h2>
              <dl className="facts">
                <dt>Frequency</dt><dd>{fmtInt(sel.edge.frequency)}</dd>
                <dt>Cases</dt><dd>{fmtInt(sel.edge.cases)} ({fmtPct(sel.edge.case_pct)})</dd>
                <dt>Average transition time</dt><dd>{fmtHours(sel.edge.avg_transition_hours)}</dd>
                <dt>Median transition time</dt><dd>{fmtHours(sel.edge.median_transition_hours)}</dd>
                <dt>P90 transition time</dt><dd>{fmtHours(sel.edge.p90_transition_hours)}</dd>
              </dl>
              <button className="btn btn-primary" onClick={() => drill({ kind: "events",
                title: `${sel.edge.source} → ${sel.edge.target}`, source: sel.edge.source, target: sel.edge.target })}>
                View transitions
              </button>
            </>
          )}
        </aside>
      </div>
    </>
  );
}
