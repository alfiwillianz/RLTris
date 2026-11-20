import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { AsyncState } from "../components/Panels";
import StatusBadge from "../components/StatusBadge";
import { formatDate } from "../lib/format";
import type { ParticipantOption } from "../types";

const BUILTIN_PARTICIPANTS = ["random", "heuristic", "search"];

export default function Tournaments() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const ppoPrefill = searchParams.get("ppo") ?? "";
  const dqnPrefill = searchParams.get("dqn") ?? "";

  const { data, error, loading, refresh } = useAsync(() => api.tournaments(200), [], 5000);
  const { data: options } = useAsync(() => api.participants(), [], 15000);

  const [form, setForm] = useState({
    name: "Round-robin tournament",
    seeds: "1",
    maxPieces: "400",
  });
  const [selected, setSelected] = useState<string[]>(["random", "heuristic"]);
  const [picker, setPicker] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const allOptions: ParticipantOption[] = [
    ...(options?.builtin ?? []),
    ...(options?.checkpoints ?? []),
  ];
  const labelFor = (id: string) => allOptions.find((option) => option.id === id)?.label ?? id;

  const addParticipant = (id: string) => {
    if (!id) return;
    setSelected((current) => (current.includes(id) ? current : [...current, id]));
    setPicker("");
  };

  useEffect(() => {
    if (ppoPrefill) addParticipant(`ppo:${ppoPrefill}`);
    if (dqnPrefill) addParticipant(`dqn:${dqnPrefill}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ppoPrefill, dqnPrefill]);

  const removeParticipant = (id: string) => {
    setSelected((current) => current.filter((item) => item !== id));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (selected.length < 2) {
      setFormError("Pick at least two participants.");
      return;
    }
    const seeds = Number(form.seeds);
    const maxPieces = Number(form.maxPieces);
    if (!Number.isFinite(seeds) || seeds < 1) {
      setFormError("Seeds must be a positive integer.");
      return;
    }
    if (!Number.isFinite(maxPieces) || maxPieces < 1) {
      setFormError("Max pieces must be a positive integer.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await api.createTournament({
        name: form.name || "Round-robin tournament",
        participants: selected,
        seeds,
        max_pieces: maxPieces,
      });
      navigate(`/tournaments/${encodeURIComponent(response.tournament.id)}`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const coldclear = options?.builtin.find((option) => option.id === "coldclear");
  const checkpoints = options?.checkpoints ?? [];

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>Tournaments</h1>
          <p className="muted">Round-robin evaluations; each match stores a replay on disk.</p>
        </div>
        <button className="btn" type="button" onClick={refresh}>
          Refresh
        </button>
      </header>

      <div className="panel">
        <h2>New tournament</h2>
        <form className="form-grid" onSubmit={submit}>
          <label className="form-wide">
            Name
            <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>
          <fieldset className="form-wide participant-set">
            <legend>Participants</legend>
            <div className="picker-row">
              <select value={picker} onChange={(event) => setPicker(event.target.value)}>
                <option value="">Choose an opponent…</option>
                <optgroup label="External engine">
                  {(options?.builtin ?? [])
                    .filter((option) => option.kind === "external")
                    .map((option) => (
                      <option key={option.id} value={option.id} disabled={!option.available}>
                        {option.label}
                        {option.available ? "" : " — unavailable"}
                      </option>
                    ))}
                </optgroup>
                <optgroup label="Baselines">
                  {(options?.builtin ?? [])
                    .filter((option) => option.kind === "baseline")
                    .map((option) => (
                      <option key={option.id} value={option.id} disabled={!option.available}>
                        {option.label}
                      </option>
                    ))}
                </optgroup>
                <optgroup label="Trained checkpoints">
                  {checkpoints.length === 0 && <option disabled>no checkpoints yet</option>}
                  {checkpoints.map((option) => (
                    <option key={option.id} value={option.id} disabled={!option.available}>
                      {option.label}
                      {option.win_rate != null ? ` · win ${(option.win_rate * 100).toFixed(0)}%` : ""}
                    </option>
                  ))}
                </optgroup>
              </select>
              <button className="btn" type="button" onClick={() => addParticipant(picker)} disabled={!picker}>
                Add
              </button>
            </div>
            <div className="chips">
              {selected.length === 0 && <span className="tiny muted">No participants selected yet.</span>}
              {selected.map((id) => (
                <span className="chip" key={id}>
                  {labelFor(id)}
                  <button type="button" aria-label={`remove ${labelFor(id)}`} onClick={() => removeParticipant(id)}>
                    ×
                  </button>
                </span>
              ))}
            </div>
            <p className="tiny muted">
              Cold Clear 2:{" "}
              {coldclear?.available ? (
                <span className="status status-completed">available</span>
              ) : (
                <span className="status status-failed">not built</span>
              )}{" "}
              {!coldclear?.available && "— build third_party/cold-clear-2 or set TETRISRL_COLDCLEAR_BIN."}
            </p>
          </fieldset>
          <label>
            Seeds (matches per pairing)
            <input
              type="number"
              min={1}
              max={50}
              value={form.seeds}
              onChange={(event) => setForm({ ...form, seeds: event.target.value })}
            />
          </label>
          <label>
            Max pieces per match
            <input
              type="number"
              min={1}
              value={form.maxPieces}
              onChange={(event) => setForm({ ...form, maxPieces: event.target.value })}
            />
          </label>
          <div className="form-actions form-wide">
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting ? "Starting…" : "Run tournament"}
            </button>
            {formError && <span className="form-error">{formError}</span>}
          </div>
          <p className="form-wide tiny muted">
            Checkpoint participants need the evaluation tournament loader; if it is missing the run is
            recorded with a fallback agent and the limitation is stored in the tournament config.
          </p>
        </form>
      </div>

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
                      No tournaments yet.
                    </td>
                  </tr>
                )}
                {data.tournaments.map((tournament) => {
                  const standings = tournament.results?.standings ?? [];
                  const winner = standings[0]?.participant;
                  return (
                    <tr key={tournament.id}>
                      <td>
                        <Link to={`/tournaments/${encodeURIComponent(tournament.id)}`}>
                          {tournament.name}
                        </Link>
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
                            if (!window.confirm(`Delete tournament "${tournament.name}"? Its matches and replays are removed permanently.`)) return;
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
