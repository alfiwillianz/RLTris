# Dashboard

The dashboard is a persistent local Web UI for the TetrisRL project. It answers
questions after (and during) long training sessions: what ran, how the metrics
evolved, which checkpoints exist, how algorithms compare, what the latest
tournament did, and what actually happened in a match.

It is split into a FastAPI backend, a React + TypeScript + Vite SPA, and a
committed production build of that SPA. The SQLite database is written by
training processes through `ExperimentManager`; the dashboard is a reader for
metrics and a supervisor for training processes. It does not train in-process
and does not keep authoritative state in memory.

## 1. Running

```bash
# canonical entry point (implemented by the project CLI)
.venv/bin/python -m tetrisrl dashboard
.venv/bin/python -m tetrisrl dashboard --host 127.0.0.1 --port 8000 --open
.venv/bin/python -m tetrisrl dashboard --dev
.venv/bin/python -m tetrisrl dashboard --db results/tetrisrl.sqlite3

# direct module entry point
.venv/bin/python -m tetrisrl.dashboard.server --host 127.0.0.1 --port 8000 \
    [--dev] [--open] [--db PATH]
```

`run_dashboard(host="127.0.0.1", port=8000, open_browser=False, dev=False)`
is the documented Python entry point. It returns `None` and blocks in uvicorn.
An optional `db_path=None` keyword was added so the project CLI's
`--db` flag can be wired through without changing the documented signature.

The server binds to `127.0.0.1` by default. There is no authentication; do not
expose it on a public interface.

### Static SPA

The built frontend lives in `tetrisrl/dashboard/static/` and is committed:

```
static/index.html
static/assets/index-*.js
static/assets/index-*.css
```

`create_app()` mounts `/assets` with `StaticFiles` when the build exists and
uses a catch-all route to return `index.html` for client-side routes such as
`/replays/<match_id>`. When the build is absent, every non-API route returns a
friendly HTML page with build instructions; the API stays usable.

### Frontend development

```bash
cd tetrisrl/dashboard/frontend
npm install
npm run dev       # http://localhost:5173, proxies /api and /ws to :8000
npm run build     # tsc --noEmit && vite build → ../static
```

Vite is configured with `outDir: ../static` and `emptyOutDir: true`. The dev
server proxies `/api` and websocket `/ws` to `127.0.0.1:8000`. CORS is enabled
for `http://localhost:5173` and `http://127.0.0.1:5173` so a dev UI can also
talk to the backend directly.

npm 12 caveats: devDependencies can be skipped when `NODE_ENV=production`
(use `npm install --include=dev`), and install scripts are blocked until
approved (`npm install-scripts approve esbuild && npm rebuild esbuild`).

## 2. Architecture

```
tetrisrl/dashboard/
  backend/
    __init__.py   exports create_app, JobManager, DashboardDB, BroadcastBus
    db.py         thin DashboardDB wrapper around ExperimentManager.
                  Adds only read helpers: downsample_series/metrics_since/
                  latest_timestep. The schema remains owned by
                  ExperimentManager; no DDL is duplicated.
    jobs.py       Popen supervisor keyed by run id, lock-protected.
                  PID liveness via os.kill(pid, 0); orphan recovery on start.
    app.py        create_app(db_path=None), API routes, tournament runner,
                  websocket bus/poller, SPA static serving.
  frontend/       React source (pages, components, lib).
  static/         committed production build.
  server.py       run_dashboard(...) and argparse CLI.
  README.md
```

Dependency direction is respected: the dashboard imports training persistence
and environment/versus, but the environment never imports the dashboard.

### Database

`ExperimentManager` is the single schema owner (`docs/ARCHITECTURE.md` §3). All
dashboard reads use its public methods. Two read-only helpers in `db.py` access
the existing `metrics` table for the live feed:

* `DashboardDB.metrics_since(run_id, after_timestep, limit)`
* `DashboardDB.latest_timestep(run_id)`

They use `ExperimentManager.connect()` and do not create or alter tables.

### Training process supervision

`POST /api/runs` creates the run record, writes the posted config to
`<results>/runs/<run_id>/config.json`, and spawns:

