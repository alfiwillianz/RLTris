# TetrisRL Architecture

Status: **living document**. Interfaces marked *(frozen)* must not change without
coordinating every module that depends on them.

## 1. Layers

```
tetrisrl/
  environment/     deterministic simulation (no torch, no HTTP, no RL)
    board.py         bitboard playfield: occupancy, clears, garbage, metrics
    pieces.py        tetromino geometry, SRS rotation states, spawn boxes
    rotation.py      SRS / SRS+ / TETR.IO-180 kick tables (SRS x,y-up convention)
    placement.py     pure (piece, rotation, column) -> hard-dropped cells
    randomizer.py    deterministic seven-bag
    spin_detection.py corner rule + spin-in verification (T-spin / mini)
    scoring.py       clear classification, attack, combo, b2b charge, surge
    garbage.py       pending queue, cancellation, insertion, hole RNG
    ruleset.py       RulesetConfig presets (tetrio_s2, tetrio_s1, guideline)
    engine.py        GameState: placement actions -> lock/clear/attack/top-out
    versus.py        deterministic 1v1 ticks, match result, replay verification
    observation.py   structured observation + flat tensor encoder
    rewards.py       reward decomposition (every component logged)
    env.py           VersusEnv: reset/step/action_mask for both RL algorithms
  agents/          baselines and opponent adapters (no training code)
    base.py          reset/observe/choose_action/receive_result/terminate
    random_agent.py  uniform legal-placement baseline
    heuristic_agent.py handcrafted evaluation baseline
    search_agent.py  beam-search baseline (multi-ply, handcrafted eval)
    opponents/       subprocess adapters for external open-source engines
  rl/              neural agents only (torch)
    networks.py      MLP actor-critic / Q-network
    masked.py        masked categorical distribution + utilities
    ppo/             PPO agent (GAE, clipped objective, minibatches)
    dqn/             Double DQN agent + replay buffer
  training/        orchestration, curriculum, checkpoints, persistence
    experiment_manager.py  SQLite run/metric/checkpoint writer
    curriculum.py    stage definitions and opponent schedules
    trainer.py       shared rollout/training/eval loop
    run_runner.py    per-run entry point used by the CLI and dashboard
  evaluation/      tournaments, metrics, statistics, replay export
  dashboard/       FastAPI backend + React/Vite frontend
  tests/           pytest suite
```

Dependency direction: `environment` <- `agents`/`rl`/`evaluation` <- `training`
<- `dashboard`. The environment must never import torch.

## 2. Core contracts *(frozen)*

### 2.1 Actions

```python
ACTION_SPACE = 80                 # rotation(4) * column(10) * hold(2)
action = rotation * 20 + column * 2 + hold
```

* `rotation`: 0, 1 (R / CW), 2 (180), 3 (L / CCW).
* `column`: left-most *occupied* column of the piece, 0..9.
* `hold`: 1 = swap with hold first (invalid when hold unavailable).
* `GameState.action_mask() -> list[bool]` (length 80) is the canonical
  validity source.  Engine `apply_action` returns `valid=False` for masked ids
  and never mutates state on an invalid action.

### 2.2 GameState

```python
GameState(ruleset="tetrio_s2", seed=0, garbage_seed=None,
          piece_source=None, player_id=0, max_pieces=100_000)
.apply_action(action) -> StepResult
.legal_actions() -> list[int]
.action_mask() -> list[bool]
.state_dict() / .load_state_dict(d)      # JSON-safe (RNG state pickled separately)
.snapshot() -> dict                      # replay frame
```

`StepResult` fields: `valid, piece, rotation, column, x, y, cells, hold_used,
spin, mini, lines, cleared_rows, perfect_clear, clear, attack, cancelled, sent,
garbage_inserted, garbage_events, top_out, topped_out_reason, game_over`.

### 2.3 Versus

```python
VersusMatch(agent_a, agent_b, ruleset, seed, max_pieces,
            record_frames=True, record_events=True, match_id="")
    .run() -> MatchResult(winner: 0|1|None, reason, ticks, stats, replay)
```

Agents implement `reset(seed)`, `choose_action(state, opponent_state) -> int`.
Each tick both agents choose from the pre-tick state, both placements are
applied, then attacks are delivered.  Replay verification re-applies the
recorded actions in `replay["ticks"]` and compares final board hashes.

### 2.4 Environment

```python
env = VersusEnv(ruleset, opponent, seed, reward_config, encoder, config)
obs, info = env.reset(seed=None)
obs, reward, terminated, truncated, info = env.step(action)
info["action_mask"]      # list[bool]
info["reward_components"]  # dict of logged components
```

### 2.5 Observation *(frozen layout, `OBS_VERSION = 1`)*

Flat float32 vector, slice boundaries available from
`ObservationEncoder.layout()`:

| slice | size | contents |
|---|---|---|
| `own_board` | 400 | 40x10 occupancy, row-major, top row first |
| `opponent_board` | 400 | 40x10 (omitted when `include_opponent=False`) |
| `own_heights` | 10 | visible column heights / board height |
| `opponent_heights` | 10 | (omitted when `include_opponent=False`) |
| `hold` | 8 | 7 piece one-hot + hold-available flag |
| `preview` | 5*7 | next pieces one-hot (only the configured preview) |
| `current_piece` | 7 | one-hot |
| `current_rotation` | 4 | one-hot |
| `scalars` | 15 | combo, b2b, charge, surge, pending, attack history, board metrics |

