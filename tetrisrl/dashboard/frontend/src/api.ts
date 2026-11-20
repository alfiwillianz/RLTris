import type {
  Checkpoint,
  CompareResponse,
  Health,
  Match,
  MetricsResponse,
  Overview,
  Replay,
  ReplayListItem,
  ParticipantsResponse,
  Run,
  Tournament,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export interface RunsQuery {
  algorithm?: string;
  status?: string;
  limit?: number;
}

export const api = {
  health: () => request<Health>("/api/health"),
  overview: () => request<Overview>("/api/overview"),
  runs: (query: RunsQuery = {}) => {
    const params = new URLSearchParams();
    if (query.algorithm) params.set("algorithm", query.algorithm);
    if (query.status) params.set("status", query.status);
    if (query.limit) params.set("limit", String(query.limit));
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<{ runs: Run[] }>(`/api/runs${suffix}`);
  },
  run: (runId: string) => request<Run>(`/api/runs/${encodeURIComponent(runId)}`),
  startRun: (body: {
    algorithm: string;
    config?: Record<string, unknown>;
    seed?: number;
    notes?: string;
    name?: string;
    timesteps?: number;
  }) =>
    request<{ run: Run; spawned: boolean; error: string | null }>("/api/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteRun: (runId: string) =>
    request<{ deleted: boolean; removed_files: number; removed_matches: number }>(
      `/api/runs/${encodeURIComponent(runId)}`,
      { method: "DELETE" },
    ),
  stopRun: (runId: string) =>
    request<{ run: Run; stop: Record<string, unknown> }>(`/api/runs/${encodeURIComponent(runId)}/stop`, {
      method: "POST",
    }),
  resumeRun: (runId: string) =>
    request<{ run: Run; spawned: boolean; error: string | null; checkpoint?: string }>(
      `/api/runs/${encodeURIComponent(runId)}/resume`,
      { method: "POST" },
    ),
  metrics: (runId: string, maxPoints = 500, names?: string[]) => {
    const params = new URLSearchParams({ max_points: String(maxPoints) });
    if (names && names.length) params.set("names", names.join(","));
    return request<MetricsResponse>(`/api/runs/${encodeURIComponent(runId)}/metrics?${params.toString()}`);
  },
  runCheckpoints: (runId: string) =>
    request<{ checkpoints: Checkpoint[] }>(`/api/runs/${encodeURIComponent(runId)}/checkpoints`),
  checkpoints: (limit = 500, runId?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (runId) params.set("run_id", runId);
    return request<{ checkpoints: Checkpoint[] }>(`/api/checkpoints?${params.toString()}`);
  },
  compare: (runIds: string[], metric: string, maxPoints = 500) => {
    const params = new URLSearchParams({
      run_ids: runIds.join(","),
      metric,
      max_points: String(maxPoints),
    });
    return request<CompareResponse>(`/api/compare?${params.toString()}`);
  },
  participants: () => request<ParticipantsResponse>("/api/participants"),
  tournaments: (limit = 100) => request<{ tournaments: Tournament[] }>(`/api/tournaments?limit=${limit}`),
  tournament: (tournamentId: string) =>
    request<{ tournament: Tournament; matches: Match[] }>(`/api/tournaments/${encodeURIComponent(tournamentId)}`),
  createTournament: (body: {
    name: string;
    participants: string[];
    seeds: number;
    max_pieces: number;
  }) =>
    request<{ tournament: Tournament; matches: Match[] }>("/api/tournaments", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteTournament: (tournamentId: string) =>
    request<{ deleted: boolean; removed_files: number; removed_matches: number }>(
      `/api/tournaments/${encodeURIComponent(tournamentId)}`,
      { method: "DELETE" },
    ),
  tournamentCsvUrl: (tournamentId: string) => apiUrl(`/api/tournaments/${encodeURIComponent(tournamentId)}/csv`),
  replays: (limit = 200) => request<{ replays: ReplayListItem[] }>(`/api/replays?limit=${limit}`),
  replay: (matchId: string) => request<Replay>(`/api/matches/${encodeURIComponent(matchId)}/replay`),
};

/** Websocket URL for the live training feed (honours VITE_API_BASE). */
export function trainingSocketUrl(): string {
  if (API_BASE) {
    try {
      const url = new URL(API_BASE, window.location.href);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = "/ws/training";
      url.search = "";
      return url.toString();
    } catch {
      /* fall through to same-origin */
    }
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/training`;
}