```
<sys.executable> -m tetrisrl train \
  --algorithm <algo> --run-id <run_id> --seed <seed> \
  --config <results>/runs/<run_id>/config.json \
  [--timesteps N] [--notes TEXT]
```

with `TETRISRL_DB=<db>` in the environment. The response returns immediately.

`JobManager` keeps `Popen` handles in a lock-protected dict and writes state
through `ExperimentManager`:

* spawn → `status="running"`, `pid=<pid>`, log at `<results>/runs/<id>/train.log`
* zero exit → `completed` (unless the run already wrote a terminal status)
* non-zero exit → `failed` with the exit code and log path in `error`
* stop → `SIGTERM`, wait 5 s, `SIGKILL`, then `status="stopped"` and `pid=NULL`
* startup → runs in `running`/`starting` whose PID is absent or dead become
  `stale` with a clear error

A missing training entry point (`tetrisrl/__main__.py` or a broken `train`
command) is never a 500: the record is created, marked `failed` with an explicit
message, and returned to the client.

`POST /api/runs/{id}/resume` picks `best_checkpoint` when set, else the newest
checkpoint row, and spawns `... train --resume <path> ...` with the same run id.
No checkpoint → HTTP 400. Already running → HTTP 409.

### Live updates

`/ws/training` is a best-effort broadcast channel:

```json
{"type": "hello", "message": "TetrisRL live training feed", "version": "0.1.0"}
{"type": "metric", "run_id": "...", "timestep": 1234, "metrics": {"train/loss": 0.4, "...": 0.0}}
{"type": "run_status", "run_id": "...", "status": "running"}
```

`BroadcastBus.publish()` is safe from any thread and is a no-op when there are
no listeners or no bound event loop. The training process itself writes metrics
directly through `ExperimentManager`; a one-second background poller reads new
metric rows from SQLite and publishes them, so training needs no shared memory
and no extra integration. External trainers may also push a metric batch with
`POST /api/runs/{id}/metrics` (extension, see below), which persists it and
broadcasts immediately.

