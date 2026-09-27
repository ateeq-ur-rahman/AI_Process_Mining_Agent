export const fmtInt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString());
export const fmtPct = (n: number | null | undefined) => (n == null ? "—" : `${n.toFixed(1)}%`);

export function fmtHours(h: number | null | undefined): string {
  if (h == null) return "—";
  if (h < 1) return `${Math.round(h * 60)} min`;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} d`;
}

export const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC" : "—";

export const humanize = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
