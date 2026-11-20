import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { AsyncState } from "../components/Panels";
import { formatDate, formatMetric, formatNumber } from "../lib/format";
import type { Run } from "../types";

export default function Checkpoints() {
  const checkpointsState = useAsync(() => api.checkpoints(1000), [], 10000);
  const runsState = useAsync(() => api.runs({ limit: 1000 }), [], 30000);
  const [query, setQuery] = useState("");

  const runsById = useMemo(() => {
    const map = new Map<string, Run>();
    (runsState.data?.runs ?? []).forEach((run) => map.set(run.id, run));
    return map;
  }, [runsState.data]);

  const checkpoints = useMemo(() => {
    const all = checkpointsState.data?.checkpoints ?? [];
    const needle = query.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((checkpoint) => {
      const run = runsById.get(checkpoint.run_id);
      return [checkpoint.run_id, checkpoint.path, run?.algorithm ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [checkpointsState.data, runsById, query]);

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>Checkpoints</h1>
          <p className="muted">Browse saved policies, inspect evaluation metadata, and set up evaluations.</p>
        </div>
        <button
          className="btn"
          type="button"
          onClick={() => {
            checkpointsState.refresh();
            runsState.refresh();
          }}
        >
          Refresh
        </button>
      </header>

      <div className="panel">
        <div className="panel-row">
          <h2>All checkpoints</h2>
          <input
            className="search-input"
            placeholder="filter by run, algorithm, path…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <AsyncState
          error={checkpointsState.error}
          loading={checkpointsState.loading && !checkpointsState.data}
          onRetry={checkpointsState.refresh}
        />
        {checkpointsState.data && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Algorithm</th>
                  <th className="num">Timestep</th>
                  <th className="num">Mean reward</th>
                  <th className="num">Win rate</th>
                  <th>Created</th>
                  <th>Path</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {checkpoints.length === 0 && (
                  <tr>
                    <td colSpan={8} className="muted">
                      No checkpoints recorded yet.
                    </td>
                  </tr>
                )}
                {checkpoints.map((checkpoint) => {
                  const run = runsById.get(checkpoint.run_id);
                  const algorithm = run?.algorithm ?? "";
                  const key = algorithm === "dqn" ? "dqn" : "ppo";
                  return (
                    <tr key={checkpoint.id}>
                      <td>
                        <Link to={`/runs/${encodeURIComponent(checkpoint.run_id)}`} className="mono">
                          {run?.name || checkpoint.run_id}
                        </Link>
                      </td>
                      <td className="mono">{algorithm || "—"}</td>
                      <td className="num">{formatNumber(checkpoint.timestep)}</td>
                      <td className="num">{formatMetric(checkpoint.mean_reward)}</td>
                      <td className="num">{formatMetric(checkpoint.win_rate)}</td>
                      <td className="tiny">{formatDate(checkpoint.created_at)}</td>
                      <td className="mono tiny truncate" title={checkpoint.path}>
                        {checkpoint.path}
                      </td>
                      <td>
                        <Link to={`/tournaments?${key}=${encodeURIComponent(checkpoint.path)}`}>Evaluate</Link>
                        {" · "}
                        <Link to="/replays">Replay</Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