There is no replay/backfill log: a websocket that connects later sees events
from the next poll onward (the poller's first pass may emit recent rows).

## 3. API

Implemented endpoints (all under `/api`):

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | status, version, db path, static/trainer availability |
| GET | `/api/overview` | counters, by-algorithm, best checkpoint, latest tournament, latest evals |
| GET | `/api/runs?algorithm=&status=&limit=` | `{"runs": [...]}`, newest first |
| POST | `/api/runs` | `{algorithm, config, seed, notes, name?, timesteps?, run_id?}` → `{run, spawned, error}` |
| GET | `/api/runs/{id}` | run object, 404 if missing |
| POST | `/api/runs/{id}/stop` | terminates tracked child; 409 if already terminal |
| POST | `/api/runs/{id}/resume` | resumes from best/latest checkpoint |
| GET | `/api/runs/{id}/metrics?names=a,b&max_points=500` | `{"metrics": {name: [[t,v], ...]}, "names": [...]}` |
| GET | `/api/runs/{id}/checkpoints` | `{"checkpoints": [...]}` |
| GET | `/api/checkpoints?run_id=&limit=` | `{"checkpoints": [...]}` |
| GET | `/api/compare?run_ids=a,b&metric=X&max_points=500` | one series per run plus its `algorithm` |
| POST | `/api/tournaments` | `{name, participants, seeds, max_pieces}`; runs in background |
| GET | `/api/tournaments?limit=` | `{"tournaments": [...]}` |
| GET | `/api/tournaments/{id}` | `{"tournament": {...}, "matches": [...]}` |
| GET | `/api/tournaments/{id}/csv` | `text/csv` attachment |
| GET | `/api/matches/{id}/replay` | raw replay JSON; 404 if match/file missing |
| GET | `/api/replays?limit=` | `{"replays": [...]}`, includes `id`, `match_id`, `available`, `replay_url` |
| WS | `/ws/training` | metric/status events |
| GET | `/{path}` | SPA (API 404s remain JSON) |

### Extensions beyond `docs/ARCHITECTURE.md` §4

These are additive and do not change documented endpoints:

1. `POST /api/runs/{id}/metrics` — internal live-feed helper:
   `{"timestep": N, "metrics": {name: value}}`. Persists through
   `ExperimentManager.log_metrics` and broadcasts.
2. `run_dashboard(..., db_path=None)` keyword and `--db` CLI flag.
3. `TETRISRL_RESULTS_DIR` environment variable: dashboard artifact root. It
   lets tests/dev keep artifacts outside the checkout. (The trainer itself
   still writes relative to its working directory; see limitations.)
4. Replay listing entries contain both `id` and `match_id` for convenience.
5. `POST /api/runs` accepts optional `run_id`, `timesteps`, and `name`.
6. `GET /api/compare` accepts optional `max_points` (default 500).

### Downsampling

Metric series are downsampled in the backend to at most `max_points` points,
always including the first and most recent samples. `max_points` defaults to
500 for run metrics/compare. A missing run is a 404; a missing metric name
returns an empty series rather than an error.

### Compare response

```json
{
  "metric": "eval/win_rate",
  "names": ["eval/win_rate", "train/loss", "..."],
  "runs": [
    {"run_id": "ppo-...", "name": "...", "algorithm": "ppo",
     "status": "completed", "series": [[0, 0.2], [500, 0.4]]}
  ]
}
```

## 4. Tournaments

`POST /api/tournaments` validates participants and seeds, creates a
`tournaments` row with `status="running"`, and starts a daemon thread. Each
unordered pair of participants plays once per seed (single round robin). For
each match the thread:

1. builds fresh agents (seeded by `VersusMatch.reset`),
2. runs `tetrisrl.environment.versus.VersusMatch`,
3. writes `<results>/replays/<match_id>.json`,
4. inserts a `matches` row with stats,
5. on completion writes a CSV to `<results>/tournaments/<tournament_id>.csv`
   and stores standings/results in `tournaments.results_json`.

Participants:

* `random`, `heuristic`, `search` — loaded through
  `tetrisrl.agents.make_agent`/the agent classes.
* `ppo:<checkpoint_path>`, `dqn:<checkpoint_path>` — loaded via
  `tetrisrl.agents.make_agent` (`PolicyAgent.from_checkpoint`), with fallback to
  evaluation helpers if an alternative loader exists.
* Unknown participants, missing modules, or an unavailable Torch/checkpoint
  fall back to a built-in heuristic agent. Every fallback is recorded in the
  tournament config/results `limitations` list; the UI displays them. No
  checkpoint participant is claimed as evaluated unless it actually loaded.

`seeds` accepts either an integer `N` (seeds `0..N-1`) or an explicit list of
integers; duplicate seeds are rejected. `max_pieces` bounds each match.

The tournament detail response includes DB matches (with replay paths) and the
stored standings. CSV always works: it is generated from the DB when results
JSON is unavailable.

## New run page

`/runs/new` is a dedicated, animated run builder (linked from the Runs header)
with three sections (algorithm/budget, opponents, metadata) and a sticky
estimated-cost card:

* algorithm (PPO / Double DQN), seed, timesteps, max pieces per episode,
  parallel environments and environment backend (in-process, subprocess,
  batched NumPy);
* training opponents as selectable cards with a per-move speed estimate and
  tags (solo, random, heuristic, beam search, seeded variants, and any built
  external engine). Multiple opponents are recorded as a mixed-opponent
  curriculum; a single one as a single-stage curriculum;
* a live estimate of throughput and wall-clock training time (including
  evaluation overhead) derived from opponent latency and the chosen backend;
* name and free-form experiment notes.

External engines (Cold Clear, RIKU, nana, …) are selectable in the training
picker with their availability checked against the built binaries; unavailable
engines are disabled and marked "not built". Selecting one shows a prominent
slow-training warning: each placement launches a separate search process
(milliseconds to seconds), so episode throughput collapses and short runs may
not progress. They are intended for short evaluations, fixed-opponent
fine-tuning and tournaments; the batched backend additionally ignores the
selection because it always plays a random opponent. The form posts
`{algorithm, seed, timesteps, notes, config}`, and the backend persists the run
before spawning the supervised training process.

## 5. Replay format and viewer

Each frame contains, per side, the 40-row occupancy bitmask, the active piece, hold/next,
combo/B2B/surge/garbage counters and `colors`: 40 strings of 10 characters (`I J L O S T Z`
for coloured blocks, `G` for garbage/unattributed blocks, `.` for empty). The colour layer is
reconstructed deterministically from the recorded placements, line clears and garbage insertions,
so the viewer can render authentic piece colours without replaying the engine or the network.


`tetrisrl/environment/versus.py` records, per tick:

```json
{
  "frames": [
    {"a": {"rows": [40 ints], "current": {...}, "hold": "...", "next": [...],
            "combo": 0, "b2b": false, "b2b_charge": 0.0, "surge": 0,
            "pending_garbage": 0, "lines": 0, "attack": 0, "pieces": 0,
            "top_out": false},
     "b": { ... }}
  ],
  "ticks": [
    {"t": 0,
     "a": {"action": 0, "piece": "T", "rotation": 0, "x": 3, "y": 20,
            "lines": 0, "attack": 0, "sent": 0, "cancelled": 0,
            "garbage_inserted": 0, "spin": false, "mini": false, ...},
     "b": { ... }}
  ],
  "result": {"winner": 0, "reason": "top_out_b", "ticks": 123,
             "stats": [{...}, {...}], "final_hashes": [h1, h2]},
  "agents": {"a": "heuristic", "b": "search"}
}
```

In each `rows[i]`, bit `i` is column `i` (bit 0 = leftmost). The rows are the
full 40-row bitboard; the viewer renders the bottom 20 visible rows.

The replay viewer is a pure playback client. It derives piece cells in
TypeScript from the mirrored SRS spawn matrices and the snapshot's
`name/rotation/x/y`; it never runs the Python engine, a randomizer, or neural
inference. Controls: play/pause, 0.5×/1×/2×/4×, step forward/back, first/last,
scrubber, and frame/tick readout. Per player it shows board, hold, next queue,
combo, B2B, charge, surge, pending garbage, lines, attack, pieces, and top-out.
It shows per-tick attack events (action/piece/lines/attack/sent/cancelled/
garbage, spins, perfect clears), a rolling log of recent clears/attacks, and the
final stats table.

Playback assumes `frames[i]` and `ticks[i]` correspond to the same recorded
tick (they do in `VersusMatch.run()`). Replays created with `record_frames=False`
or without ticks cannot be animated; the meta panel still loads.

## 6. Frontend pages

* `/` — Overview: counters, algorithm breakdown, best checkpoint, latest
  tournament, latest evaluations. Refreshes every 5 s.
* `/runs` — filterable table, start-run form (algorithm, seed, timesteps,
  notes, name). A failed spawn is reported instead of navigating away.
* `/runs/:id` — status, config/error/notes, stop/resume, checkpoint list,
  metric picker, multi-metric Recharts line chart. Polls every 3 s.
* `/compare` — multi-select runs, metric selector built from the selected runs'
  metric names, overlay chart, latest `eval/win_rate` with
  `eval/win_rate_ci_low`/`high`, and per-opponent win rates from checkpoint
  metadata (`opponents`/`per_opponent`/`win_rates` keys) when present.
* `/tournaments` — history and creation form (built-ins plus PPO/DQN checkpoint
  paths). Checkpoint-page links prefill the path via query parameters.
* `/tournaments/:id` — status, config, standings, per-match results, replay
  links, limitations/failures, CSV download.
* `/replays` — searchable replay list with availability.
* `/checkpoints` — browse all checkpoints, timestep/reward/win rate/path, and
  links to set up an evaluation or browse replays.
* `/replays/:id` — the replay viewer described above.

Every page fetches from the API on mount; there is no in-memory-only record of
results. API base URL is `import.meta.env.VITE_API_BASE` (default `""`).

## 7. Testing and verification

```bash
.venv/bin/python -m pytest tetrisrl/tests/test_dashboard.py -q
# 20 passed
```

Starlette's `TestClient` requires `httpx2` in this environment (it is not a
FastAPI runtime dependency): `uv pip install --python .venv/bin/python httpx2`.