The encoder never reads the piece bag beyond `preview`.

### 2.6 Reward

`RewardConfig` (dataclass) + `compute_reward(...) -> (total, components)` with
components `clear, attack, defense, survival, terminal, board_penalty, b2b,
combo, surge, total`.  Both algorithms must use the same function.

## 3. Persistence

SQLite database (`results/tetrisrl.sqlite3` by default, override with
`TETRISRL_DB`).  Filesystem for large artifacts (`results/runs/<run_id>/`,
`results/replays/*.json`, checkpoints).

```sql
runs(id TEXT PRIMARY KEY, name TEXT, algorithm TEXT, status TEXT, config_json TEXT,
     seed INTEGER, created_at TEXT, started_at TEXT, ended_at TEXT, updated_at TEXT,
     notes TEXT, total_timesteps INTEGER, best_checkpoint TEXT, results_dir TEXT,
     pid INTEGER, error TEXT, env_json TEXT);
metrics(run_id TEXT, timestep INTEGER, name TEXT, value REAL,
        PRIMARY KEY(run_id, timestep, name));
checkpoints(id TEXT PRIMARY KEY, run_id TEXT, path TEXT, timestep INTEGER,
            created_at TEXT, mean_reward REAL, win_rate REAL, metadata_json TEXT);
tournaments(id TEXT PRIMARY KEY, name TEXT, created_at TEXT, config_json TEXT,
            status TEXT, results_json TEXT, csv_path TEXT);
matches(id TEXT PRIMARY KEY, tournament_id TEXT, created_at TEXT, agent_a TEXT,
        agent_b TEXT, winner INTEGER, reason TEXT, ticks INTEGER, seed INTEGER,
        replay_path TEXT, stats_json TEXT);
```

`ExperimentManager` is the only writer of these tables from training processes.

## 4. Dashboard API

```
GET  /api/health
GET  /api/overview
GET  /api/runs?algorithm=&status=&limit=
POST /api/runs                      {algorithm, config, seed, notes, name?}
GET  /api/runs/{id}
POST /api/runs/{id}/stop
POST /api/runs/{id}/resume
GET  /api/runs/{id}/metrics?names=a,b&max_points=500
GET  /api/runs/{id}/checkpoints
GET  /api/checkpoints
GET  /api/compare?run_ids=a,b&metric=eval/win_rate
POST /api/tournaments               {name, participants, seeds, max_pieces}
GET  /api/tournaments
GET  /api/tournaments/{id}
GET  /api/tournaments/{id}/csv
GET  /api/matches/{id}/replay
GET  /api/replays
WS   /ws/training                   live metric events
```

Training processes run as child processes (`python -m tetrisrl train ...`) and
persist metrics themselves through `ExperimentManager`; the API is read-only for
metrics and controls runs through the process supervisor.

## 5. CLI

```
python -m tetrisrl train --algorithm {ppo,dqn} [--config FILE] [--seed N]
                         [--timesteps N] [--resume CHECKPOINT] [--run-id ID]
python -m tetrisrl evaluate --algorithm {ppo,dqn} [--checkpoint PATH]
python -m tetrisrl tournament [--config FILE]
python -m tetrisrl play --agent {ppo,dqn,heuristic,random,search}
python -m tetrisrl replay --file results/replays/x.json [--verify]
python -m tetrisrl benchmark [--steps N]
python -m tetrisrl dashboard [--host H] [--port P] [--dev]
```

## 6. Determinism

* Piece generation: per-player `random.Random(seed)` seven-bag.
* Garbage holes: per-player `random.Random(garbage_seed)`.
* Opponent randomness: seeded `random.Random` owned by the agent.
* `VersusMatch` derives four independent seeds from one match seed.
* Replays store seeds + actions; `verify_replay` re-simulates and compares board
  hashes.  Neural inference is never required for playback.

## 7. Batched (NumPy) simulation backend

`tetrisrl/environment/batched.py` implements a vectorised placement/board core
for `N` independent boards:

* exact hard-drop resolution for all 80 actions (per-column first-block rows,
  not a height-table approximation), action masks, locking, stable line-clear
  compaction, garbage insertion, 64-bit board hashes, column heights;
* **24.7x throughput** over the scalar reference engine in the benchmark
  (`256 boards`, measured `33,445` vs `1,356` board-steps/s on this machine;
  run `python scripts/benchmark_batched.py`).

Parity is enforced by differential tests (`tetrisrl/tests/test_batched.py`):
for randomized boards, the mask, landing rows and absolute cells must match the
reference engine action-for-action, and lock+clear must produce identical board
hashes.

**Scope and limits.** The batched core deliberately does not yet implement
spawn-area rotation kicks, spin-in (rotation-at-rest) resolution, spin
detection, B2B charging/Surge accounting, garbage exchange, or observation and
reward assembly. It is therefore a validated *placement/board backend*, not a
drop-in replacement for `GameState`; headline experiments still use the
reference engine. The integration path is: port scoring/garbage per board
(vectorised where possible), assemble observations in a batched encoder, then
expose a `VecEnv`-compatible wrapper and run the parity suite on full episodes
before switching any reported experiment.

The spawn-kick change made for exact action semantics (an action's column is
the placement's left-most occupied column) is documented in the placement module
and covered by the SRS tests.
