import { useEffect, useState } from "react";

export type Route = "dashboard" | "explorer" | "bottlenecks" | "deviations" | "variants" | "analyst";
const ROUTES: Route[] = ["dashboard", "explorer", "bottlenecks", "deviations", "variants", "analyst"];

function parse(): { route: Route; params: URLSearchParams } {
  const [path, query] = window.location.hash.replace(/^#\/?/, "").split("?");
  const route = (ROUTES.includes(path as Route) ? path : "dashboard") as Route;
  return { route, params: new URLSearchParams(query ?? "") };
}

export function useHashRoute() {
  const [state, setState] = useState(parse);
  useEffect(() => {
    const on = () => setState(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return state;
}

export function navigate(route: Route, params?: Record<string, string>) {
  const qs = params ? new URLSearchParams(params).toString() : "";
  window.location.hash = `/${route}${qs ? `?${qs}` : ""}`;
}
