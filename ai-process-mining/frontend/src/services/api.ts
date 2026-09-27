import type {
  AnalysisReport, Bottlenecks, CaseDetail, Dataset, Deviations, EventRow, InvalidRow, Overview, ProcessGraph,
  QueryAnswer, Resources, Variants,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(message: string, public status: number, public details?: unknown) {
    super(message);
  }
}

// For responses that don't come from our API (nginx, the Vite proxy), so there is no JSON error body.
const FALLBACK_MESSAGES: Record<number, string> = {
  413: "The file is larger than the server's upload limit.",
  502: "The backend isn't responding. Check that it is running.",
  504: "The backend took too long to respond.",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError("Can't reach the API. Check that the backend is running.", 0);
  }
  if (!res.ok) {
    let body: { error?: string; details?: unknown } = {};
    try { body = await res.json(); } catch { /* HTML error page from a proxy */ }
    const message = body.error ?? FALLBACK_MESSAGES[res.status] ?? `Request failed with HTTP ${res.status}.`;
    throw new ApiError(message, res.status, body.details);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") s.set(k, String(v)); });
  const str = s.toString();
  return str ? `?${str}` : "";
};

const enc = encodeURIComponent;

export const api = {
  health: () => request<{ status: string; llm_enabled: boolean }>("/api/health"),
  aiStatus: () => request<{ llm_enabled: boolean; model: string | null; prompt_version: string }>("/api/research/status"),
  listDatasets: () => request<Dataset[]>("/api/datasets"),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<Dataset>("/api/datasets/upload", { method: "POST", body: fd });
  },
  loadSample: () => request<Dataset>("/api/datasets/sample", { method: "POST" }),
  deleteDataset: (id: string) => request<void>(`/api/datasets/${id}`, { method: "DELETE" }),
  validation: (id: string) => request<{ report: Dataset["validation_report"]; status: string; error: string | null }>(
    `/api/datasets/${id}/validation`),
  invalidRows: (id: string, issue?: string, offset = 0) =>
    request<{ total: number; items: InvalidRow[] }>(`/api/datasets/${id}/validation/invalid-rows${q({ issue, offset, limit: 100 })}`),
  invalidRowsCsvUrl: (id: string) => `${BASE}/api/datasets/${id}/validation/invalid-rows.csv`,
  caseDetail: (id: string, caseId: string) => request<CaseDetail>(`/api/datasets/${id}/cases/${enc(caseId)}`),
  events: (id: string, p: { activity?: string; source?: string; target?: string; resource?: string; offset?: number }) =>
    request<{ total: number; items: EventRow[] }>(`/api/datasets/${id}/events${q({ ...p, limit: 100 })}`),
  overview: (id: string) => request<Overview>(`/api/process/${id}/overview`),
  graph: (id: string) => request<ProcessGraph>(`/api/process/${id}/graph`),
  variants: (id: string) => request<Variants>(`/api/process/${id}/variants?limit=200`),
  variantCases: (id: string, v: string) =>
    request<{ total: number; items: { case_id: string; duration_hours: number; start: string; n_events: number }[] }>(
      `/api/process/${id}/variants/${enc(v)}/cases?limit=50`),
  bottlenecks: (id: string, weights?: Record<string, number>) =>
    request<Bottlenecks>(`/api/process/${id}/bottlenecks${weights ? q(Object.fromEntries(
      Object.entries(weights).map(([k, v]) => [`w_${k}`, v]))) : ""}`),
  deviations: (id: string, p: { type?: string; activity?: string; case_id?: string; offset?: number }) =>
    request<Deviations>(`/api/process/${id}/deviations${q({ ...p, limit: 50 })}`),
  resources: (id: string) => request<Resources>(`/api/process/${id}/resources`),
  analyze: (id: string, focus?: string) =>
    request<{ run_id: string; report: AnalysisReport; meta: { mode: string; llm_error?: string | null } }>(
      `/api/research/${id}/analyze`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ focus: focus || null }) }),
  latestReport: (id: string) => request<{ report: AnalysisReport; created_at: string }>(`/api/research/${id}/latest`),
  reportMarkdownUrl: (id: string) => `${BASE}/api/research/${id}/report.md`,
  query: (id: string, question: string, history: { role: string; content: string }[]) =>
    request<QueryAnswer>(`/api/query/${id}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }) }),
};
