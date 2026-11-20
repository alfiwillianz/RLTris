export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

export function formatMetric(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 10000) return value.toExponential(2);
  if (Math.abs(value) >= 100) return value.toFixed(1);
  return value.toFixed(digits);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const percent = Math.abs(value) <= 1 ? value * 100 : value;
  return `${percent.toFixed(digits)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function formatTimesteps(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

export function statusClass(status: string | null | undefined): string {
  const normalized = (status ?? "unknown").toLowerCase();
  if (["running", "starting"].includes(normalized)) return "status status-running";
  if (["completed"].includes(normalized)) return "status status-completed";
  if (["failed", "stale"].includes(normalized)) return "status status-failed";
  if (["stopped", "paused"].includes(normalized)) return "status status-stopped";
  return "status status-created";
}

export function winnerLabel(winner: number | null | undefined): string {
  if (winner === null || winner === undefined) return "draw";
  return winner === 0 ? "A wins" : "B wins";
}

export function metricLabel(metric: string): string {
  return metric
    .replace(/^train\//, "")
    .replace(/^eval\//, "eval · ")
    .replace(/[_.]/g, " ");
}

export const METRIC_COLORS = [
  "#22d3ee",
  "#f59e0b",
  "#10b981",
  "#a78bfa",
  "#f43f5e",
  "#38bdf8",
  "#fb923c",
  "#e879f9",
  "#84cc16",
  "#94a3b8",
];
