import type { ReactNode } from "react";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="state" role="status">{label}</div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <p>{message}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Kpi({ value, label, hint }: { value: ReactNode; label: string; hint?: string }) {
  return (
    <div className="kpi" title={hint}>
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}

export function Indicator({ level }: { level: string }) {
  const cls = level === "HIGH" ? "ind-high" : level === "MEDIUM" ? "ind-med" : level === "LOW" ? "ind-low" : "ind-na";
  const text = level === "NOT_SCORED" ? "Not scored" : level.charAt(0) + level.slice(1).toLowerCase();
  return <span className={`ind ${cls}`}>{text}</span>;
}

export function Severity({ level }: { level: "low" | "medium" | "high" }) {
  return <Indicator level={level.toUpperCase()} />;
}

export function Trace({ steps, highlight }: { steps: string[]; highlight?: Set<string> }) {
  return (
    <ol className="trace">
      {steps.map((s, i) => (
        <li key={i} className={highlight?.has(s) ? "trace-hl" : undefined}>{s}</li>
      ))}
    </ol>
  );
}

export function PageHeader({ title, lede, actions }: { title: string; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {lede && <p className="lede">{lede}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="note">{children}</p>;
}
