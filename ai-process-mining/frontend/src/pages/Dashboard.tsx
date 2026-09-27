import { useApp } from "../components/AppContext";
import { UploadPanel } from "../components/UploadPanel";
import { ValidationPanel } from "../components/ValidationPanel";
import { ErrorState, Kpi, Loading, Note, PageHeader, Trace } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { navigate } from "../hooks/useHashRoute";
import { api } from "../services/api";
import { fmtDate, fmtHours, fmtInt, fmtPct } from "../services/format";

export function Dashboard() {
  const { datasetId, setDatasetId, refreshDatasets } = useApp();
  if (!datasetId) {
    return (
      <>
        <PageHeader title="Load an event log"
          lede="Upload a CSV of timestamped events, or try the synthetic Order-to-Cash sample. Each case is rebuilt from its events; the other pages show the process map, where cases wait, and which cases take a different route." />
        <UploadPanel onDone={(d) => { refreshDatasets(); setDatasetId(d.id); }} />
      </>
    );
  }
  return <DatasetDashboard datasetId={datasetId} />;
}

function DatasetDashboard({ datasetId }: { datasetId: string }) {
  const ov = useAsync(() => api.overview(datasetId), [datasetId]);
  const val = useAsync(() => api.validation(datasetId), [datasetId]);
  if (ov.error) return <ErrorState message={ov.error} onRetry={ov.reload} />;
  if (ov.loading || !ov.data) return <Loading label="Computing process metrics…" />;
  const o = ov.data;
  return (
    <>
      <PageHeader title="Dashboard"
        lede={<>{fmtInt(o.total_events)} events from {fmtDate(o.first_event)} to {fmtDate(o.last_event)}. Computed in {(o.engine_processing_ms / 1000).toFixed(1)} s.</>} />
      <div className="kpis">
        <Kpi value={fmtInt(o.total_cases)} label="Total cases"
          hint={`${fmtInt(o.completed_cases)} completed, ${fmtInt(o.incomplete_cases)} incomplete`} />
        <Kpi value={fmtHours(o.avg_case_duration_hours)} label="Average duration" />
        <Kpi value={fmtHours(o.median_case_duration_hours)} label="Median duration" />
        <Kpi value={fmtHours(o.p95_case_duration_hours)} label="P95 duration" hint="95% of cases finish within this time" />
        <Kpi value={o.unique_activities} label="Unique activities" />
        <Kpi value={fmtInt(o.unique_variants)} label="Unique variants" />
        <Kpi value={fmtPct(o.deviation_rate_pct)} label="Deviation rate" hint="Cases with at least one deviation" />
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Dominant path</h2>
          <button className="btn" onClick={() => navigate("explorer")}>Open process map</button>
        </div>
        <p>{fmtPct(o.conformance_rate_pct)} of cases follow this sequence exactly. Top 10 variants cover {fmtPct(o.top10_variant_coverage_pct)} of cases.</p>
        <Trace steps={o.dominant_path} />
        <Note>
          The dominant path is the most frequent sequence among completed cases. It is a reference for comparison,
          not an approved process model. Cases count as complete when they end at: {o.completion_activities.join(", ")}.
          {!o.processing_time_available && " No start timestamps were provided, so waiting time is measured between consecutive events."}
        </Note>
      </section>

      {val.data?.report && <ValidationPanel datasetId={datasetId} report={val.data.report} />}
    </>
  );
}
