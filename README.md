# TetrisRL — Competitive RL Arena (TETR.IO Season 2)

A reproducible research platform for asking one question:

> **Can reinforcement learning develop competitive Tetris strategies against
> established algorithmic opponents under TETR.IO Season 2 mechanics?**

It is not a Tetris clone with a neural network attached: the repository contains a
deterministic simulation of the verified Season 2 ruleset, two independent RL
implementations (PPO and Double DQN) that share exactly the same environment,
observation, action space and reward function, a local 1v1 arena with
deterministic replays, scripted baselines (random, handcrafted heuristic,
beam search), an adapter layer for external open-source engines, and a persistent
local web dashboard for long training runs.

## What is implemented

| Area | Contents |
|---|---|
| Ruleset | 10×40 board (20 hidden rows), SRS+ rotation with TETR.IO 180° kicks, seven-bag, hold, hard drop, 5 previews, spin detection (3-corner + mini), Season 2 attack table, combo multiplier, B2B charging + Surge, garbage queue/tank/cancellation with hole RNG, block-out/garbage-out, configurable lock-out |
| Arena | Deterministic simultaneous-tick 1v1, independent boards/bags/garbage RNGs, paired seeds, winner/draw handling, replay recording + hash verification |
| Agents | Uniform-random baseline, handcrafted heuristic (Dellacherie features), beam-search baseline (multi-ply), checkpoint policy agents, external-engine subprocess adapters |
| RL | Masked PPO (GAE, clipped objective, entropy, minibatches, grad clip, checkpointing) and Double DQN (replay buffer, target network, Double-Q targets, Huber loss, masked exploration) in PyTorch with automatic CUDA detection |
| Training | Config-driven curriculum, opponent schedules (solo/random/heuristic/search/mixed/self-play), vectorised envs (in-process and subprocess), periodic evaluation with confidence intervals, resume, graceful stop, SQLite metrics |
| Dashboard | FastAPI backend + React/TypeScript frontend, SQLite persistence, live training charts, algorithm comparison, tournaments, dual-board replay viewer with playback controls, checkpoint browser |
| Evaluation | Round-robin tournaments, CSV export, paired-seed evaluation, Wilson intervals, statistical summaries, reward/observation/ruleset ablations |
| Batched backend | NumPy placement/board core (24.7x reference on placement/board work, differential parity tests) plus a vectorised versus training env with SRS+ spin-in/detection and Season 2 scoring (~2.5k board-steps/s with spins, random opponent), selectable with `--vec-env batched` |
| External engine | Cold Clear 2 (pinned commit, built from source) driven over TBP; 20 real matches executed (10-0-0 vs heuristic, 10-0-0 vs random), 0.42% fallbacks. See `docs/BENCHMARKS_INTEGRATION.md` |
| Tests | 120+ automated tests covering board, geometry, kicks, spins, scoring, garbage, versus determinism, replays, observation, rewards, agents, PPO/DQN math, persistence and dashboard |

## Quick start

```bash
# 1. Environment (Python 3.10+; 3.12 recommended)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt

# 2. Verify mechanics before training
.venv/bin/python -m pytest tetrisrl/tests -q

# 3. Train
.venv/bin/python -m tetrisrl train --algorithm ppo --timesteps 200000
.venv/bin/python -m tetrisrl train --algorithm dqn --timesteps 200000

# 4. Evaluate a checkpoint
.venv/bin/python -m tetrisrl evaluate --algorithm ppo --matches 20 --opponents random,heuristic

# 5. Tournament (round robin, replays saved)
.venv/bin/python -m tetrisrl tournament --participants random,heuristic,search --seeds 4

# 6. Inspect a replay
.venv/bin/python -m tetrisrl replay --file results/replays/<match>.json --verify

# 7. Dashboard
.venv/bin/python -m tetrisrl dashboard --open
```

### CUDA notes

`torch` selects CUDA automatically. On Blackwell GPUs (RTX 50-series) install a
CUDA 12.8+ build, e.g.:

```bash
uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cu130
```

The training loops fall back to CPU when CUDA is unavailable. Simulation is
CPU-bound; the neural update is GPU-bound. See `docs/ARCHITECTURE.md` for the
environment/agent split.

## Repository layout

```
tetrisrl/
  environment/   deterministic simulation (no torch)
  agents/        random, heuristic, beam-search, policy wrapper, external adapters
  rl/            masked PPO and Double DQN, networks, replay buffer
  training/      curriculum, vectorised envs, checkpoints, run context, SQLite
  evaluation/    evaluator, tournaments, metrics, statistics, replays
  dashboard/     FastAPI backend, React/Vite frontend, built static assets
  tests/         pytest suite
configs/         experiment configurations
scripts/         benchmarking and experiment orchestration
docs/            RULESET, ARCHITECTURE, BENCHMARKS, EXPERIMENTS, REPRODUCIBILITY, DASHBOARD
results/         SQLite DB, runs, checkpoints, replays, logs (git-ignored)
```

## Research protocol

The platform supports the experiments specified by the project brief:

* **A. PPO vs Double DQN** — identical environment/observation/reward.
* **B. Reward shaping ablation** — board-penalty-free vs shaped reward.
* **C. Single- vs mixed-opponent training** — `configs/single_heuristic.json` vs
  `configs/mixed_opponents.json`.
* **D. Opponent-observation ablation** — `include_opponent=false` removes the
  opponent board/heights/pending channels.
* **E. Season 2 B2B charging** — `ruleset: tetrio_s1` (classic B2B) vs `tetrio_s2`
  (charging + Surge) with identical everything else.
* **F. Sample efficiency** — metric series are persisted per timestep.
* **G. Generalisation** — final checkpoints are evaluated against the unused
  beam-search opponent.

Configuration files are in `configs/`; `scripts/run_experiments.py` runs the matrix
and `scripts/make_report.py` produces tables and plots from the SQLite database.
Results are reported honestly, including sample sizes and confidence intervals —
nothing is fabricated. See `docs/EXPERIMENTS.md`.

## Reproducibility

* Deterministic piece/garbage RNGs seeded per episode and derived per match.
* Every run records algorithm, full config, seed, timestamps and checkpoints.
* Replays store seeds, per-tick actions/events and board frames; verification
  re-simulates and compares board hashes (no neural inference needed).
* Metrics never live only in memory: SQLite + filesystem survive restarts.

See `docs/REPRODUCIBILITY.md` for the exact experiment commands and expected
artefacts. Executed results (tables, confidence intervals, learning curves) are in
`docs/RESULTS.md`.

## Known limitations (documented, not hidden)

* The exact garbage messiness defaults are unpublished; they are configuration
  constants with documented approximations (`docs/RULESET.md` §13).
* I-piece 180° kick table has a documented frame ambiguity; JLSTZ 180s are safe.
* Placement-based action abstraction condenses movement into one decision; the
  "last action was a rotation" spin condition is reconstructed from geometry.
* External engines (Cold Clear, etc.) are used as placement suggesters only —
  the arena owns Season 2 attack/charging/garbage. Their integration status and
  licence are documented in `docs/BENCHMARKS.md`.
* Long training is compute-bound; results in `docs/EXPERIMENTS.md` reflect the
  actual budgets executed on this machine.

## Licence

Project code is MIT. External engines are not vendored; see
`docs/BENCHMARKS.md` for their licences and integration status.
