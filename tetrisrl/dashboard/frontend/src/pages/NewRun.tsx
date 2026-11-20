import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";

interface OpponentMeta {
  id: string;
  label: string;
  group: "solo" | "baseline" | "external";
  msPerMove: number;
  blurb: string;
  icon: string;
  tag?: string;
}

const BASE_OPPONENTS: OpponentMeta[] = [
  {
    id: "none",
    label: "Solo / survival",
    group: "solo",
    msPerMove: 0,
    blurb: "No opponent; the agent learns board management and survival pressure only.",
    icon: "◎",
    tag: "no attacks",
  },
  {
    id: "random",
    label: "Random placements",
    group: "baseline",
    msPerMove: 0.1,
    blurb: "Uniform legal placements. Fast and erratic; useful for early curriculum.",
    icon: "R",
  },
  {
    id: "heuristic",
    label: "Handcrafted heuristic",
    group: "baseline",
    msPerMove: 6,
    blurb: "Dellacherie-style one-ply evaluation with competitive terms.",
    icon: "H",
    tag: "consistent",
  },
  {
    id: "search",
    label: "Beam search",
    group: "baseline",
    msPerMove: 80,
    blurb: "Multi-ply beam search over placements; the strongest in-repo baseline.",
    icon: "B",
    tag: "slow",
  },
  {
    id: "variant",
    label: "Seeded variants",
    group: "baseline",
    msPerMove: 35,
    blurb: "Jittered heuristic weights, evaluation noise and randomised search per episode.",
    icon: "V",
    tag: "anti-overfit",
  },
];

const EXTERNAL_META: Record<string, { msPerMove: number; blurb: string; icon: string; tag?: string }> = {
  coldclear: { msPerMove: 62, blurb: "TBP placement oracle, strongest verified external engine.", icon: "CC" },
  riku: { msPerMove: 5, blurb: "Fast zero-dependency TBP beam search.", icon: "RI", tag: "fast" },
  coldclear1: { msPerMove: 42, blurb: "C ABI engine that receives pending garbage counts.", icon: "C1", tag: "garbage-aware" },
  nana: { msPerMove: 150, blurb: "Parallel MCTS with an opponent model and garbage meter.", icon: "NA", tag: "garbage-aware" },
  hikari: { msPerMove: 20, blurb: "TBP engine with a 24-row board view.", icon: "HK" },
  blockfish: { msPerMove: 45, blurb: "Cheese/downstack specialist — not a versus benchmark.", icon: "BF", tag: "specialist" },
  frostetra: { msPerMove: 300, blurb: "SBP engine claiming SRS+/180; slow search.", icon: "FR", tag: "SRS+" },
};

