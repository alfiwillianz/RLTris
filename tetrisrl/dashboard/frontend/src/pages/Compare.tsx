import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import MetricChart from "../components/MetricChart";
import { AsyncState } from "../components/Panels";
import StatusBadge from "../components/StatusBadge";
import { formatMetric, formatNumber, metricLabel } from "../lib/format";
import type { Checkpoint, MetricsResponse, Run } from "../types";

const DEFAULT_METRICS = [
  "eval/win_rate",
  "train/episode_reward",
  "train/reward",
  "train/loss",
  "eval/mean_reward",
  "train/entropy",
  "train/epsilon",
];

function latestPoint(metrics: MetricsResponse | undefined, name: string): number | null {
  const series = metrics?.metrics?.[name];
  if (!series || !series.length) return null;
  return series[series.length - 1][1];
}

function opponentRates(checkpoints: Checkpoint[]): { source: string; rates: [string, number][] } | null {
  for (const checkpoint of checkpoints) {
    const metadata = checkpoint.metadata ?? {};
    const candidates = ["opponents", "per_opponent", "win_rates", "opponent_win_rates"];
    for (const key of candidates) {
      const value = (metadata as Record<string, unknown>)[key];
      if (value && typeof value === "object" && !Array.isArray(value)) {
        const rates = Object.entries(value as Record<string, unknown>)
          .filter(([, rate]) => typeof rate === "number")
          .map(([opponent, rate]) => [opponent, rate as number] as [string, number]);
        if (rates.length) {
          return { source: `${key} @ ${checkpoint.timestep}`, rates };
        }
      }
    }
  }
  return null;
}

