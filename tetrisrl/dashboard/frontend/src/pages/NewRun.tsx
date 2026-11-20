import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";

const TRAINING_OPPONENTS = [
  { id: "none", label: "Solo / survival (no opponent)" },
  { id: "random", label: "Random legal placements" },
  { id: "heuristic", label: "Handcrafted heuristic" },
  { id: "search", label: "Beam search (multi-ply)" },
  { id: "variant", label: "Seeded variants (mixed weights/search)" },
];

export default function NewRun() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    algorithm: "ppo",
    seed: "0",
    timesteps: "100000",
    maxPieces: "300",
    nEnvs: "8",
    vecEnv: "dummy",
    name: "",
    notes: "",
  });
  const [opponents, setOpponents] = useState<string[]>(["random", "heuristic"]);
  const { data: participants } = useAsync(() => api.participants(), [], 30000);
  const externalEngines = (participants?.builtin ?? []).filter((option) => option.kind === "external");
  const selectedExternal = opponents.filter((id) => externalEngines.some((option) => option.id === id));
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const toggleOpponent = (id: string) => {
    setOpponents((current) => {
      if (id === "none") return current.includes("none") ? [] : ["none"];
      const withoutNone = current.filter((item) => item !== "none");
      return withoutNone.includes(id) ? withoutNone.filter((item) => item !== id) : [...withoutNone, id];
    });
  };

  const buildCurriculum = () => {
    const timesteps = Number(form.timesteps);
    const maxPieces = Number(form.maxPieces);
    if (opponents.length === 1 && opponents[0] === "none") {
      return [{ name: "custom_solo", timesteps, opponent: "none", max_pieces: maxPieces }];
    }
    if (opponents.length === 1) {
      return [{ name: "custom_opponent", timesteps, opponent: opponents[0], max_pieces: maxPieces }];
    }
    return [{ name: "custom_mixed", timesteps, opponent: "mixed", opponents, max_pieces: maxPieces }];
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const timesteps = Number(form.timesteps);
    if (!Number.isFinite(timesteps) || timesteps < 1) {
      setFormError("Timesteps must be a positive integer.");
      return;
    }
    if (opponents.length === 0) {
      setFormError("Pick at least one opponent (or Solo / survival).");
      return;
    }
    setSubmitting(true);
    try {
      const response = await api.startRun({
        algorithm: form.algorithm,
        seed: Number(form.seed) || 0,
        timesteps,
        name: form.name || undefined,
        notes: form.notes,
        config: {
          timesteps,
          n_envs: Number(form.nEnvs) || 8,
          vec_env: form.vecEnv,
          max_pieces: Number(form.maxPieces) || 300,
          curriculum: buildCurriculum(),
        },
      });
      if (response.spawned) {
        navigate(`/runs/${encodeURIComponent(response.run.id)}`);
      } else {
        setFormError(response.error ?? "The run record was created but no training process was spawned.");
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section>
      <div className="breadcrumb">
        <Link to="/runs">Runs</Link> / <span>New run</span>
      </div>
      <header className="page-header">
        <div>
          <h1>Start a new run</h1>
          <p className="muted">
            The run is recorded in SQLite immediately and a training process is supervised in the background.
          </p>
        </div>
      </header>

      <div className="panel">
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
            <input type="number" value={form.seed} onChange={(event) => setForm({ ...form, seed: event.target.value })} />
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
            Max pieces per episode
            <input
              type="number"
              min={1}
              value={form.maxPieces}
              onChange={(event) => setForm({ ...form, maxPieces: event.target.value })}
            />
          </label>
          <label>
            Parallel environments
            <input
              type="number"
              min={1}
              max={64}
              value={form.nEnvs}
              onChange={(event) => setForm({ ...form, nEnvs: event.target.value })}
            />
          </label>
          <label>
            Environment backend
            <select value={form.vecEnv} onChange={(event) => setForm({ ...form, vecEnv: event.target.value })}>
              <option value="dummy">In-process (reference engine)</option>
              <option value="subprocess">Subprocess workers (reference engine)</option>
              <option value="batched">Batched NumPy (random opponent)</option>
            </select>
          </label>
          <label className="form-wide">
            Name <span className="muted tiny">(optional)</span>
            <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>

          <fieldset className="form-wide participant-set">
            <legend>Training opponents</legend>
            <p className="tiny muted">
              Multiple selections are sampled per episode (mixed-opponent training). Solo disables the opponent.
            </p>
            {TRAINING_OPPONENTS.map((option) => (
              <label key={option.id} className="check">
                <input
                  type="checkbox"
                  checked={opponents.includes(option.id)}
                  onChange={() => toggleOpponent(option.id)}
                />
                {option.label}
              </label>
            ))}

            <div className="tiny muted" style={{ marginTop: "0.6rem", marginBottom: "0.2rem" }}>
              External engines (built from source, placement suggesters — arena owns the rules):
            </div>
            {externalEngines.length === 0 && (
              <p className="tiny muted">No external engines are available yet.</p>
            )}
            {externalEngines.map((option) => (
              <label key={option.id} className="check">
                <input
                  type="checkbox"
                  checked={opponents.includes(option.id)}
                  disabled={!option.available}
                  onChange={() => toggleOpponent(option.id)}
                />
                {option.label}
                {!option.available && <span className="tiny muted"> — not built</span>}
              </label>
            ))}

            {selectedExternal.length > 0 && (
              <div className="form-notice" style={{ marginTop: "0.6rem" }}>
                Slow training warning: {selectedExternal.join(", ")} run a separate search process per
                placement (milliseconds to seconds each). Episode throughput will drop sharply and short
                runs may not progress. Use external engines for short evaluations, tournaments, or
                fine-tuning against a fixed opponent — not for long per-step training.
              </div>
            )}
            {form.vecEnv === "batched" && (
              <p className="tiny muted">
                Note: the batched NumPy backend currently always plays a random opponent and ignores the
                selection above.
              </p>
            )}
          </fieldset>

          <label className="form-wide">
            Notes
            <textarea
              rows={3}
              value={form.notes}
              placeholder="Hypothesis, config changes, expected outcome…"
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
            />
          </label>

          <div className="form-actions form-wide">
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting ? "Starting…" : "Start run"}
            </button>
            <Link className="btn" to="/runs">
              Cancel
            </Link>
            {formError && <span className="form-error">{formError}</span>}
          </div>
        </form>
      </div>
    </section>
  );
}