function humanize(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const hours = seconds / 3600;
  return hours < 10 ? `${hours.toFixed(1)}h` : `${Math.round(hours)}h`;
}

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
  const [mode, setMode] = useState<"rl" | "continue" | "pretrain">("rl");
  const [pretrain, setPretrain] = useState({
    epochs: "10",
    matchesPerPair: "2",
    bcEpochs: "2",
    batchSize: "256",
  });
  const [opponents, setOpponents] = useState<string[]>(["random", "heuristic"]);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [resumeSpec, setResumeSpec] = useState<string | null>(null);
  const [resumeOpen, setResumeOpen] = useState(false);
  const [resumeQuery, setResumeQuery] = useState("");
  const { data: participants } = useAsync(() => api.participants(), [], 30000);
  const resumeOptions = (participants?.checkpoints ?? []).filter(
    (option) => option.available && (option.algorithm ?? option.id.split(":")[0]) === form.algorithm,
  );
  const filteredResume = useMemo(() => {
    const needle = resumeQuery.trim().toLowerCase();
    if (!needle) return resumeOptions.slice(0, 60);
    return resumeOptions
      .filter((option) =>
        `${option.label} ${option.run_id ?? ""} ${option.timestep ?? ""}`.toLowerCase().includes(needle),
      )
      .slice(0, 80);
  }, [resumeOptions, resumeQuery]);
  const resumeOption = resumeSpec
    ? (participants?.checkpoints ?? []).find((option) => option.id === resumeSpec)
    : null;

  const externalOptions: OpponentMeta[] = useMemo(
    () =>
      (participants?.builtin ?? [])
        .filter((option) => option.kind === "external")
        .map((option) => {
          const meta = EXTERNAL_META[option.id] ?? { msPerMove: 100, blurb: "External engine.", icon: "??" };
          return {
            id: option.id,
            label: option.label,
            group: "external" as const,
            msPerMove: meta.msPerMove,
            blurb: meta.blurb,
            icon: meta.icon,
            tag: meta.tag,
            available: option.available,
          } as OpponentMeta & { available: boolean };
        }),
    [participants],
  );
  const allOptions = [...BASE_OPPONENTS, ...externalOptions];
  const selectedMeta = opponents.map((id) => allOptions.find((option) => option.id === id)).filter(Boolean) as OpponentMeta[];
  const selectedExternal = selectedMeta.filter((option) => option.group === "external");

  const isPretrain = mode === "pretrain";
  const estimate = useMemo(() => {
    const timesteps = Number(form.timesteps) || 0;
    const nEnvs = Math.max(1, Number(form.nEnvs) || 1);
    const agentMs = form.vecEnv === "batched" ? 0.5 : 1.6;
    const opponentMs = selectedMeta.length
      ? selectedMeta.reduce((sum, option) => sum + option.msPerMove, 0) / selectedMeta.length
      : 0;
    if (isPretrain) {
      const epochs = Math.max(1, Number(pretrain.epochs) || 1);
      const perPair = Math.max(1, Number(pretrain.matchesPerPair) || 1);
      const n = Math.max(1, selectedMeta.length);
      const pairs = n < 2 ? 1 : (n * (n - 1)) / 2;
      const matchesPerEpoch = pairs * perPair;
      const estimateTicks = 90;
      const collect = (epochs * matchesPerEpoch * estimateTicks * opponentMs) / 1000;
      const bc = epochs * Math.max(1, Number(pretrain.bcEpochs) || 1) * 1.5;
      return {
        stepsPerSec: (epochs * matchesPerEpoch) / Math.max(1, collect + bc),
        trainSeconds: collect,
        evalSeconds: bc,
        totalSeconds: collect + bc,
        throughputText: `${matchesPerEpoch} matches/epoch · ${pairs} pairing${pairs === 1 ? "" : "s"}`,
        timestepLabel: "Epochs",
        timestepValue: epochs,
      };
    }
    let stepsPerSec = 1000 / Math.max(0.1, agentMs + opponentMs);
    if (form.vecEnv === "subprocess") stepsPerSec *= Math.min(nEnvs, 8) * 0.85;
    if (form.vecEnv === "batched") stepsPerSec = 1800;
    const trainSeconds = timesteps / stepsPerSec;
    const evaluations = Math.floor(timesteps / 50000);
    const evalSeconds = evaluations * 25;
    return {
      stepsPerSec,
      trainSeconds,
      evalSeconds,
      totalSeconds: trainSeconds + evalSeconds,
      throughputText: `${Math.round(stepsPerSec).toLocaleString()} steps/s`,
      timestepLabel: "Timesteps",
      timestepValue: timesteps,
    };
  }, [form.timesteps, form.nEnvs, form.vecEnv, selectedMeta, isPretrain, pretrain.epochs, pretrain.matchesPerPair, pretrain.bcEpochs]);

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
    if (!isPretrain && (!Number.isFinite(timesteps) || timesteps < 1)) {
      setFormError("Timesteps must be a positive integer.");
      return;
    }
    if (isPretrain) {
      const epochs = Number(pretrain.epochs);
      const perPair = Number(pretrain.matchesPerPair);
      if (!Number.isFinite(epochs) || epochs < 1 || !Number.isFinite(perPair) || perPair < 1) {
        setFormError("Epochs and matches per pair must be positive integers.");
        return;
      }
    }
    if (opponents.length === 0) {
      setFormError("Pick at least one opponent (or Solo / survival).");
      return;
    }
    setSubmitting(true);
    try {
      const base = {
        algorithm: form.algorithm,
        seed: Number(form.seed) || 0,
        name: form.name || undefined,
        notes: form.notes,
        resume_checkpoint:
          mode === "continue" && resumeSpec ? resumeSpec.slice(resumeSpec.indexOf(":") + 1) : undefined,
      };
      const config = isPretrain
        ? {
            mode: "pretrain",
            max_pieces: Number(form.maxPieces) || 300,
            seed: Number(form.seed) || 0,
            pretrain: {
              epochs: Number(pretrain.epochs) || 1,
              matches_per_pair: Number(pretrain.matchesPerPair) || 1,
              bc_epochs: Number(pretrain.bcEpochs) || 1,
              batch_size: Number(pretrain.batchSize) || 256,
              opponents,
              max_pieces: Number(form.maxPieces) || 300,
              eval_every: Math.max(1, Math.round((Number(pretrain.epochs) || 1) / 4)),
            },
          }
        : {
            timesteps,
            n_envs: Number(form.nEnvs) || 8,
            vec_env: form.vecEnv,
            max_pieces: Number(form.maxPieces) || 300,
            curriculum: buildCurriculum(),
          };
      const response = await api.startRun({
        ...base,
        timesteps: isPretrain ? undefined : timesteps,
        config,
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

  const renderCard = (option: OpponentMeta & { available?: boolean }) => {
    const selected = opponents.includes(option.id);
    const unavailable = option.group === "external" && option.available === false;
    return (
      <button
        type="button"
        key={option.id}
        className={`opponent-card${selected ? " selected" : ""}${unavailable ? " unavailable" : ""}`}
        onClick={() => !unavailable && toggleOpponent(option.id)}
        aria-pressed={selected}
        disabled={unavailable}
      >
        <span className="opponent-icon">{option.icon}</span>
        <span className="opponent-body">
          <span className="opponent-name">{option.label}</span>
          <span className="opponent-blurb">{option.blurb}</span>
          <span className="opponent-meta">
            <span className={`speed speed-${option.msPerMove < 10 ? "fast" : option.msPerMove < 100 ? "mid" : "slow"}`}>
              {option.msPerMove === 0 ? "instant" : `~${option.msPerMove < 1 ? "<1" : option.msPerMove} ms/move`}
            </span>
            {option.tag && <span className="tag">{option.tag}</span>}
            {unavailable && <span className="tag tag-warn">not built</span>}
          </span>
        </span>
        <span className="opponent-check">{selected ? "✓" : ""}</span>
      </button>
    );
  };

  return (
    <section className="new-run-page">
      <div className="breadcrumb">
        <Link to="/runs">Runs</Link> <span className="crumb-sep">/</span> <span>New run</span>
      </div>
      <header className="page-header hero">
        <div>
          <h1>Launch an experiment</h1>
          <p className="muted">
            The run is persisted in SQLite immediately; training is supervised in the background and survives
            application restarts.
          </p>
        </div>
        <div className="hero-badge">PPO / Double DQN</div>
      </header>

      <form onSubmit={submit}>
        <div className="run-layout">
          <div className="run-main">
            <div className="panel step-card">
              <div className="step-heading">
                <span className="step-index">1</span>
                <div>
                  <h2>Algorithm and budget</h2>
                  <p className="tiny muted">What to train and how far to run it.</p>
                </div>
              </div>
              <div className="mode-grid">
                {[
                  { id: "rl", title: "From scratch", blurb: "Standard RL against the chosen opponents." },
                  { id: "continue", title: "Continue", blurb: "Fine-tune from a saved checkpoint." },
                  { id: "pretrain", title: "Pretrain (BC)", blurb: "Pairwise demos → winner-only cloning." },
                ].map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className={`mode-card${mode === option.id ? " selected" : ""}`}
                    onClick={() => setMode(option.id as typeof mode)}
                  >
                    <span className="mode-title">{option.title}</span>
                    <span className="mode-blurb">{option.blurb}</span>
                  </button>
                ))}
              </div>
              <div className="form-grid">
                <label>
                  Algorithm
                  <select
                    value={form.algorithm}
                    onChange={(event) => {
                      const algorithm = event.target.value;
                      setForm({ ...form, algorithm });
                      if (resumeSpec && !resumeSpec.startsWith(`${algorithm}:`)) setResumeSpec(null);
                    }}
                  >
                    <option value="ppo">PPO</option>
                    <option value="dqn">Double DQN</option>
                  </select>
                </label>
                <label>
                  Seed
                  <input type="number" value={form.seed} onChange={(event) => setForm({ ...form, seed: event.target.value })} />
                </label>
                {!isPretrain && (
                  <label>
                    Timesteps
                    <input
                      type="number"
                      min={1}
                      value={form.timesteps}
                      onChange={(event) => setForm({ ...form, timesteps: event.target.value })}
                    />
                  </label>
                )}
                <label>
                  Max pieces per episode
                  <input
                    type="number"
                    min={1}
                    value={form.maxPieces}
                    onChange={(event) => setForm({ ...form, maxPieces: event.target.value })}
                  />
                </label>
                {isPretrain ? (
                  <>
                    <label>
                      Epochs
                      <input
                        type="number"
                        min={1}
                        value={pretrain.epochs}
                        onChange={(event) => setPretrain({ ...pretrain, epochs: event.target.value })}
                      />
                    </label>
                    <label>
                      Matches per pair per epoch
                      <input
                        type="number"
                        min={1}
                        value={pretrain.matchesPerPair}
                        onChange={(event) => setPretrain({ ...pretrain, matchesPerPair: event.target.value })}
                      />
                    </label>
                    <label>
                      Cloning passes per epoch
                      <input
                        type="number"
                        min={1}
                        value={pretrain.bcEpochs}
                        onChange={(event) => setPretrain({ ...pretrain, bcEpochs: event.target.value })}
                      />
                    </label>
                    <label>
                      Batch size
                      <input
                        type="number"
                        min={1}
                        value={pretrain.batchSize}
                        onChange={(event) => setPretrain({ ...pretrain, batchSize: event.target.value })}
                      />
                    </label>
                  </>
                ) : (
                  <>
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
                  </>
                )}
              </div>
              {mode === "continue" && (
              <div className="resume-row">
                <div>
                  <div className="resume-title">Continue from a checkpoint</div>
                  <div className="tiny muted">
                    Load weights from an earlier run and keep this run's own id, budget and metrics.
                  </div>
                </div>
                {resumeOption ? (
                  <div className="resume-selected">
                    <span className="mono tiny">{resumeOption.label}</span>
                    <button className="btn btn-sm" type="button" onClick={() => setResumeOpen(true)}>
                      Change
                    </button>
                    <button className="btn btn-sm" type="button" onClick={() => setResumeSpec(null)}>
                      Remove
                    </button>
                  </div>
                ) : (
                  <button className="btn" type="button" onClick={() => setResumeOpen(true)}>
                    Select checkpoint
                  </button>
                )}
              </div>
              )}
            </div>

            <div className="panel step-card">
              <div className="step-heading">
                <span className="step-index">2</span>
                <div>
                  <h2>{isPretrain ? "Demo tournament pool" : "Pick opponents"}</h2>
                  <p className="tiny muted">
                    {isPretrain
                      ? "Matches are generated from these opponents every epoch; only winning trajectories are cloned."
                      : "One choice → single-stage curriculum. Several → sampled per episode."}
                  </p>
                </div>
                <span className="selection-count">{opponents.length} selected</span>
              </div>

              <div className="opponent-section-label">In-repo opponents</div>
              <div className="opponent-grid">{BASE_OPPONENTS.map(renderCard)}</div>

              <div className="opponent-section-label">
                External engines <span className="tiny muted">— built from source, placement suggesters only</span>
              </div>
              {externalOptions.length === 0 ? (
                <div className="empty-note">No external engines are available yet.</div>
              ) : (
                <div className="opponent-grid">{externalOptions.map(renderCard)}</div>
              )}

              {selectedExternal.length > 0 && (
                <div className="warning-banner">
                  <strong>Slow training warning:</strong> {selectedExternal.map((option) => option.label).join(", ")}{" "}
                  launch a separate search process per placement. Throughput drops sharply; use them for short
                  evaluations or fixed-opponent fine-tuning rather than long per-step training.
                </div>
              )}
              {form.vecEnv === "batched" && (
                <p className="tiny muted">
                  The batched backend always plays a random opponent and ignores this selection.
                </p>
              )}
            </div>

            <div className="panel step-card">
              <div className="step-heading">
                <span className="step-index">3</span>
                <div>
                  <h2>Metadata</h2>
                  <p className="tiny muted">Recorded with the run so results stay interpretable.</p>
                </div>
              </div>
              <div className="form-grid">
                <label className="form-wide">
                  Name <span className="muted tiny">(optional)</span>
                  <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
                </label>
                <label className="form-wide">
                  Notes
                  <textarea
                    rows={3}
                    value={form.notes}
                    placeholder="Hypothesis, config changes, expected outcome…"
                    onChange={(event) => setForm({ ...form, notes: event.target.value })}
                  />
                </label>
              </div>
            </div>
          </div>

          <aside className="run-side">
            <div className="panel estimate-card">
              <h2>Estimated cost</h2>
              <p className="tiny muted">Rough wall-clock estimate from opponent latency and backend.</p>
              <div className="estimate-hero" key={Math.round(estimate.totalSeconds)}>
                <span className="estimate-value">{humanize(estimate.totalSeconds)}</span>
                <span className="estimate-label">estimated training time</span>
              </div>
              <div className="estimate-meter">
                <span
                  className="estimate-meter-fill"
                  style={{ width: `${Math.min(100, 20 + Math.log10(Math.max(1, estimate.totalSeconds)) * 30)}%` }}
                />
              </div>
              <div className="kv-grid estimate-kv">
                <div>
                  <span className="muted">{isPretrain ? "Dataset" : "Throughput"}</span>
                  <div className="mono">{estimate.throughputText}</div>
                </div>
                <div>
                  <span className="muted">Training</span>
                  <div className="mono">{humanize(estimate.trainSeconds)}</div>
                </div>
                <div>
                  <span className="muted">{isPretrain ? "Cloning overhead" : "Evaluation overhead"}</span>
                  <div className="mono">{humanize(estimate.evalSeconds)}</div>
                </div>
                <div>
                  <span className="muted">{estimate.timestepLabel}</span>
                  <div className="mono">{estimate.timestepValue.toLocaleString()}</div>
                </div>
              </div>
              <div className="estimate-opponents">
                {selectedMeta.length === 0 && <span className="tiny muted">No opponent selected.</span>}
                {selectedMeta.map((option) => (
                  <span className="mini-chip" key={option.id}>
                    {option.label}
                  </span>
                ))}
              </div>
              <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
                {submitting ? "Starting…" : "Start run"}
              </button>
              <Link className="btn btn-block" to="/runs">
                Cancel
              </Link>
              {formError && <div className="form-error">{formError}</div>}
            </div>
          </aside>
        </div>
      </form>

      {resumeOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Select checkpoint" onClick={() => setResumeOpen(false)}>
          <div className="modal panel" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h2>Continue from checkpoint</h2>
                <p className="tiny muted">
                  Showing {form.algorithm.toUpperCase()} checkpoints only. The new run records its own id,
                  seed, budget and metrics.
                </p>
              </div>
              <button className="btn" type="button" onClick={() => setResumeOpen(false)}>
                Close
              </button>
            </div>
            <input
              className="search-input"
              type="search"
              autoFocus
              placeholder="Search by run id or step…"
              value={resumeQuery}
              onChange={(event) => setResumeQuery(event.target.value)}
            />
            {filteredResume.length === 0 ? (
              <div className="empty-note">
                {resumeOptions.length === 0
                  ? `No ${form.algorithm.toUpperCase()} checkpoints yet — train a run first.`
                  : "No checkpoint matches the search."}
              </div>
            ) : (
              <div className="checkpoint-grid">
                {filteredResume.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className={`opponent-card${resumeSpec === option.id ? " selected" : ""}`}
                    onClick={() => {
                      setResumeSpec(option.id);
                      setResumeOpen(false);
                    }}
                  >
                    <span className="opponent-icon">{option.algorithm?.toUpperCase() ?? "PT"}</span>
                    <span className="opponent-body">
                      <span className="opponent-name">{option.label}</span>
                      <span className="opponent-meta">
                        <span className="tag">step {option.timestep?.toLocaleString()}</span>
                        {option.win_rate != null && <span className="tag">win {(option.win_rate * 100).toFixed(0)}%</span>}
                      </span>
                    </span>
                    <span className="opponent-check">{resumeSpec === option.id ? "✓" : ""}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
