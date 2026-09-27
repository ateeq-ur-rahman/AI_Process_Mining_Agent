import { useRef, useState } from "react";
import { ApiError, api } from "../services/api";
import type { Dataset } from "../types/api";

export function UploadPanel({ onDone, compact = false }: { onDone: (d: Dataset) => void; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  async function run(label: string, fn: () => Promise<Dataset>) {
    setBusy(label); setError(null);
    try { onDone(await fn()); } catch (e) {
      const err = e as ApiError;
      setError(err.message);
    } finally { setBusy(null); }
  }
  const pick = (f?: File | null) => f && run(`Analysing ${f.name}…`, () => api.upload(f));

  return (
    <div
      className={`upload${drag ? " is-drag" : ""}${compact ? " is-compact" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
    >
      {!compact && (
        <>
          <h2>Upload an event log</h2>
          <p>
            A CSV with one row per event. Required columns: <code>case_id</code>, <code>activity</code>,{" "}
            <code>timestamp</code>. Optional: <code>resource</code>, <code>department</code>, <code>amount</code>,{" "}
            <code>start_timestamp</code> and others. Timestamps without an offset are read as UTC.
          </p>
        </>
      )}
      <div className="upload-actions">
        <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => pick(e.target.files?.[0])} />
        <button className="btn btn-primary" disabled={!!busy} onClick={() => input.current?.click()}>
          Choose CSV file
        </button>
        <button className="btn" disabled={!!busy} onClick={() => run("Loading sample…", api.loadSample)}>
          Use synthetic Order-to-Cash sample
        </button>
        {!compact && <span className="muted">or drop a file here</span>}
      </div>
      {busy && <p className="upload-status" role="status">{busy} Validating, building traces and discovering the process.</p>}
      {error && <p className="upload-error" role="alert">{error}</p>}
    </div>
  );
}
