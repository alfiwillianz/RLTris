import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { AsyncState } from "../components/Panels";
import StatusBadge from "../components/StatusBadge";
import { formatMetric, formatNumber, formatTimesteps } from "../lib/format";

function StatCard({
  label,
  value,
  hint,
  to,
}: {
  label: string;
  value: string | number;
  hint?: string;
  to?: string;
}) {
  const body = (
    <>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </>
  );
  return to ? (
    <Link className="stat-card stat-card-link" to={to}>
      {body}
    </Link>
  ) : (
    <div className="stat-card">{body}</div>
  );
}

export default function Overview() {
  const { data, error, loading, refresh } = useAsync(() => api.overview(), [], 5000);

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>Overview</h1>
          <p className="muted">Persistent experiment state, read from SQLite on every visit.</p>
        </div>
        <button className="btn" type="button" onClick={refresh}>
          Refresh
        </button>
      </header>

      <AsyncState error={error} loading={loading && !data} onRetry={refresh} />
      {data && (
        <>
          <div className="stat-grid">
            <StatCard label="Total runs" value={formatNumber(data.total_runs)} to="/runs" />
            <StatCard
              label="Active"
              value={formatNumber(data.active_runs)}
              hint={`${formatNumber(data.completed_runs)} completed · ${formatNumber(data.failed_runs)} failed`}
            />
            <StatCard label="Total timesteps" value={formatTimesteps(data.total_timesteps)} />
            <StatCard
              label="Algorithms"
              value={Object.keys(data.by_algorithm).length}
              hint={Object.entries(data.by_algorithm)
                .map(([algorithm, count]) => `${algorithm}: ${count}`)
                .join(" · ")}
            />
            <StatCard
              label="Best checkpoint"
              value={data.best ? data.best.algorithm.toUpperCase() : "—"}
              hint={data.best?.id ?? "No checkpoint recorded yet"}
              to={data.best ? `/runs/${encodeURIComponent(data.best.id)}` : undefined}
            />
            <StatCard
              label="Latest tournament"
              value={data.latest_tournament?.name ?? "—"}
              hint={data.latest_tournament?.status ?? "No tournament yet"}
              to={
                data.latest_tournament
                  ? `/tournaments/${encodeURIComponent(data.latest_tournament.id)}`
                  : undefined
              }
            />
          </div>

          <div className="grid-two">
            <div className="panel">
              <h2>Algorithm breakdown</h2>
              {Object.keys(data.by_algorithm).length === 0 ? (
                <p className="muted">No runs yet. Start one from the Runs page.</p>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Algorithm</th>
                      <th className="num">Runs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.by_algorithm).map(([algorithm, count]) => (
                      <tr key={algorithm}>
                        <td>
                          <Link to={`/runs?algorithm=${encodeURIComponent(algorithm)}`}>{algorithm}</Link>
                        </td>
                        <td className="num">{count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="panel">
              <h2>Latest evaluations</h2>
              {Object.keys(data.latest_evaluations).length === 0 ? (
                <p className="muted">No evaluation metrics logged yet.</p>
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Algorithm</th>
                      <th>Run</th>
                      <th className="num">Win rate</th>
                      <th className="num">Timestep</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(data.latest_evaluations).map(([algorithm, evaluation]) => (
                      <tr key={algorithm}>
                        <td className="mono">{algorithm}</td>
                        <td>
                          <Link to={`/runs/${encodeURIComponent(evaluation.run_id)}`}>
                            {evaluation.run_id}
                          </Link>
                        </td>
                        <td className="num">{formatMetric(evaluation.value, 3)}</td>
                        <td className="num">{formatNumber(evaluation.timestep)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {data.latest_tournament && (
            <div className="panel">
              <div className="panel-row">
                <h2>Latest tournament</h2>
                <StatusBadge status={data.latest_tournament.status} />
              </div>
              <p>
                <Link to={`/tournaments/${encodeURIComponent(data.latest_tournament.id)}`}>
                  {data.latest_tournament.name}
                </Link>{" "}
                <span className="muted tiny">created {data.latest_tournament.created_at}</span>
              </p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
