import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { AsyncState } from "../components/Panels";
import { formatDate, formatNumber, winnerLabel } from "../lib/format";

export default function Replays() {
  const { data, error, loading, refresh } = useAsync(() => api.replays(500), [], 10000);
  const [query, setQuery] = useState("");

  const replays = useMemo(() => {
    const all = data?.replays ?? [];
    const needle = query.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((replay) =>
      [replay.id, replay.agent_a, replay.agent_b, replay.tournament_id ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [data, query]);

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>Replays</h1>
          <p className="muted">Recorded matches; playback uses only stored frames, ticks, and board bitmasks.</p>
        </div>
        <button className="btn" type="button" onClick={refresh}>
          Refresh
        </button>
      </header>

      <div className="panel">
        <div className="panel-row">
          <h2>Matches</h2>
          <input
            className="search-input"
            placeholder="filter by match, agent, tournament…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <AsyncState error={error} loading={loading && !data} onRetry={refresh} />
        {data && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Match</th>
                  <th>Tournament</th>
                  <th>A</th>
                  <th>B</th>
                  <th>Result</th>
                  <th className="num">Seed</th>
                  <th className="num">Ticks</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {replays.length === 0 && (
                  <tr>
                    <td colSpan={9} className="muted">
                      No replays recorded yet. Run a tournament to create one.
                    </td>
                  </tr>
                )}
                {replays.map((replay) => (
                  <tr key={replay.id}>
                    <td className="mono">{replay.id}</td>
                    <td>
                      {replay.tournament_id ? (
                        <Link to={`/tournaments/${encodeURIComponent(replay.tournament_id)}`}>
                          {replay.tournament_id}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="mono">{replay.agent_a}</td>
                    <td className="mono">{replay.agent_b}</td>
                    <td>{winnerLabel(replay.winner)}</td>
                    <td className="num">{replay.seed}</td>
                    <td className="num">{formatNumber(replay.ticks)}</td>
                    <td className="tiny">{formatDate(replay.created_at)}</td>
                    <td>
                      {replay.available ? (
                        <Link to={`/replays/${encodeURIComponent(replay.id)}`}>Watch</Link>
                      ) : (
                        <span className="muted tiny">file missing</span>
                      )}
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
