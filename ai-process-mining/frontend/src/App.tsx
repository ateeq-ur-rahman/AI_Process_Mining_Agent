import { useCallback, useEffect, useState } from "react";
import { AppContext, type DrillTarget } from "./components/AppContext";
import { Drawer } from "./components/Drawer";
import { UploadPanel } from "./components/UploadPanel";
import { navigate, useHashRoute, type Route } from "./hooks/useHashRoute";
import { AIAnalyst } from "./pages/AIAnalyst";
import { Bottlenecks } from "./pages/Bottlenecks";
import { Dashboard } from "./pages/Dashboard";
import { Deviations } from "./pages/Deviations";
import { ProcessExplorer } from "./pages/ProcessExplorer";
import { Variants } from "./pages/Variants";
import { api } from "./services/api";
import type { Dataset } from "./types/api";

const NAV: { route: Route; label: string }[] = [
  { route: "dashboard", label: "Dashboard" },
  { route: "explorer", label: "Process map" },
  { route: "bottlenecks", label: "Bottlenecks" },
  { route: "deviations", label: "Deviations" },
  { route: "variants", label: "Variants" },
  { route: "analyst", label: "AI analyst" },
];

const STORE_KEY = "apm.dataset";

export default function App() {
  const { route, params } = useHashRoute();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetIdState] = useState<string | null>(null);
  const [drillTarget, setDrill] = useState<DrillTarget | null>(null);
  const [apiDown, setApiDown] = useState(false);

  const refreshDatasets = useCallback(() => {
    api.listDatasets().then((ds) => {
      setApiDown(false);
      setDatasets(ds);
      setDatasetIdState((cur) => {
        const ready = ds.filter((d) => d.status === "ready");
        let saved: string | null = null;
        try { saved = localStorage.getItem(STORE_KEY); } catch { /* storage unavailable */ }
        if (cur && ready.some((d) => d.id === cur)) return cur;
        if (saved && ready.some((d) => d.id === saved)) return saved;
        return ready[0]?.id ?? null;
      });
    }, () => setApiDown(true));
  }, []);
  useEffect(refreshDatasets, [refreshDatasets]);

  const setDatasetId = useCallback((id: string | null) => {
    setDatasetIdState(id);
    try { id ? localStorage.setItem(STORE_KEY, id) : localStorage.removeItem(STORE_KEY); } catch { /* ignore */ }
  }, []);

  const current = datasets.find((d) => d.id === datasetId);
  const needsData = route !== "dashboard" && !datasetId;

  return (
    <AppContext.Provider value={{ datasetId, setDatasetId, drill: setDrill, refreshDatasets }}>
      <div className="shell">
        <nav className="nav" aria-label="Main">
          <div className="brand">
            <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
              <circle cx="6" cy="8" r="3.5" /><circle cx="26" cy="8" r="3.5" /><circle cx="16" cy="25" r="3.5" />
              <path d="M9 8h13M8 11l6 11M24 11l-6 11" fill="none" strokeWidth="2.2" />
            </svg>
            <span>Process Mining Agent</span>
          </div>
          <div className="dataset-picker">
            <label htmlFor="ds">Event log</label>
            <select id="ds" value={datasetId ?? ""} onChange={(e) => setDatasetId(e.target.value || null)}>
              {datasets.filter((d) => d.status === "ready").length === 0 && <option value="">No logs yet</option>}
              {datasets.filter((d) => d.status === "ready").map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
            {current && (
              <button className="link small" onClick={() => { setDatasetId(null); navigate("dashboard"); }}>
                Upload another log
              </button>
            )}
          </div>
          <ul>
            {NAV.map((n) => (
              <li key={n.route}>
                <a href={`#/${n.route}`} aria-current={route === n.route ? "page" : undefined}>{n.label}</a>
              </li>
            ))}
          </ul>
        </nav>
        <main className="main">
          {apiDown && <p className="upload-error" role="alert">Can't reach the API. Check that the backend is running.</p>}
          {needsData ? (
            <div>
              <h1>Start with an event log</h1>
              <UploadPanel onDone={(d) => { refreshDatasets(); setDatasetId(d.id); }} />
            </div>
          ) : (
            <div key={datasetId ?? "none"}>
              {route === "dashboard" && <Dashboard />}
              {route === "explorer" && <ProcessExplorer />}
              {route === "bottlenecks" && <Bottlenecks />}
              {route === "deviations" && <Deviations initialType={params.get("type") ?? undefined} />}
              {route === "variants" && <Variants />}
              {route === "analyst" && <AIAnalyst />}
            </div>
          )}
        </main>
      </div>
      <Drawer target={drillTarget} onClose={() => setDrill(null)} />
    </AppContext.Provider>
  );
}
