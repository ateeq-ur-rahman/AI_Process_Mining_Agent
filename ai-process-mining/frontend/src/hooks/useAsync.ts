import { useCallback, useEffect, useState } from "react";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fn().then(
      (d) => { if (alive) { setData(d); setLoading(false); } },
      (e: Error) => { if (alive) { setError(e.message); setLoading(false); } },
    );
    // `alive` stops a slow earlier request from overwriting the result of a newer one.
    return () => { alive = false; };
  }, [...deps, tick]); // fn is recreated every render, so the caller lists what it depends on

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
