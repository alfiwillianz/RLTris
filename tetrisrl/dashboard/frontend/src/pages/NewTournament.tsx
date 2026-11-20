import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";

interface Entry {
  id: string;
  label: string;
  kind: "baseline" | "external" | "checkpoint";
  available: boolean;
  detail?: string | null;
  algorithm?: string;
  timestep?: number;
  run_id?: string;
  win_rate?: number | null;
}

const ENGINE_META: Record<string, { icon: string; blurb: string; tag?: string }> = {
  coldclear: { icon: "CC", blurb: "TBP placement oracle, strongest verified engine." },
  riku: { icon: "RI", blurb: "Fast zero-dependency TBP beam search.", tag: "fast" },
  coldclear1: { icon: "C1", blurb: "C ABI engine, garbage-aware.", tag: "garbage-aware" },
  nana: { icon: "NA", blurb: "Parallel MCTS with opponent model.", tag: "garbage-aware" },
  hikari: { icon: "HK", blurb: "TBP engine with a 24-row board." },
  blockfish: { icon: "BF", blurb: "Cheese specialist; not a versus benchmark.", tag: "specialist" },
  frostetra: { icon: "FR", blurb: "SBP engine claiming SRS+/180.", tag: "SRS+" },
  random: { icon: "R", blurb: "Uniform legal placements." },
  heuristic: { icon: "H", blurb: "One-ply Dellacherie-style evaluation." },
  search: { icon: "B", blurb: "Multi-ply beam search." },
};

function specLabel(options: Entry[], id: string): string {
  return options.find((option) => option.id === id)?.label ?? id;
}

