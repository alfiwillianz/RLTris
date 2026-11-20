import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync, useTrainingFeed } from "../hooks";
import MetricChart from "../components/MetricChart";
import { AsyncState } from "../components/Panels";
import StatusBadge from "../components/StatusBadge";
import {
  formatDate,
  formatMetric,
  formatNumber,
  metricLabel,
  METRIC_COLORS,
} from "../lib/format";
import type { Checkpoint } from "../types";

const PREFERRED_METRICS = [
  "train/episode_reward",
  "train/reward",
  "train/moving_avg_reward",
  "eval/win_rate",
  "train/win_rate",
  "train/loss",
  "train/entropy",
  "train/epsilon",
  "train/lines",
  "eval/mean_reward",
];

function checkpointHref(checkpoint: Checkpoint, algorithm: string): string {
  const key = algorithm === "dqn" ? "dqn" : "ppo";
  return `/tournaments?${key}=${encodeURIComponent(checkpoint.path)}`;
}

export default function RunDetail() {
  const { runId = "" } = useParams();
  const encoded = encodeURIComponent(runId);
  const runState = useAsync(() => api.run(runId), [runId], 3000);
  const metricState = useAsync(() => api.metrics(runId, 500), [runId], 3000);
  const checkpointState = useAsync(() => api.runCheckpoints(runId), [runId], 6000);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const liveEvent = useTrainingFeed(true);

  const names = metricState.data?.names ?? [];
  const liveMetric =
    liveEvent && liveEvent.type === "metric" && liveEvent.run_id === runId ? liveEvent : null;
  const liveMetrics =
    liveMetric && typeof liveMetric.metrics === "object" && liveMetric.metrics
      ? (liveMetric.metrics as Record<string, number>)
      : {};

  useEffect(() => {
    if (!names.length) return;
    setSelected((current) => {
      if (current.length) return current;
      const preferred = PREFERRED_METRICS.filter((name) => names.includes(name));
      return preferred.length ? preferred.slice(0, 4) : names.slice(0, 3);
    });
  }, [names]);

  const chartSeries = useMemo(() => {
    const metrics = metricState.data?.metrics ?? {};
    return selected
      .filter((name) => metrics[name]?.length)
      .map((name, index) => ({
        key: name,
        label: metricLabel(name),
        points: metrics[name],
        color: METRIC_COLORS[index % METRIC_COLORS.length],
      }));
  }, [metricState.data, selected]);

  const run = runState.data;

  const stop = async () => {
    setBusy(true);
    setActionError(null);
    setActionNotice(null);
    try {
      await api.stopRun(runId);
      setActionNotice("Run stopped.");
      runState.refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const resume = async () => {
    setBusy(true);
    setActionError(null);
    setActionNotice(null);
    try {
      const response = await api.resumeRun(runId);
      setActionNotice(
        response.spawned
          ? `Resumed from ${response.checkpoint ?? "checkpoint"}.`
          : response.error ?? "No process spawned.",
      );
      runState.refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const toggleMetric = (name: string) => {
    setSelected((current) =>
      current.includes(name) ? current.filter((item) => item !== name) : [...current, name],
    );
  };

  return (
    <section>
      <div className="breadcrumb">
        <Link to="/runs">Runs</Link> / <span className="mono">{runId}</span>
      </div>
      <header className="page-header">
        <div>
          <h1>{run?.name || runId}</h1>
          <p className="muted mono">{runId}</p>
        </div>
        <div className="header-actions">
          {run && <StatusBadge status={run.status} />}
          <button className="btn" type="button" onClick={runState.refresh}>
            Refresh
          </button>
          <button
            className="btn btn-danger"
            type="button"
            onClick={stop}
            disabled={busy || !run || !["running", "starting"].includes(run.status)}
          >
            Stop
          </button>
          <button
            className="btn"
            type="button"
            onClick={resume}
            disabled={busy || !run || run.status === "running"}
            title="Resume from the best or latest checkpoint"
          >
            Resume
          </button>
        </div>
      </header>

      <AsyncState error={runState.error} loading={runState.loading && !run} onRetry={runState.refresh} />
      {actionError && <div className="form-error panel">{actionError}</div>}
      {actionNotice && <div className="form-notice panel">{actionNotice}</div>}

      {run && (
        <>
          <div className="panel">
            <div className="kv-grid">
              <div>
                <span className="muted">Algorithm</span>
                <div className="mono">{run.algorithm}</div>
              </div>
              <div>
                <span className="muted">Seed</span>
                <div className="mono">{run.seed ?? "—"}</div>
              </div>
              <div>
                <span className="muted">Timesteps</span>
                <div className="mono">{formatNumber(run.total_timesteps)}</div>
              </div>
              <div>
                <span className="muted">PID</span>
                <div className="mono">{run.pid ?? "—"}</div>
              </div>
              <div>
                <span className="muted">Created</span>
                <div className="tiny">{formatDate(run.created_at)}</div>
              </div>
              <div>
                <span className="muted">Started</span>
                <div className="tiny">{formatDate(run.started_at)}</div>
              </div>
              <div>
                <span className="muted">Ended</span>
                <div className="tiny">{formatDate(run.ended_at)}</div>
              </div>
              <div>
                <span className="muted">Results dir</span>
                <div className="tiny mono truncate" title={run.results_dir ?? ""}>
                  {run.results_dir ?? "—"}
                </div>
              </div>
            </div>
            {run.notes && (
              <p>
                <span className="muted">Notes: </span>
                {run.notes}
              </p>
            )}
            {run.error && <p className="form-error mono">{run.error}</p>}
            {run.best_checkpoint && (
              <p className="tiny">
                Best checkpoint: <span className="mono">{run.best_checkpoint}</span>
              </p>
            )}
          </div>

          <div className="panel">
            <div className="panel-row">
              <h2>Training metrics</h2>
              <div className="tiny muted">
                {names.length} metric series · polled every 3s
                {liveMetric ? ` · live timestep ${formatNumber(Number(liveMetric.timestep))}` : ""}
              </div>
            </div>
            {liveMetric && Object.keys(liveMetrics).length > 0 && (
              <p className="tiny muted mono">
                live:{" "}
                {Object.entries(liveMetrics)
                  .slice(0, 4)
                  .map(([name, value]) => `${name}=${formatMetric(Number(value))}`)
                  .join(" · ")}
              </p>
            )}
            <AsyncState
              error={metricState.error}
              loading={metricState.loading && !metricState.data}
              onRetry={metricState.refresh}
            />
            {metricState.data && names.length === 0 && <p className="muted">No metrics logged yet.</p>}
            {names.length > 0 && (
              <>
                <div className="metric-picker">
                  {names.map((name) => (
                    <label key={name} className={selected.includes(name) ? "chip chip-active" : "chip"}>
                      <input
                        type="checkbox"
                        checked={selected.includes(name)}
                        onChange={() => toggleMetric(name)}
                      />
                      {metricLabel(name)}
                    </label>
                  ))}
                </div>
                <div className="metric-actions">
                  <button className="btn btn-small" type="button" onClick={() => setSelected(names)}>
                    Select all
                  </button>
                  <button className="btn btn-small" type="button" onClick={() => setSelected([])}>
                    Clear
                  </button>
                </div>
                <MetricChart series={chartSeries} height={360} />
              </>
            )}
          </div>

          <div className="panel">
            <div className="panel-row">
              <h2>Checkpoints</h2>
              <span className="tiny muted">{checkpointState.data?.checkpoints.length ?? 0} saved</span>
            </div>
            <AsyncState
              error={checkpointState.error}
              loading={checkpointState.loading && !checkpointState.data}
              onRetry={checkpointState.refresh}
            />
            {checkpointState.data && checkpointState.data.checkpoints.length === 0 && (
              <p className="muted">No checkpoints recorded for this run.</p>
            )}
            {checkpointState.data && checkpointState.data.checkpoints.length > 0 && (
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th className="num">Timestep</th>
                      <th className="num">Mean reward</th>
                      <th className="num">Win rate</th>
                      <th>Created</th>
                      <th>Path</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checkpointState.data.checkpoints.map((checkpoint) => (
                      <tr key={checkpoint.id}>
                        <td className="num">{formatNumber(checkpoint.timestep)}</td>
                        <td className="num">{formatMetric(checkpoint.mean_reward)}</td>
                        <td className="num">{formatMetric(checkpoint.win_rate)}</td>
                        <td className="tiny">{formatDate(checkpoint.created_at)}</td>
                        <td className="mono tiny truncate" title={checkpoint.path}>
                          {checkpoint.path}
                        </td>
                        <td>
                          <Link to={checkpointHref(checkpoint, run.algorithm)}>Evaluate</Link>
                          {" · "}
                          <Link to="/replays">Replays</Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
      {runState.error && (
        <p className="tiny muted">
          <Link to={`/api/runs/${encoded}`}>Raw API response</Link>
        </p>
      )}
    </section>
  );
}
