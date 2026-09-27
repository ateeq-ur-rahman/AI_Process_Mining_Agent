import { useEffect, useRef, useState } from "react";
import { useApp } from "../components/AppContext";
import { Loading, Note, PageHeader, Severity } from "../components/ui";
import { navigate } from "../hooks/useHashRoute";
import { api } from "../services/api";
import type { AnalysisReport, Drilldown, Evidence, QueryAnswer } from "../types/api";

const SUGGESTIONS = [
  "Where is the biggest bottleneck?",
  "How many orders experienced rework?",
  "How many cases skipped Quality Check?",
  "What is the most common path?",
  "How long does a case take?",
  "Which resources handle the most cases?",
];

type Turn = { role: "user"; content: string } | { role: "assistant"; content: string; answer?: QueryAnswer; error?: boolean };

export function AIAnalyst() {
  const { datasetId } = useApp();
  const [status, setStatus] = useState<{ llm_enabled: boolean; model: string | null } | null>(null);
  useEffect(() => { api.aiStatus().then(setStatus, () => setStatus(null)); }, []);
  return (
    <>
      <PageHeader title="AI analyst"
        lede={<>Answers and reports are built from the computed metrics. Expand the evidence under an answer to see which numbers it used.{" "}
          {status && (status.llm_enabled
            ? <>Model: {status.model}.</>
            : <>No LLM is configured, so answers come from templates over the same metrics.</>)}</>} />
      <div className="analyst">
        <Chat datasetId={datasetId!} />
        <Report datasetId={datasetId!} />
      </div>
    </>
  );
}

function EvidenceList({ items }: { items: Evidence[] }) {
  if (!items.length) return null;
  return (
    <dl className="evidence">
      {items.map((e, i) => (
        <div key={i}><dt>{e.metric}</dt><dd>{e.value}</dd></div>
      ))}
    </dl>
  );
}

function Chat({ datasetId }: { datasetId: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { setTurns([]); }, [datasetId]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [turns]);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || busy) return;
    const history = turns.map((t) => ({ role: t.role, content: t.content }));
    setTurns((t) => [...t, { role: "user", content: q }]);
    setText(""); setBusy(true);
    try {
      const a = await api.query(datasetId, q, history);
      setTurns((t) => [...t, { role: "assistant", content: a.answer, answer: a }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", content: (e as Error).message, error: true }]);
    } finally { setBusy(false); }
  }

  return (
    <section className="panel chat">
      <h2>Ask about this process</h2>
      <div className="chat-log" aria-live="polite">
        {turns.length === 0 && (
          <div className="suggestions">
            {SUGGESTIONS.map((s) => <button key={s} className="btn" onClick={() => ask(s)}>{s}</button>)}
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`msg msg-${t.role}${"error" in t && t.error ? " msg-error" : ""}`}>
            <p>{t.content}</p>
            {t.role === "assistant" && t.answer && (
              <details>
                <summary>Evidence ({t.answer.evidence.length}), {t.answer.mode === "llm" ? "LLM" : "rule-based"} answer</summary>
                <EvidenceList items={t.answer.evidence} />
                <p className="muted">Engine queries: {t.answer.tools_used.join(", ")}</p>
              </details>
            )}
            {t.role === "assistant" && t.answer?.flags.map((f) => <p key={f} className="flag">{f}</p>)}
          </div>
        ))}
        {busy && <div className="msg msg-assistant"><p className="muted">Querying the engine…</p></div>}
        <div ref={end} />
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
        <label htmlFor="q" className="sr-only">Question</label>
        <input id="q" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about this process…" maxLength={1000} />
        <button className="btn btn-primary" disabled={busy || !text.trim()}>Ask</button>
      </form>
    </section>
  );
}