export default function Compare() {
  const runsState = useAsync(() => api.runs({ limit: 500 }), [], 10000);
  const runs = runsState.data?.runs ?? [];
  const [selected, setSelected] = useState<string[]>([]);
  const [metric, setMetric] = useState("eval/win_rate");
  const [availableMetrics, setAvailableMetrics] = useState<string[]>(DEFAULT_METRICS);

  useEffect(() => {
    if (selected.length || !runs.length) return;
    const completed = runs.filter((run) => run.status === "completed");
    const initial = (completed.length >= 2 ? completed : runs).slice(0, 2).map((run) => run.id);
    setSelected(initial);
  }, [runs, selected.length]);

  const selectedKey = selected.join(",");

  useEffect(() => {
    if (!selected.length) return;
    let cancelled = false;
    (async () => {
      const responses = await Promise.all(
        selected.map((runId) => api.metrics(runId, 1).catch(() => null)),
      );
      if (cancelled) return;
      const names = new Set<string>(DEFAULT_METRICS);
      responses.forEach((response) => response?.names.forEach((name) => names.add(name)));
      setAvailableMetrics([...names].sort());
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedKey]);

  const compareState = useAsync(async () => {
    if (!selected.length || !metric) return null;
    return api.compare(selected, metric, 500);
  }, [selectedKey, metric], 5000);

  const evaluationState = useAsync(async () => {
    if (!selected.length) return [];
    return Promise.all(
      selected.map(async (runId) => {
        const [metrics, checkpoints] = await Promise.all([
          api
            .metrics(runId, 500, ["eval/win_rate", "eval/win_rate_ci_low", "eval/win_rate_ci_high"])
            .catch(() => null),
          api.runCheckpoints(runId).catch(() => ({ checkpoints: [] as Checkpoint[] })),
        ]);
        return { runId, metrics, checkpoints: checkpoints.checkpoints };
      }),
    );
  }, [selectedKey], 10000);

  const runsById = useMemo(() => {
    const map = new Map<string, Run>();
    runs.forEach((run) => map.set(run.id, run));
    return map;
  }, [runs]);

  const chartSeries = useMemo(() => {
    const payload = compareState.data;
    if (!payload) return [];
    return payload.runs
      .filter((run) => run.series.length)
      .map((run) => ({
        key: run.run_id,
        label: `${run.name || run.run_id} · ${run.algorithm}`,
        points: run.series,
      }));
  }, [compareState.data]);

  const toggle = (runId: string) => {
    setSelected((current) =>
      current.includes(runId) ? current.filter((item) => item !== runId) : [...current, runId],
    );
  };

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>Compare</h1>
          <p className="muted">Overlay training curves and evaluation statistics across runs.</p>
        </div>
        <button className="btn" type="button" onClick={runsState.refresh}>
          Refresh
        </button>
      </header>

      <AsyncState
        error={runsState.error}
        loading={runsState.loading && !runsState.data}
        onRetry={runsState.refresh}
      />

      <div className="grid-two compare-layout">
        <div className="panel">
          <h2>Select runs</h2>
          {runs.length === 0 && <p className="muted">No runs available.</p>}
          <div className="run-picker">
            {runs.map((run) => (
              <label key={run.id} className={selected.includes(run.id) ? "run-option run-option-active" : "run-option"}>
                <input
                  type="checkbox"
                  checked={selected.includes(run.id)}
                  onChange={() => toggle(run.id)}
                />
                <span className="run-option-main">
                  <span className="mono">{run.name || run.id}</span>
                  <span className="tiny muted">
                    {run.algorithm} · {formatNumber(run.total_timesteps)} steps
                  </span>
                </span>
                <StatusBadge status={run.status} />
              </label>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2>Metric</h2>
          <label className="stack">
            <select value={metric} onChange={(event) => setMetric(event.target.value)}>
              {availableMetrics.map((name) => (
                <option key={name} value={name}>
                  {metricLabel(name)}
                </option>
              ))}
            </select>
          </label>
          <p className="tiny muted">
            Selected: {selected.length} run{selected.length === 1 ? "" : "s"}.{" "}
            <button className="link-button" type="button" onClick={() => setSelected(runs.map((run) => run.id))}>
              all
            </button>{" "}
            ·{" "}
            <button className="link-button" type="button" onClick={() => setSelected([])}>
              none
            </button>
          </p>
          <p className="tiny muted">Metrics are downsampled to at most 500 points per run.</p>
        </div>
      </div>

      <div className="panel">
        <div className="panel-row">
          <h2>{metricLabel(metric)}</h2>
          <span className="tiny muted">polled every 5s</span>
        </div>
        <AsyncState
          error={compareState.error}
          loading={compareState.loading && !compareState.data}
          onRetry={compareState.refresh}
        />
        {!selected.length && <p className="muted">Select at least one run to overlay series.</p>}
        {selected.length > 0 && <MetricChart series={chartSeries} height={380} />}
      </div>

      <div className="panel">
        <h2>Evaluation win rates</h2>
        <AsyncState
          error={evaluationState.error}
          loading={evaluationState.loading && !evaluationState.data}
          onRetry={evaluationState.refresh}
        />
        {evaluationState.data && evaluationState.data.length > 0 && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Algorithm</th>
                  <th className="num">Win rate</th>
                  <th className="num">CI low</th>
                  <th className="num">CI high</th>
                  <th>Per-opponent win rates</th>
                </tr>
              </thead>
              <tbody>
                {evaluationState.data.map((entry) => {
                  const run = runsById.get(entry.runId);
                  const opponents = opponentRates(entry.checkpoints);
                  return (
                    <tr key={entry.runId}>
                      <td>
                        <Link to={`/runs/${encodeURIComponent(entry.runId)}`} className="mono">
                          {run?.name || entry.runId}
                        </Link>
                      </td>
                      <td className="mono">{run?.algorithm ?? "—"}</td>
                      <td className="num">{formatMetric(latestPoint(entry.metrics ?? undefined, "eval/win_rate"))}</td>
                      <td className="num">
                        {formatMetric(latestPoint(entry.metrics ?? undefined, "eval/win_rate_ci_low"))}
                      </td>
                      <td className="num">
                        {formatMetric(latestPoint(entry.metrics ?? undefined, "eval/win_rate_ci_high"))}
                      </td>
                      <td>
                        {opponents ? (
                          <span className="tiny" title={`source: ${opponents.source}`}>
                            {opponents.rates
                              .map(([opponent, rate]) => `${opponent}: ${formatMetric(rate, 2)}`)
                              .join(" · ")}
                          </span>
                        ) : (
                          <span className="muted tiny">not recorded</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {evaluationState.data?.length === 0 && <p className="muted">Select runs to compare evaluations.</p>}
      </div>
    </section>
  );
}
