import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { AsyncState } from "../components/Panels";
import StatusBadge from "../components/StatusBadge";
import { formatDate, formatNumber } from "../lib/format";

export default function Runs() {
  const [searchParams] = useSearchParams();
  const [algorithm, setAlgorithm] = useState(searchParams.get("algorithm") ?? "");
  const [status, setStatus] = useState(searchParams.get("status") ?? "");

  const { data, error, loading, refresh } = useAsync(
    () => api.runs({ algorithm: algorithm || undefined, status: status || undefined, limit: 500 }),
    [algorithm, status],
    4000,
  );

  const runs = useMemo(() => data?.runs ?? [], [data]);
  const [deleting, setDeleting] = useState<string | null>(null);

  const deleteRun = async (runId: string, status: string) => {
    const running = ["running", "starting"].includes(status);
    const message = running
      ? `Stop and delete run "${runId}"? This removes its checkpoints, replays and metrics permanently.`
      : `Delete run "${runId}"? This removes its checkpoints, replays and metrics permanently.`;
    if (!window.confirm(message)) return;
    setDeleting(runId);
    try {
      await api.deleteRun(runId);
      refresh();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(null);
    }
  };

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>Runs</h1>
          <p className="muted">Every run is persisted in SQLite; training processes are supervised.</p>
        </div>
        <div className="header-actions">
          <Link className="btn btn-primary" to="/runs/new">
            Start a new run
          </Link>
          <button className="btn" type="button" onClick={refresh}>
            Refresh
          </button>
        </div>
      </header>

      <div className="panel">
        <div className="panel-row">
          <h2>All runs</h2>
          <div className="filters">
            <select value={algorithm} onChange={(event) => setAlgorithm(event.target.value)}>
              <option value="">all algorithms</option>
              <option value="ppo">ppo</option>
              <option value="dqn">dqn</option>
            </select>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">all statuses</option>
              <option value="running">running</option>
              <option value="completed">completed</option>
              <option value="failed">failed</option>
              <option value="stopped">stopped</option>
              <option value="stale">stale</option>
            </select>
          </div>
        </div>

        <AsyncState error={error} loading={loading && !data} onRetry={refresh} />
        {data && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Algorithm</th>
                  <th>Status</th>
                  <th className="num">Seed</th>
                  <th className="num">Timesteps</th>
                  <th>Created</th>
                  <th>Notes</th>
                  <th className="num">Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 && (
                  <tr>
                    <td colSpan={8} className="muted">
                      No runs match the current filters.
                    </td>
                  </tr>
                )}
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Link to={`/runs/${encodeURIComponent(run.id)}`} className="mono">
                        {run.name || run.id}
                      </Link>
                    </td>
                    <td className="mono">{run.algorithm}</td>
                    <td>
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="num">{run.seed ?? "—"}</td>
                    <td className="num">
                      {formatNumber(run.total_timesteps)}
                      {(run.config as Record<string, unknown> | undefined)?.mode === "pretrain" ? " ep" : ""}
                    </td>
                    <td className="nowrap tiny">{formatDate(run.created_at)}</td>
                    <td className="truncate" title={run.notes ?? ""}>
                      {run.notes || "—"}
                    </td>
                    <td className="num">
                      <button
                        className="btn btn-danger btn-sm"
                        type="button"
                        disabled={deleting === run.id}
                        onClick={() => deleteRun(run.id, run.status)}
                      >
                        {deleting === run.id ? "Deleting…" : "Delete"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
