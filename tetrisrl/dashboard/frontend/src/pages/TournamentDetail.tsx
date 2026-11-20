import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { AsyncState } from "../components/Panels";
import StatusBadge from "../components/StatusBadge";
import { formatDate, formatNumber, winnerLabel } from "../lib/format";

export default function TournamentDetail() {
  const navigate = useNavigate();
  const { tournamentId = "" } = useParams();
  const { data, error, loading, refresh } = useAsync(
    () => api.tournament(tournamentId),
    [tournamentId],
    2000,
  );

  const tournament = data?.tournament;
  const matches = data?.matches ?? [];
  const results = tournament?.results ?? null;
  const standings = results?.standings ?? [];
  const limitations = [
    ...(tournament?.config.limitations ?? []),
    ...(results?.limitations ?? []),
  ].filter((item, index, array) => array.indexOf(item) === index);
  const failures = results?.failures ?? [];

  return (
    <section>
      <div className="breadcrumb">
        <Link to="/tournaments">Tournaments</Link> / <span className="mono">{tournamentId}</span>
      </div>
      <header className="page-header">
        <div>
          <h1>{tournament?.name ?? tournamentId}</h1>
          <p className="muted mono">{tournamentId}</p>
        </div>
        <div className="header-actions">
          {tournament && <StatusBadge status={tournament.status} />}
          <button className="btn" type="button" onClick={refresh}>
            Refresh
          </button>
          <a className="btn" href={api.tournamentCsvUrl(tournamentId)}>
            Download CSV
          </a>
          <button
            className="btn btn-danger"
            type="button"
            onClick={async () => {
              if (!window.confirm(`Delete tournament "${tournamentId}"? Its matches and replays are removed permanently.`)) return;
              try {
                await api.deleteTournament(tournamentId);
                navigate("/tournaments");
              } catch (err) {
                window.alert(err instanceof Error ? err.message : String(err));
              }
            }}
          >
            Delete
          </button>
        </div>
      </header>

      <AsyncState error={error} loading={loading && !data} onRetry={refresh} />

      {tournament && (
        <>
          <div className="panel">
            <div className="kv-grid">
              <div>
                <span className="muted">Status</span>
                <div>
                  <StatusBadge status={tournament.status} />
                </div>
              </div>
              <div>
                <span className="muted">Created</span>
                <div className="tiny">{formatDate(tournament.created_at)}</div>
              </div>
              <div>
                <span className="muted">Participants</span>
                <div className="tiny mono">
                  {(tournament.config.participants ?? []).join(", ") || "—"}
                </div>
              </div>
              <div>
                <span className="muted">Seeds</span>
                <div className="tiny mono">
                  {(tournament.config.seeds ?? []).join(", ") || "—"}
                </div>
              </div>
              <div>
                <span className="muted">Max pieces</span>
                <div className="tiny mono">{tournament.config.max_pieces ?? "—"}</div>
              </div>
              <div>
                <span className="muted">Matches</span>
                <div className="tiny mono">{matches.length}</div>
              </div>
            </div>
            {tournament.status === "running" && (
              <p className="muted tiny">Matches are running in a background thread; this page refreshes every 2s.</p>
            )}
            {results?.error && <p className="form-error mono">{results.error}</p>}
          </div>

          {results?.error ? null : (
            <div className="panel">
              <h2>Standings</h2>
              {standings.length === 0 ? (
                <p className="muted">{tournament.status === "running" ? "Waiting for first match…" : "No standings recorded."}</p>
              ) : (
                <div className="table-scroll">
                  <table className="table">
                    <thead>
                      <tr>
                        <th className="num">Rank</th>
                        <th>Participant</th>
                        <th className="num">Matches</th>
                        <th className="num">W</th>
                        <th className="num">L</th>
                        <th className="num">D</th>
                        <th className="num">Points</th>
                        <th className="num">Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {standings.map((row) => (
                        <tr key={row.participant}>
                          <td className="num">{row.rank}</td>
                          <td className="mono">{row.participant}</td>
                          <td className="num">{row.matches}</td>
                          <td className="num">{row.wins}</td>
                          <td className="num">{row.losses}</td>
                          <td className="num">{row.draws}</td>
                          <td className="num">{row.points}</td>
                          <td className="num">{row.score === null ? "—" : row.score.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div className="panel">
            <div className="panel-row">
              <h2>Matches</h2>
              <span className="tiny muted">{matches.length} recorded</span>
            </div>
            {matches.length === 0 ? (
              <p className="muted">No matches recorded yet.</p>
            ) : (
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Match</th>
                      <th>Seed</th>
                      <th>A</th>
                      <th>B</th>
                      <th>Result</th>
                      <th>Reason</th>
                      <th className="num">Ticks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {matches.map((match) => (
                      <tr key={match.id}>
                        <td>
                          <Link to={`/replays/${encodeURIComponent(match.id)}`} className="mono">
                            {match.id}
                          </Link>
                        </td>
                        <td className="num">{match.seed}</td>
                        <td className="mono">{match.agent_a}</td>
                        <td className="mono">{match.agent_b}</td>
                        <td>{winnerLabel(match.winner)}</td>
                        <td className="tiny">{match.reason}</td>
                        <td className="num">{formatNumber(match.ticks)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {(limitations.length > 0 || failures.length > 0) && (
            <div className="panel">
              <h2>Limitations &amp; failures</h2>
              {limitations.length > 0 && (
                <>
                  <h3>Limitations</h3>
                  <ul className="plain-list">
                    {limitations.map((item) => (
                      <li key={item} className="tiny">
                        {item}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {failures.length > 0 && (
                <>
                  <h3>Failed matches</h3>
                  <ul className="plain-list">
                    {failures.map((item) => (
                      <li key={item} className="tiny form-error">
                        {item}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