The suite uses `TestClient`, a `tmp_path` SQLite DB, and direct
`ExperimentManager` seeding. It covers overview counters, run list/detail,
metric downsampling and name filtering, compare, checkpoints, tournament
list/detail/CSV, a real two-agent tournament, replay listing/fetch/404, the
missing-trainer failure path, spawn command construction, stop/resume, 404s,
websocket hello + metric broadcast, a real subprocess stopped through the API,
and persistence/orphan recovery across two app instances with the same DB path.

Frontend build verified with:

```bash
cd tetrisrl/dashboard/frontend
npm install
npm run build
# ✓ 648 modules transformed; static/index.html + assets written
```

The built SPA was served through uvicorn and checked over HTTP (`/`,
`/assets/index-*.js`, a deep client route, `/api/health`), both through
`python -m tetrisrl.dashboard.server` and through
`python -m tetrisrl dashboard --db <tmp>`.

End-to-end smoke test: `POST /api/runs` spawned a real PPO training child
(8 timesteps, CPU), which completed, logged a full metric set, and registered a
checkpoint; the API then served the metrics and checkpoint list. No browser
automation was run.

## 8. Known limitations

* **Trainer artifact root.** The dashboard writes configs/logs/replays under
  `TETRISRL_RESULTS_DIR` (default `<repo>/results`), but the current trainer
  writes its own `results/runs/<run_id>/config.json` relative to its working
  directory and may rewrite the posted config with the resolved config. In the
  default checkout these paths coincide. With `TETRISRL_RESULTS_DIR` overridden
  (tests/dev), a real child process would still write under `<repo>/results`.
