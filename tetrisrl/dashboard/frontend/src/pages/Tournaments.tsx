import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { AsyncState } from "../components/Panels";
import StatusBadge from "../components/StatusBadge";
import { formatDate } from "../lib/format";

export default function Tournaments() {
  const { data, error, loading, refresh } = useAsync(() => api.tournaments(200), [], 5000);

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>Tournaments</h1>
          <p className="muted">Round-robin evaluations; each match stores a replay on disk.</p>
        </div>
        <div className="header-actions">
          <Link className="btn btn-primary" to="/tournaments/new">
            New tournament
          </Link>
          <button className="btn" type="button" onClick={refresh}>
            Refresh
          </button>
        </div>
      </header>

      <div className="panel">
        <div className="panel-row">
          <h2>History</h2>
          <span className="tiny muted">{data?.tournaments.length ?? 0} tournaments</span>
        </div>
        <AsyncState error={error} loading={loading && !data} onRetry={refresh} />
        {data && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Tournament</th>
                  <th>Status</th>
                  <th className="num">Participants</th>
                  <th>Winner</th>
                  <th>Created</th>
                  <th className="num">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.tournaments.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted">
                      No tournaments yet. Create one to compare engines and checkpoints.
                    </td>
                  </tr>
                )}
                {data.tournaments.map((tournament) => {
                  const standings = tournament.results?.standings ?? [];
                  const winner = standings[0]?.participant;
                  return (
                    <tr key={tournament.id}>
                      <td>
                        <Link to={`/tournaments/${encodeURIComponent(tournament.id)}`}>{tournament.name}</Link>
                        <div className="tiny muted mono">{tournament.id}</div>
                      </td>
                      <td>
                        <StatusBadge status={tournament.status} />
                      </td>
                      <td className="num">{tournament.config.participants?.length ?? 0}</td>
                      <td>{winner ?? "—"}</td>
                      <td className="tiny">{formatDate(tournament.created_at)}</td>
                      <td className="num">
                        <button
                          className="btn btn-danger btn-sm"
                          type="button"
                          onClick={async () => {
                            if (
                              !window.confirm(
                                `Delete tournament "${tournament.name}"? Its matches and replays are removed permanently.`,
                              )
                            )
                              return;
                            try {
                              await api.deleteTournament(tournament.id);
                              refresh();
                            } catch (err) {
                              window.alert(err instanceof Error ? err.message : String(err));
                            }
                          }}
                        >
                          Delete
                        </button>
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