function drillTo(d: Drilldown | null, drill: ReturnType<typeof useApp>["drill"]) {
  if (!d) return null;
  if (d.kind === "activity" && d.activity)
    return () => drill({ kind: "events", title: `Waiting before ${d.activity}`, activity: d.activity! });
  if (d.kind === "transition" && d.source)
    return () => drill({ kind: "events", title: `${d.source} → ${d.target}`, source: d.source!, target: d.target! });
  if (d.kind === "deviation" && d.deviation_type) return () => navigate("deviations", { type: d.deviation_type! });
  if (d.kind === "variant") return () => navigate("variants");
  if (d.kind === "resource" && d.resource)
    return () => drill({ kind: "events", title: `Events by ${d.resource}`, resource: d.resource! });
  return null;
}

function Report({ datasetId }: { datasetId: string }) {
  const { drill } = useApp();
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [focus, setFocus] = useState("");

  useEffect(() => {
    setReport(null);
    api.latestReport(datasetId).then((r) => setReport(r.report), () => setReport(null));
  }, [datasetId]);

  async function generate() {
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await api.analyze(datasetId, focus);
      setReport(r.report);
      if (r.meta.llm_error) setNotice(`The language model call failed (${r.meta.llm_error}); this report was generated by rules instead.`);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <section className="panel report">
      <div className="panel-head">
        <h2>Analysis report</h2>
        {report && <a className="btn" href={api.reportMarkdownUrl(datasetId)} download>Download Markdown</a>}
      </div>
      <form className="inline-form" onSubmit={(e) => { e.preventDefault(); generate(); }}>
        <label htmlFor="focus" className="sr-only">Focus (optional)</label>
        <input id="focus" placeholder="Optional focus, e.g. payment delays" value={focus} maxLength={500}
          onChange={(e) => setFocus(e.target.value)} />
        <button className="btn btn-primary" disabled={busy}>{report ? "Regenerate report" : "Generate report"}</button>
      </form>
      {busy && <Loading label="Writing report…" />}
      {error && <p className="upload-error" role="alert">{error}</p>}
      {notice && <p className="flag">{notice}</p>}
      {!report && !busy && <p className="muted">The report lists the main findings, the numbers behind each, and what to look into next.</p>}
      {report && (
        <>
          <p className="report-summary">{report.summary}</p>
          <p className="muted">Generated {report.generated_by.mode === "llm" ? `by ${report.generated_by.model}` : "by rules"}, prompt {report.generated_by.prompt_version}.</p>
          {report.guardrail_flags.map((f) => <p key={f} className="flag">{f}</p>)}
          {report.key_findings.map((f, i) => {
            const go = drillTo(f.drilldown, drill);
            return (
              <article key={i} className={`finding sev-${f.severity}`}>
                <header><h3>{f.title}</h3><Severity level={f.severity} /></header>
                <p>{f.description}</p>
                <h4>Evidence</h4>
                <EvidenceList items={f.evidence} />
                {f.possible_explanations.length > 0 && (<>
                  <h4>Possible explanations, not established by the data</h4>
                  <ul>{f.possible_explanations.map((x) => <li key={x}>{x}</li>)}</ul>
                </>)}
                {f.recommended_investigations.length > 0 && (<>
                  <h4>Worth investigating</h4>
                  <ul>{f.recommended_investigations.map((x) => <li key={x}>{x}</li>)}</ul>
                </>)}
                {go && <button className="btn" onClick={go}>Inspect underlying data</button>}
              </article>
            );
          })}
          {report.data_quality_notes.length > 0 && (<><h3>Data quality</h3><ul>{report.data_quality_notes.map((x) => <li key={x}>{x}</li>)}</ul></>)}
          <h3>Limitations</h3>
          <ul>{report.limitations.map((x) => <li key={x}>{x}</li>)}</ul>
          <h3>Data that would help</h3>
          <ul>{report.additional_data_suggestions.map((x) => <li key={x}>{x}</li>)}</ul>
          <Note>Recommendations are suggestions for investigation, not operational decisions.</Note>
        </>
      )}
    </section>
  );
}
