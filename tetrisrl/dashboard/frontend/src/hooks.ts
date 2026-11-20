import { useCallback, useEffect, useRef, useState } from "react";
import { trainingSocketUrl } from "./api";

/**
 * Small async-data hook with optional polling.
 *
 * The page always fetches from the API on mount (no in-memory-only state) and
 * `refresh()` re-runs the loader on demand.
 */
export function useAsync<T>(
  loader: () => Promise<T>,
  deps: React.DependencyList,
  intervalMs?: number,
): {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const result = await loaderRef.current();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    let handle: number | undefined;
    if (intervalMs && intervalMs > 0) {
      handle = window.setInterval(() => void load(), intervalMs);
    }
    return () => {
      cancelled = true;
      if (handle) window.clearInterval(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadKey, intervalMs]);

  const refresh = useCallback(() => setReloadKey((key) => key + 1), []);
  return { data, error, loading, refresh };
}

/** Subscribe to the live training websocket; returns the latest event. */
export function useTrainingFeed(enabled = true): Record<string, unknown> | null {
  const [event, setEvent] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let socket: WebSocket | null = null;
    let stopped = false;
    let retry: number | undefined;

    const connect = async () => {
      if (stopped) return;
      try {
        socket = new WebSocket(trainingSocketUrl());
        socket.onmessage = (message) => {
          try {
            setEvent(JSON.parse(message.data as string) as Record<string, unknown>);
          } catch {
            /* ignore malformed frames */
          }
        };
        socket.onclose = () => {
          socket = null;
          if (!stopped) retry = window.setTimeout(() => void connect(), 5000);
        };
        socket.onerror = () => socket?.close();
      } catch {
        if (!stopped) retry = window.setTimeout(() => void connect(), 5000);
      }
    };
    void connect();
    return () => {
      stopped = true;
      if (retry) window.clearTimeout(retry);
      socket?.close();
    };
  }, [enabled]);

  return event;
}