* **Tournament interruption.** Orphan recovery covers training runs only. A
  dashboard crash/restart during a tournament leaves its row `running` with no
  worker; there is no tournament reaper yet.
* **Checkpoint agents need Torch.** `ppo:`/`dqn:` participants require PyTorch
  and a readable checkpoint. Failures are recorded and fall back to a heuristic
  agent; this is labelled, not silently presented as a real evaluation.
* **Fallback agents are dashboard-local.** If `tetrisrl.agents.*` is not
  importable (e.g. during parallel development), small random/heuristic
  fallbacks keep tournaments runnable and the limitation is recorded.
* **Live feed is best-effort.** No authentication, no backfill, no per-client
  subscriptions. Polling the REST endpoints remains the authoritative UI path.
* **Single-process supervisor.** A dashboard restart loses in-memory Popen
  tracking; runs with live PIDs are left alone, dead ones become `stale`.
  Stop/resume is only possible for runs the dashboard can spawn.
* **No auth / local only.** Default bind is `127.0.0.1`; do not expose publicly.
* **Replay animation** requires frame/tick recording. Corrupt replay files
  return 500 from the fetch endpoint; missing files return 404. There is no
  re-simulation or verification button in the UI (`verify_replay` remains a CLI
  concern).
* **Bundle size.** The production JS is ~615 kB (Recharts); no code splitting.
* **Static build is committed.** Frontend changes require rebuilding and
  committing `static/` so the no-npm deployment path keeps working.

## Deletion

Runs and tournaments can be deleted from the UI (Runs table, Run detail,
Tournaments history, Tournament detail) behind a confirmation prompt.

```
DELETE /api/runs/{id}
DELETE /api/tournaments/{id}
```

Cascade semantics:

* **Run**: stops the training process if it is running (SIGTERM, then SIGKILL),
  deletes the run row, its metric series, its checkpoint index and checkpoint
  files, its results directory (`results/runs/<id>` including eval JSON/logs),
  and every match whose participant spec references the run (with its replay
  file).
* **Tournament**: deletes the tournament row, its match rows, every replay file
  for those matches, and the exported CSV. A tournament whose background thread
  is still running is refused with `409` so a worker cannot recreate rows after
  deletion.

Safety: artifact paths are resolved and must live under the configured results
root before anything is unlinked; a checkpoint path pointing outside it is left
untouched (covered by `tests/test_dashboard.py`). Deleting is permanent — there
is no trash/undo.