export default function NewTournament() {
  const navigate = useNavigate();
  const { data, error, loading } = useAsync(() => api.participants(), [], 30000);
  const [name, setName] = useState("Round-robin tournament");
  const [seeds, setSeeds] = useState("1");
  const [maxPieces, setMaxPieces] = useState("400");
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const builtin = data?.builtin ?? [];
  const checkpoints = data?.checkpoints ?? [];
  const allOptions: Entry[] = useMemo(() => [...builtin, ...checkpoints], [builtin, checkpoints]);

  const filteredCheckpoints = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = checkpoints.filter((option) => option.available);
    if (!needle) return list.slice(0, 40);
    return list
      .filter((option) =>
        `${option.label} ${option.run_id ?? ""} ${option.algorithm ?? ""} ${option.timestep ?? ""}`
          .toLowerCase()
          .includes(needle),
      )
      .slice(0, 60);
  }, [checkpoints, query]);

  const toggle = (id: string) => {
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };

  const matches = useMemo(() => {
    const n = selected.length;
    const s = Math.max(1, Number(seeds) || 1);
    return n < 2 ? 0 : ((n * (n - 1)) / 2) * s;
  }, [selected.length, seeds]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setFormError(null);
    if (selected.length < 2) {
      setFormError("Pick at least two participants (engines and/or checkpoints).");
      return;
    }
    const seedCount = Number(seeds);
    const pieces = Number(maxPieces);
    if (!Number.isFinite(seedCount) || seedCount < 1) {
      setFormError("Seeds must be a positive integer.");
      return;
    }
    if (!Number.isFinite(pieces) || pieces < 1) {
      setFormError("Max pieces must be a positive integer.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await api.createTournament({
        name: name || "Round-robin tournament",
        participants: selected,
        seeds: seedCount,
        max_pieces: pieces,
      });
      navigate(`/tournaments/${encodeURIComponent(response.tournament.id)}`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const renderCard = (option: Entry) => {
    const selectedNow = selected.includes(option.id);
    const meta = ENGINE_META[option.id] ?? { icon: option.algorithm?.toUpperCase() ?? "PT", blurb: "" };
    return (
      <button
        key={option.id}
        type="button"
        className={`opponent-card${selectedNow ? " selected" : ""}${!option.available ? " unavailable" : ""}`}
        onClick={() => option.available && toggle(option.id)}
        aria-pressed={selectedNow}
        disabled={!option.available}
      >
        <span className="opponent-icon">{meta.icon}</span>
        <span className="opponent-body">
          <span className="opponent-name">{option.label}</span>
          {meta.blurb && <span className="opponent-blurb">{meta.blurb}</span>}
          <span className="opponent-meta">
            {option.kind === "checkpoint" ? (
              <>
                <span className={`speed speed-${option.algorithm === "ppo" ? "fast" : "mid"}`}>
                  {option.algorithm?.toUpperCase()}
                </span>
                <span className="tag">step {option.timestep?.toLocaleString()}</span>
                {option.win_rate != null && <span className="tag">win {(option.win_rate * 100).toFixed(0)}%</span>}
              </>
            ) : (
              <span className="tag">{option.kind === "external" ? "external engine" : "baseline"}</span>
            )}
            {!option.available && <span className="tag tag-warn">not available</span>}
          </span>
        </span>
        <span className="opponent-check">{selectedNow ? "✓" : ""}</span>
      </button>
    );
  };

  return (
    <section className="new-run-page">
      <div className="breadcrumb">
        <Link to="/tournaments">Tournaments</Link> <span className="crumb-sep">/</span> <span>New tournament</span>
      </div>
      <header className="page-header hero">
        <div>
          <h1>Create a tournament</h1>
          <p className="muted">Round robin across engines and checkpoints; every match stores a replay.</p>
        </div>
        <div className="hero-badge">{matches} scheduled matches</div>
      </header>

      <form onSubmit={submit}>
        <div className="run-layout">
          <div className="run-main">
            <div className="panel step-card">
              <div className="step-heading">
                <span className="step-index">1</span>
                <div>
                  <h2>Engines</h2>
                  <p className="tiny muted">Built external engines and in-repo baselines.</p>
                </div>
              </div>
              {error && <div className="form-error">{error}</div>}
              {loading && !data && <div className="empty-note">Loading participants…</div>}
              <div className="opponent-section-label">External engines</div>
              <div className="opponent-grid">
                {builtin.filter((option) => option.kind === "external").map(renderCard)}
              </div>
              <div className="opponent-section-label">Baselines</div>
              <div className="opponent-grid">{builtin.filter((option) => option.kind === "baseline").map(renderCard)}</div>
            </div>

            <div className="panel step-card">
              <div className="step-heading">
                <span className="step-index">2</span>
                <div>
                  <h2>Trained checkpoints</h2>
                  <p className="tiny muted">Search runs by name, algorithm, step or checkpoint path.</p>
                </div>
                <span className="selection-count">{checkpoints.filter((c) => c.available).length} available</span>
              </div>
              <input
                className="search-input"
                type="search"
                placeholder="Search checkpoints — run id, PPO/DQN, step…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              {filteredCheckpoints.length === 0 ? (
                <div className="empty-note">
                  {checkpoints.length === 0 ? "No checkpoints yet — train a run first." : "No checkpoint matches the search."}
                </div>
              ) : (
                <div className="checkpoint-grid">{filteredCheckpoints.map(renderCard)}</div>
              )}
            </div>

            <div className="panel step-card">
              <div className="step-heading">
                <span className="step-index">3</span>
                <div>
                  <h2>Schedule</h2>
                  <p className="tiny muted">Matches per pairing and the piece cap per match.</p>
                </div>
              </div>
              <div className="form-grid">
                <label className="form-wide">
                  Name
                  <input value={name} onChange={(event) => setName(event.target.value)} />
                </label>
                <label>
                  Seeds (matches per pairing)
                  <input type="number" min={1} value={seeds} onChange={(event) => setSeeds(event.target.value)} />
                </label>
                <label>
                  Max pieces per match
                  <input
                    type="number"
                    min={1}
                    value={maxPieces}
                    onChange={(event) => setMaxPieces(event.target.value)}
                  />
                </label>
              </div>
            </div>
          </div>

          <aside className="run-side">
            <div className="panel estimate-card">
              <h2>Line-up</h2>
              <p className="tiny muted">Click cards on the left to add or remove participants.</p>
              <div className="estimate-hero" key={selected.length}>
                <span className="estimate-value">{selected.length}</span>
                <span className="estimate-label">participants · {matches} matches</span>
              </div>
              <div className="chips">
                {selected.length === 0 && <span className="tiny muted">Nothing selected yet.</span>}
                {selected.map((id) => (
                  <span className="chip" key={id}>
                    {specLabel(allOptions, id)}
                    <button type="button" aria-label={`remove ${specLabel(allOptions, id)}`} onClick={() => toggle(id)}>
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
                {submitting ? "Starting…" : "Run tournament"}
              </button>
              <Link className="btn btn-block" to="/tournaments">
                Cancel
              </Link>
              {formError && <div className="form-error">{formError}</div>}
            </div>
          </aside>
        </div>
      </form>
    </section>
  );
}
