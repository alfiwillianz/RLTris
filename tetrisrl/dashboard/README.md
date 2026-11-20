# TetrisRL Dashboard

Persistent local Web UI for training runs, algorithm comparison, round-robin
tournaments, and deterministic match replays.

* Backend: FastAPI + SQLite (via `ExperimentManager`)
* Frontend: React + TypeScript + Vite (Recharts)
* Artifacts: checkpoints/configs/logs in `results/runs/<run_id>/`, replays in
  `results/replays/<match_id>.json`
* The built SPA is committed under `tetrisrl/dashboard/static/`, so a plain
  checkout works **without Node.js**.

See [`docs/DASHBOARD.md`](../../../docs/DASHBOARD.md) for the full reference
(API, replay format, process supervision, limitations).

## Quick start

```bash
# from the repository root
.venv/bin/python -m tetrisrl dashboard
# → http://127.0.0.1:8000

# options
.venv/bin/python -m tetrisrl dashboard --host 127.0.0.1 --port 8000 --open
.venv/bin/python -m tetrisrl dashboard --dev     # reload + Vite instructions
.venv/bin/python -m tetrisrl dashboard --db results/tetrisrl.sqlite3
```

Equivalent direct entry point:

```bash
.venv/bin/python -m tetrisrl.dashboard.server --host 127.0.0.1 --port 8000
```

API health check: `http://127.0.0.1:8000/api/health`; OpenAPI docs at `/docs`.

## Frontend development

```bash
cd tetrisrl/dashboard/frontend
npm install
npm run dev        # http://localhost:5173, proxies /api and /ws to :8000
```

Run the backend with `--dev` in another terminal. To produce the committed
bundle:

```bash
cd tetrisrl/dashboard/frontend
npm run build      # tsc --noEmit && vite build → ../static
```

Notes:

* `NODE_ENV=production npm install` omits devDependencies. Use
  `npm install --include=dev` (or unset `NODE_ENV`) when building locally.
* npm 12 blocks install scripts by default; approve esbuild's postinstall once:
  `npm install-scripts approve esbuild && npm rebuild esbuild`.

## Backend development / tests

```bash
.venv/bin/python -m pytest tetrisrl/tests/test_dashboard.py -q
```

The tests use a temporary SQLite database and a temporary artifact directory;
they never start training, require npm, or touch `results/`.

Starlette's `TestClient` needs `httpx2` in this environment (it is not a
FastAPI runtime dependency). Install it once with:

```bash
uv pip install --python .venv/bin/python httpx2
```

## Layout

```
tetrisrl/dashboard/
  backend/
    __init__.py      public exports
    db.py            ExperimentManager wrapper + read helpers (no schema)
    jobs.py          Popen supervisor, orphan recovery, PID liveness
    app.py           FastAPI factory, API, tournaments, websocket, SPA serving
  frontend/          React + TypeScript + Vite source
  static/            committed production build
  server.py          run_dashboard(host, port, open_browser=False, dev=False)
  README.md
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `TETRISRL_DB` | `results/tetrisrl.sqlite3` | SQLite database used by the API and training children |
| `TETRISRL_RESULTS_DIR` | `<repo>/results` | Dashboard artifact root (replays, run dirs, tournament CSV); tests use it to stay out of the repo |

`VITE_API_BASE` (frontend build time) can point the UI at a different API
origin; it defaults to same-origin `""`.
