import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api/client";
import type { CaseView } from "../api/types";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Load data once on mount (and whenever `reload` is called). Ignores results after unmount. */
export function useAsync<T>(loader: () => Promise<T>): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loaderRef.current().then(
      (d) => {
        if (cancelled) return;
        setData(d);
        setLoading(false);
      },
      (e: unknown) => {
        if (cancelled) return;
        setError(errorMessage(e));
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

const POLL_MS = 1500;

export interface CaseState {
  data: CaseView | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

/**
 * Fetches a case and keeps polling every ~1.5 s while the case reports running = true.
 * Exactly one timer exists at a time and it is cleared on unmount or id change.
 */
export function useCase(id: string): CaseState {
  const [data, setData] = useState<CaseView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [kick, setKick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let lastRunning = false;

    const run = async () => {
      try {
        const view = await api.getCase(id);
        if (cancelled) return;
        setData(view);
        setError(null);
        setLoading(false);
        lastRunning = view.running;
        if (view.running) {
          timer = window.setTimeout(run, POLL_MS);
        }
      } catch (e) {
        if (cancelled) return;
        setError(errorMessage(e));
        setLoading(false);
        // Keep trying while we previously saw a running case; a transient failure should not freeze the page.
        if (lastRunning) timer = window.setTimeout(run, POLL_MS * 3);
      }
    };

    setLoading(true);
    run();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [id, kick]);

  const refresh = useCallback(() => setKick((k) => k + 1), []);
  return { data, error, loading, refresh };
}

/** Re-render periodically so relative timestamps stay fresh. */
export function useNow(intervalMs = 30000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} - DealScope` : "DealScope";
  }, [title]);
}
