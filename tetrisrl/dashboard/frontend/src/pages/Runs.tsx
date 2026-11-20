import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { AsyncState } from "../components/Panels";
import StatusBadge from "../components/StatusBadge";
import { formatDate, formatNumber } from "../lib/format";

export default function Runs() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [algorithm, setAlgorithm] = useState(searchParams.get("algorithm") ?? "");
  const [status, setStatus] = useState(searchParams.get("status") ?? "");

  const { data, error, loading, refresh } = useAsync(
    () => api.runs({ algorithm: algorithm || undefined, status: status || undefined, limit: 500 }),
    [algorithm, status],
    4000,
  );

  const [form, setForm] = useState({
    algorithm: "ppo",
    seed: "0",
    timesteps: "100000",
    notes: "",
    name: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const runs = useMemo(() => data?.runs ?? [], [data]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    setNotice(null);
    try {
      const response = await api.startRun({
        algorithm: form.algorithm,
        seed: Number(form.seed) || 0,
        timesteps: Number(form.timesteps) || undefined,
        notes: form.notes,
        name: form.name || undefined,
      });
      if (response.spawned) {
        navigate(`/runs/${encodeURIComponent(response.run.id)}`);
      } else {
        setNotice(response.error ?? "The run record was created but no training process was spawned.");
        refresh();
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section>
      <header className="page-header">
        <div>
          <h1>Runs</h1>
          <p className="muted">Every run is persisted in SQLite; training processes are supervised.</p>
        </div>
        <button className="btn" type="button" onClick={refresh}>
          Refresh
        </button>
      </header>

      <div className="panel">
        <h2>Start a new run</h2>
        <form className="form-grid" onSubmit={submit}>
          <label>
            Algorithm
            <select value={form.algorithm} onChange={(event) => setForm({ ...form, algorithm: event.target.value })}>
              <option value="ppo">PPO</option>
              <option value="dqn">Double DQN</option>
            </select>
          </label>
          <label>
            Seed
            <input
              type="number"
              value={form.seed}
              onChange={(event) => setForm({ ...form, seed: event.target.value })}
            />
          </label>
          <label>
            Timesteps
            <input
              type="number"
              min={1}
              value={form.timesteps}
              onChange={(event) => setForm({ ...form, timesteps: event.target.value })}
            />
          </label>
          <label>
            Name <span className="muted tiny">(optional)</span>
            <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>
          <label className="form-wide">
            Notes
            <textarea
              rows={2}
              value={form.notes}
              placeholder="Hypothesis, config changes, expected outcome…"
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
            />
          </label>
          <div className="form-actions form-wide">
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting ? "Starting…" : "Start run"}
            </button>
            {formError && <span className="form-error">{formError}</span>}
            {notice && <span className="form-notice">{notice}</span>}
          </div>
        </form>
      </div>

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
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">
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
                    <td className="num">{formatNumber(run.total_timesteps)}</td>
                    <td className="nowrap tiny">{formatDate(run.created_at)}</td>
                    <td className="truncate" title={run.notes ?? ""}>
                      {run.notes || "—"}
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
