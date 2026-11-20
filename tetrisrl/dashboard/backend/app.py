"""FastAPI application for the TetrisRL dashboard.

Design
------
* ``create_app(db_path)`` builds an app bound to one SQLite database.  The
  database schema is owned by :class:`ExperimentManager`; this module never
  executes DDL.
* Training is always a child process (see :mod:`jobs`).  Starting a run returns
  immediately; progress is persisted by the trainer and read back from SQLite.
* Tournaments run in a background thread, write one replay JSON per match, and
  update the tournament row when finished.
* The built React SPA is served from ``tetrisrl/dashboard/static``; when the
  build is absent a friendly page explains how to build it.
* ``/ws/training`` broadcasts metric events from a small in-process bus.  A
  background poller feeds it from the database so training processes can feed
  it without sharing memory; external trainers may also POST metric batches to
  ``/api/runs/{id}/metrics``.
"""

from __future__ import annotations

import asyncio
import csv
import importlib
import importlib.util
import io
import itertools
import json
import os
import random
import re
import shutil
import signal
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ... import __version__
from ...training.experiment_manager import ExperimentManager
from .db import DashboardDB, downsample_metrics
from .jobs import JobManager, project_root, results_root

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ALGORITHM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
BUILTIN_PARTICIPANTS = ("random", "heuristic", "search")
EXTERNAL_PARTICIPANTS = ("coldclear", "riku", "coldclear1", "hikari", "blockfish")


def _engine_status(spec: str) -> Dict[str, Any]:
    """Availability of an external opponent adapter without spawning it."""
    try:
        if spec == "coldclear":
            from ...agents.opponents import coldclear_available, coldclear_binary_path

            available = bool(coldclear_available())
            path = str(coldclear_binary_path())
        elif spec == "riku":
            from ...agents.opponents.riku import riku_available, riku_binary_path

            available = bool(riku_available())
            path = str(riku_binary_path())
        elif spec == "hikari":
            from ...agents.opponents.hikari import hikari_available, hikari_binary_path

            available = bool(hikari_available())
            path = str(hikari_binary_path())
        elif spec == "coldclear1":
            from ...agents.opponents.coldclear1 import coldclear1_available, coldclear1_binary_path

            available = bool(coldclear1_available())
            path = str(coldclear1_binary_path())
        elif spec == "blockfish":
            from ...agents.opponents.blockfish import blockfish_available, blockfish_binary_path

            available = bool(blockfish_available())
            path = str(blockfish_binary_path())
        else:
            return {"available": False, "path": None, "error": f"unknown engine {spec!r}"}
    except Exception as exc:
        return {"available": False, "path": None, "error": f"{type(exc).__name__}: {exc}"}
    return {"available": available, "path": path, "error": None}


def _coldclear_status() -> Dict[str, Any]:
    return _engine_status("coldclear")


def _unused_coldclear_status() -> Dict[str, Any]:
    """Return Cold Clear 2 availability without importing heavy modules."""
    try:
        from ...agents.opponents import coldclear_available, coldclear_binary_path

        available = bool(coldclear_available())
        path = str(coldclear_binary_path())
    except Exception as exc:  # engine not built / adapter missing
        return {"available": False, "path": None, "error": f"{type(exc).__name__}: {exc}"}
    return {"available": available, "path": path, "error": None}

BUILD_HELP_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>TetrisRL Dashboard</title>
<style>
  body { background:#0d1117; color:#c9d1d9; font-family: ui-sans-serif, system-ui, sans-serif;
         display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }
  main { max-width: 720px; padding: 2rem; border:1px solid #30363d; border-radius: 12px;
         background:#161b22; }
  h1 { color:#58a6ff; margin-top:0; } code, pre { background:#0d1117; border-radius: 6px; }
  code { padding: .15rem .35rem; } pre { padding: 1rem; overflow:auto; }
  a { color:#58a6ff; }
</style></head>
<body><main>
<h1>TetrisRL dashboard backend is running</h1>
<p>The React frontend has not been built yet, so there is no SPA to serve.</p>
<p>Build it once (Node.js 18+):</p>
<pre>cd tetrisrl/dashboard/frontend
npm install
npm run build</pre>
<p>Then reload this page. The build output goes to
<code>tetrisrl/dashboard/static</code> and is committed to the repository, so a
normal checkout already contains it.</p>
<p>For frontend development run the backend with <code>--dev</code> and start
<code>npm run dev</code> inside <code>tetrisrl/dashboard/frontend</code>; the Vite
dev server proxies <code>/api</code> and <code>/ws</code> to port 8000.</p>
<p>API health check: <a href="/api/health">/api/health</a>. API docs:
<a href="/docs">/docs</a>.</p>
</main></body></html>
"""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class StartRunRequest(BaseModel):
    algorithm: str = Field(..., min_length=1, max_length=32)
    config: Dict[str, Any] = Field(default_factory=dict)
    seed: int = 0
    notes: str = ""
    name: Optional[str] = None
    timesteps: Optional[int] = Field(default=None, ge=1)
    run_id: Optional[str] = None


class MetricBatch(BaseModel):
    timestep: int = Field(..., ge=0)
    metrics: Dict[str, float] = Field(default_factory=dict)


class TournamentRequest(BaseModel):
    name: str = "Round-robin tournament"
    participants: List[str] = Field(default_factory=lambda: ["random", "heuristic"])
    seeds: Any = 1
    max_pieces: int = Field(default=500, ge=1, le=100_000)


# ---------------------------------------------------------------------------
# Fallback agents
#
# The real baselines live in ``tetrisrl.agents`` and are written by another
# workstream.  These small implementations keep the dashboard functional (and
# tournaments runnable) while those modules are still being written.  Whenever a
# fallback is used the tournament records a limitation entry.
# ---------------------------------------------------------------------------
class _FallbackRandomAgent:
    name = "random-fallback"

    def __init__(self) -> None:
        self.rng = random.Random(0)

    def reset(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed if seed is not None else 0)

    def choose_action(self, state: Any, opponent_state: Any = None) -> int:
        legal = state.legal_actions()
        return self.rng.choice(legal) if legal else -1


class _FallbackHeuristicAgent:
    """Dellacherie-style greedy placement scorer (no lookahead)."""

    name = "heuristic-fallback"

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def reset(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed if seed is not None else 0)

    def choose_action(self, state: Any, opponent_state: Any = None) -> int:
        legal = state.legal_actions()
        if not legal:
            return -1
        best_action = legal[0]
        best_score = float("-inf")
        for action in legal:
            placement = state.resolve(action)
            if placement is None:
                continue
            board = state.board.copy()
            board.lock(placement.cells)
            cleared = len(board.clear_lines())
            heights = board.heights()
            aggregate = sum(heights)
            holes = board.holes()
            bumpiness = board.bumpiness()
            max_height = max(heights) if heights else 0
            score = (
                cleared * 4.0
                - aggregate * 0.51
                - holes * 0.76
                - bumpiness * 0.18
                - max_height * 0.05
                + self.rng.random() * 1e-6
            )
            if score > best_score:
                best_score = score
                best_action = action
        return best_action


class _FallbackSearchAgent(_FallbackHeuristicAgent):
    """Placeholder for the beam-search baseline (uses the greedy scorer)."""

    name = "search-fallback"


_BUILTIN_AGENT_SPECS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "random": ("tetrisrl.agents.random_agent", ("RandomAgent", "RandomPlacementAgent", "Random")),
    "heuristic": ("tetrisrl.agents.heuristic_agent", ("HeuristicAgent", "Heuristic")),
    "search": ("tetrisrl.agents.search_agent", ("SearchAgent", "BeamSearchAgent", "Search")),
}

_FALLBACK_CLASSES = {
    "random": _FallbackRandomAgent,
    "heuristic": _FallbackHeuristicAgent,
    "search": _FallbackSearchAgent,
}

_EXTERNAL_LOADER_FUNCS = (
    "load_agent",
    "build_agent",
    "create_agent",
    "load_checkpoint_agent",
    "load_participant",
)


def _import_first(module_names: Iterable[str]) -> Optional[Any]:
    for name in module_names:
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


def _load_builtin_agent(name: str, limitations: List[str]) -> Any:
    module_name, class_names = _BUILTIN_AGENT_SPECS[name]
    module = _import_first([module_name])
    if module is not None:
        for class_name in class_names:
            cls = getattr(module, class_name, None)
            if cls is None:
                continue
            try:
                return cls()
            except TypeError:
                try:
                    return cls(0)
                except Exception:
                    continue
            except Exception:
                continue
    limitations.append(
        f"{name}: tetrisrl.agents.{name}_agent is unavailable; using dashboard fallback agent"
    )
    return _FALLBACK_CLASSES[name]()


def _load_external_agent(spec: str, limitations: List[str]) -> Optional[Any]:
    """Try to load ``ppo:<path>`` / ``dqn:<path>`` via the agent factory/helpers."""
    kind, _, checkpoint = spec.partition(":")
    if not checkpoint:
        limitations.append(f"{spec}: missing checkpoint path")
        return None

    # Preferred integration: ``tetrisrl.agents.make_agent`` understands
    # ``ppo:<checkpoint>`` and ``dqn:<checkpoint>`` directly.
    agents_module = _import_first(["tetrisrl.agents"])
    factory = getattr(agents_module, "make_agent", None) if agents_module is not None else None
    if callable(factory):
        try:
            agent = factory(spec)
        except TypeError:
            agent = None
        except Exception as exc:
            limitations.append(
                f"{spec}: agent factory could not load the checkpoint "
                f"({type(exc).__name__}: {exc})"
            )
            agent = None
        if agent is not None:
            return agent

    module = _import_first(["tetrisrl.evaluation.tournament", "tetrisrl.evaluation"])
    if module is None:
        limitations.append(
            f"{spec}: tetrisrl.evaluation.tournament is unavailable; falling back to a heuristic agent"
        )
        return None
    for func_name in _EXTERNAL_LOADER_FUNCS:
        loader = getattr(module, func_name, None)
        if not callable(loader):
            continue
        attempts = (
            lambda: loader(kind, checkpoint),
            lambda: loader(algorithm=kind, checkpoint=checkpoint),
            lambda: loader(algorithm=kind, checkpoint_path=checkpoint),
            lambda: loader(kind, checkpoint_path=checkpoint),
            lambda: loader(checkpoint, algorithm=kind),
            lambda: loader(spec),
            lambda: loader(checkpoint_path=checkpoint),
        )
        for attempt in attempts:
            try:
                agent = attempt()
            except TypeError:
                continue
            except Exception as exc:
                limitations.append(f"{spec}: loader {func_name} failed ({type(exc).__name__}: {exc})")
                break
            if agent is not None:
                return agent
    limitations.append(
        f"{spec}: no compatible checkpoint loader in tetrisrl.evaluation.tournament; "
        "falling back to a heuristic agent"
    )
    return None


def _build_agent(spec: str, limitations: List[str]) -> Any:
    spec = (spec or "").strip()
    if spec in EXTERNAL_PARTICIPANTS:
        status = _engine_status(spec)
        if not status["available"]:
            limitations.append(
                f"{spec}: engine unavailable; falling back to a heuristic agent "
                f"({status['error'] or 'missing built binary'})"
            )
            return _FallbackHeuristicAgent()
        agents_module = _import_first(["tetrisrl.agents"])
        factory = getattr(agents_module, "make_agent", None) if agents_module is not None else None
        if callable(factory):
            try:
                return factory(spec)
            except Exception as exc:
                limitations.append(f"{spec}: adapter failed to start ({type(exc).__name__}: {exc})")
                return _FallbackHeuristicAgent()
        limitations.append(f"{spec}: tetrisrl.agents.make_agent unavailable; using heuristic")
        return _FallbackHeuristicAgent()
    if spec == "coldclear":
        status = _coldclear_status()
        if not status["available"]:
            limitations.append(
                "coldclear: engine binary not available; falling back to a heuristic agent "
                f"({status['error'] or 'missing third_party/cold-clear-2 build'})"
            )
            return _FallbackHeuristicAgent()
        agents_module = _import_first(["tetrisrl.agents"])
        factory = getattr(agents_module, "make_agent", None) if agents_module is not None else None
        if callable(factory):
            try:
                return factory(spec)
            except Exception as exc:
                limitations.append(f"coldclear: adapter failed to start ({type(exc).__name__}: {exc})")
                return _FallbackHeuristicAgent()
        limitations.append("coldclear: tetrisrl.agents.make_agent is unavailable; using heuristic")
        return _FallbackHeuristicAgent()
    if spec in BUILTIN_PARTICIPANTS:
        return _load_builtin_agent(spec, limitations)
    if spec.startswith("ppo:") or spec.startswith("dqn:"):
        agent = _load_external_agent(spec, limitations)
        if agent is not None:
            return agent
        return _FallbackHeuristicAgent()
    limitations.append(f"{spec or '<empty>'}: unknown participant; using a heuristic agent")
    return _FallbackHeuristicAgent()


def _participant_limitations(participants: Sequence[str]) -> List[str]:
    """Static limitations recorded in the tournament config at submission."""
    limitations: List[str] = []
    module = None
    for spec in participants:
        if spec in BUILTIN_PARTICIPANTS:
            try:
                found = importlib.util.find_spec(_BUILTIN_AGENT_SPECS[spec][0]) is not None
            except Exception:
                found = False
            if not found:
                limitations.append(
                    f"{spec}: tetrisrl.agents.{spec}_agent not importable yet; fallback agent will be used"
                )
        elif spec.startswith(("ppo:", "dqn:")):
            agents_module = _import_first(["tetrisrl.agents"])
            factory = getattr(agents_module, "make_agent", None) if agents_module is not None else None
            if module is None:
                module = _import_first(["tetrisrl.evaluation.tournament", "tetrisrl.evaluation"])
            has_loader = callable(factory) or (
                module is not None
                and any(callable(getattr(module, fn, None)) for fn in _EXTERNAL_LOADER_FUNCS)
            )
            if not has_loader:
                limitations.append(
                    f"{spec}: no checkpoint agent factory available; "
                    "tournament will fall back to a built-in heuristic agent"
                )
        elif spec in EXTERNAL_PARTICIPANTS:
            status = _engine_status(spec)
            if not status["available"]:
                limitations.append(f"{spec}: engine unavailable; fallback heuristic agent will be used")
        elif spec == "coldclear":
            status = _coldclear_status()
            if not status["available"]:
                limitations.append(
                    "coldclear: engine binary not available; fallback heuristic agent will be used"
                )
        else:
            limitations.append(f"{spec}: unknown participant; fallback heuristic agent will be used")
    return limitations


# ---------------------------------------------------------------------------
# Broadcast bus
# ---------------------------------------------------------------------------
class BroadcastBus:
    """Minimal thread-safe broadcast bus for ``/ws/training``.

    Publishing with no listeners is a no-op.  Exceptions while sending to one
    websocket never affect other listeners or the API.
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        with self._lock:
            self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        with self._lock:
            self._connections.discard(websocket)

    @property
    def connection_count(self) -> int:
        with self._lock:
            return len(self._connections)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        with self._lock:
            connections = list(self._connections)
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(websocket)

    def publish(self, message: Dict[str, Any]) -> None:
        """Publish from any thread (no-op without listeners or a bound loop)."""
        with self._lock:
            if not self._connections:
                return
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), loop)
        except Exception:
            return


async def _metric_poller(manager: ExperimentManager, bus: BroadcastBus, interval: float = 1.0) -> None:
    """Feed the websocket bus from metric rows written by training processes."""
    db = DashboardDB(manager.db_path)
    cursors: Dict[str, int] = {}
    while True:
        try:
            await asyncio.sleep(interval)
            runs = manager.list_runs(limit=200)
            active = {r["id"] for r in runs if r.get("status") in ("running", "starting")}
            for run in runs:
                run_id = run["id"]
                if run_id not in active:
                    cursors.pop(run_id, None)
                    continue
                last = cursors.get(run_id, -1)
                rows = db.metrics_since(run_id, last, limit=500)
                if not rows:
                    continue
                grouped: Dict[int, Dict[str, float]] = {}
                for row in rows:
                    grouped.setdefault(int(row["timestep"]), {})[row["name"]] = float(row["value"])
                for timestep in sorted(grouped):
                    await bus.broadcast(
                        {
                            "type": "metric",
                            "run_id": run_id,
                            "timestep": timestep,
                            "metrics": grouped[timestep],
                        }
                    )
                cursors[run_id] = max(grouped)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:
            # A transient DB error must never kill the live feed.
            await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def _resolve_artifact_path(raw: Optional[str], artifacts: Path) -> Optional[Path]:
    if not raw:
        return None
    path = Path(raw)
    candidates: List[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend([Path.cwd() / path, artifacts / path, project_root() / path])
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _train_module_available() -> bool:
    """True when ``python -m tetrisrl train ...`` can at least be launched."""
    try:
        return importlib.util.find_spec("tetrisrl.__main__") is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Tournament execution
# ---------------------------------------------------------------------------
def _normalize_seeds(raw: Any) -> List[int]:
    if isinstance(raw, bool):
        raise ValueError("seeds must be an integer or a list of integers")
    if isinstance(raw, int):
        if not 1 <= raw <= 50:
            raise ValueError("seeds must be between 1 and 50")
        return list(range(raw))
    if isinstance(raw, (list, tuple)):
        values: List[int] = []
        for item in raw:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError("every seed must be an integer")
            values.append(int(item))
        if not values or len(values) > 50:
            raise ValueError("provide between 1 and 50 seeds")
        if len(set(values)) != len(values):
            raise ValueError("seeds must be unique")
        return values
    raise ValueError("seeds must be an integer or a list of integers")


def _standings(participants: Sequence[str], matches: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    table = {
        participant: {
            "participant": participant,
            "matches": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "points": 0.0,
            "ticks": 0,
        }
        for participant in participants
    }
    for match in matches:
        a, b = match.get("agent_a"), match.get("agent_b")
        if a not in table or b not in table:
            continue
        row_a, row_b = table[a], table[b]
        row_a["matches"] += 1
        row_b["matches"] += 1
        row_a["ticks"] += int(match.get("ticks") or 0)
        row_b["ticks"] += int(match.get("ticks") or 0)
        winner = match.get("winner")
        if winner == 0:
            row_a["wins"] += 1
            row_b["losses"] += 1
            row_a["points"] += 1.0
        elif winner == 1:
            row_b["wins"] += 1
            row_a["losses"] += 1
            row_b["points"] += 1.0
        else:
            row_a["draws"] += 1
            row_b["draws"] += 1
            row_a["points"] += 0.5
            row_b["points"] += 0.5
    rows = list(table.values())
    for row in rows:
        wins = row["wins"] + 0.5 * row["draws"]
        row["score"] = round(wins / row["matches"], 4) if row["matches"] else None
    rows.sort(key=lambda r: (-r["points"], -(r["score"] or 0), r["participant"]))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _write_tournament_csv(path: Path, tournament_id: str, matches: Sequence[Dict[str, Any]], standings: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "match_id",
            "tournament_id",
            "seed",
            "agent_a",
            "agent_b",
            "winner",
            "winner_name",
            "reason",
            "ticks",
            "replay_path",
        ]
    )
    for match in matches:
        winner = match.get("winner")
        winner_name = "draw" if winner is None else ("a" if winner == 0 else "b")
        writer.writerow(
            [
                match.get("id") or match.get("match_id"),
                tournament_id,
                match.get("seed"),
                match.get("agent_a"),
                match.get("agent_b"),
                "" if winner is None else winner,
                winner_name,
                match.get("reason"),
                match.get("ticks"),
                match.get("replay_path"),
            ]
        )
    writer.writerow([])
    writer.writerow(["rank", "participant", "matches", "wins", "losses", "draws", "points", "score", "ticks"])
    for row in standings:
        writer.writerow(
            [
                row["rank"],
                row["participant"],
                row["matches"],
                row["wins"],
                row["losses"],
                row["draws"],
                row["points"],
                row["score"],
                row["ticks"],
            ]
        )
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _run_tournament(
    manager: ExperimentManager,
    artifacts: Path,
    tournament_id: str,
    participants: Sequence[str],
    seeds: Sequence[int],
    max_pieces: int,
    name: str,
) -> None:
    limitations: List[str] = []
    match_records: List[Dict[str, Any]] = []
    failures: List[str] = []
    try:
        from ...environment.versus import VersusMatch

        pairs = list(itertools.combinations(range(len(participants)), 2))
        replays_dir = artifacts / "replays"
        replays_dir.mkdir(parents=True, exist_ok=True)
        for pair_index, (ia, ib) in enumerate(pairs):
            for seed in seeds:
                match_id = f"{tournament_id}-m{pair_index:03d}-s{seed}"
                try:
                    agent_a = _build_agent(participants[ia], limitations)
                    agent_b = _build_agent(participants[ib], limitations)
                    match = VersusMatch(
                        agent_a,
                        agent_b,
                        seed=int(seed),
                        max_pieces=int(max_pieces),
                        match_id=match_id,
                        metadata={
                            "tournament_id": tournament_id,
                            "tournament_name": name,
                            "participants": [participants[ia], participants[ib]],
                        },
                    )
                    result = match.run()
                    replay = result.replay
                    replay_path = replays_dir / f"{match_id}.json"
                    replay_path.write_text(json.dumps(replay), encoding="utf-8")
                    record = {
                        "id": match_id,
                        "seed": int(seed),
                        "agent_a": participants[ia],
                        "agent_b": participants[ib],
                        "winner": result.winner,
                        "reason": result.reason,
                        "ticks": int(result.ticks),
                        "replay_path": str(replay_path),
                        "stats": [s.to_dict() for s in result.stats],
                    }
                    manager.add_match(
                        match_id=match_id,
                        agent_a=participants[ia],
                        agent_b=participants[ib],
                        winner=result.winner,
                        reason=result.reason,
                        ticks=int(result.ticks),
                        seed=int(seed),
                        replay_path=str(replay_path),
                        stats={"players": [s.to_dict() for s in result.stats]},
                        tournament_id=tournament_id,
                    )
                    match_records.append(record)
                except Exception as exc:
                    failures.append(f"{match_id}: {type(exc).__name__}: {exc}")
        standings = _standings(participants, match_records)
        limitations[:] = list(dict.fromkeys(limitations))
        results = {
            "standings": standings,
            "matches": match_records,
            "limitations": limitations,
            "failures": failures,
            "seeds": list(seeds),
            "max_pieces": int(max_pieces),
        }
        csv_path = artifacts / "tournaments" / f"{tournament_id}.csv"
        _write_tournament_csv(csv_path, tournament_id, match_records, standings)
        completed = sum(1 for _ in match_records)
        status = "completed" if completed > 0 or not pairs else "failed"
        manager.update_tournament(
            tournament_id,
            status=status,
            results=results,
            csv_path=str(csv_path),
        )
    except Exception as exc:
        try:
            manager.update_tournament(
                tournament_id,
                status="failed",
                results={
                    "error": f"{type(exc).__name__}: {exc}",
                    "limitations": limitations,
                    "failures": failures,
                    "matches": match_records,
                },
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app(db_path: str | None = None) -> FastAPI:
    resolved_db = str(db_path or os.environ.get("TETRISRL_DB") or "results/tetrisrl.sqlite3")
    manager = ExperimentManager(resolved_db)
    artifacts = results_root()
    jobs = JobManager(manager, artifacts, cwd=project_root())
    jobs.recover_orphans()
    bus = BroadcastBus()
    tournament_threads: Dict[str, threading.Thread] = {}
    tournament_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bind_loop(asyncio.get_running_loop())
        poller = asyncio.create_task(_metric_poller(manager, bus))
        try:
            yield
        finally:
            poller.cancel()
            try:
                await poller
            except (asyncio.CancelledError, Exception):
                pass

    app = FastAPI(
        title="TetrisRL Dashboard",
        version=__version__,
        description="Local experiment dashboard API for the TetrisRL arena.",
        lifespan=lifespan,
    )
    app.state.db_path = resolved_db
    app.state.manager = manager
    app.state.artifacts_root = artifacts
    app.state.jobs = jobs
    app.state.bus = bus

    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEV_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- helpers ----------------------------------------------------------
    def get_run_or_404(run_id: str) -> Dict[str, Any]:
        run = manager.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
        return run

    def metrics_payload(run_id: str, names: Optional[Sequence[str]], max_points: Optional[int]) -> Dict[str, Any]:
        if names is not None and not names:
            return {"metrics": {}, "names": []}
        series = manager.get_metrics(run_id, names=names, max_points=None)
        series = downsample_metrics(series, max_points)
        return {
            "metrics": {name: [[t, v] for t, v in points] for name, points in series.items()},
            "names": sorted(series.keys()),
        }

    # -- meta -------------------------------------------------------------
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "db_path": resolved_db,
            "results_root": str(artifacts),
            "static_available": (STATIC_DIR / "index.html").is_file(),
            "trainer_available": _train_module_available(),
            "tracked_jobs": len(jobs.running_runs()),
            "tournaments_running": sum(1 for t in tournament_threads.values() if t.is_alive()),
        }

    @app.get("/api/overview")
    def overview() -> Dict[str, Any]:
        data = manager.overview()
        data["db_path"] = resolved_db
        return data

    # -- runs -------------------------------------------------------------
    @app.get("/api/runs")
    def list_runs(
        algorithm: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> Dict[str, Any]:
        return {"runs": manager.list_runs(algorithm=algorithm, status=status, limit=limit)}

    @app.post("/api/runs")
    def start_run(payload: StartRunRequest) -> Dict[str, Any]:
        if not ALGORITHM_RE.match(payload.algorithm):
            raise HTTPException(status_code=422, detail="algorithm must be alphanumeric (_,- allowed)")
        if payload.run_id is not None and not RUN_ID_RE.match(payload.run_id):
            raise HTTPException(status_code=422, detail="invalid run_id")
        run_id = payload.run_id or f"{payload.algorithm}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        run_dir = artifacts / "runs" / run_id
        try:
            run = manager.create_run(
                algorithm=payload.algorithm,
                config=payload.config,
                seed=payload.seed,
                name=payload.name,
                notes=payload.notes,
                results_dir=str(run_dir),
                run_id=run_id,
                status="starting",
                env={},
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"could not create run: {exc}") from exc

        config_path = run_dir / "config.json"
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(payload.config, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            manager.set_status(run_id, "failed", error=f"could not write config.json: {exc}")
            run = manager.get_run(run_id) or run
            return {"run": run, "spawned": False, "error": run.get("error")}

        if not _train_module_available():
            message = (
                "training entry point is missing: `python -m tetrisrl train` is not available "
                "(tetrisrl/__main__.py). The run record was created and marked failed; "
                "no process was spawned."
            )
            manager.set_status(run_id, "failed", error=message)
            bus.publish({"type": "run_status", "run_id": run_id, "status": "failed", "error": message})
            return {"run": manager.get_run(run_id), "spawned": False, "error": message}

        argv = [
            sys.executable,
            "-m",
            "tetrisrl",
            "train",
            "--algorithm",
            payload.algorithm,
            "--run-id",
            run_id,
            "--seed",
            str(int(payload.seed)),
            "--config",
            str(config_path),
        ]
        timesteps = payload.timesteps
        if timesteps is None:
            candidate = payload.config.get("timesteps", payload.config.get("total_timesteps"))
            if isinstance(candidate, (int, float)) and candidate > 0:
                timesteps = int(candidate)
        if timesteps:
            argv.extend(["--timesteps", str(int(timesteps))])
        if payload.notes:
            argv.extend(["--notes", payload.notes])
        device = payload.config.get("device")
        if isinstance(device, str) and device:
            # The CLI defaults --device to "auto" and applies it unconditionally,
            # so forward the posted config explicitly to preserve it.
            argv.extend(["--device", device])

        env = os.environ.copy()
        env["TETRISRL_DB"] = resolved_db
        env["PYTHONUNBUFFERED"] = "1"
        try:
            jobs.start(run_id, argv, env=env)
        except Exception as exc:
            message = f"failed to spawn training process: {type(exc).__name__}: {exc}"
            manager.set_status(run_id, "failed", error=message)
            bus.publish({"type": "run_status", "run_id": run_id, "status": "failed", "error": message})
            return {"run": manager.get_run(run_id), "spawned": False, "error": message}
        updated = manager.get_run(run_id)
        bus.publish({"type": "run_status", "run_id": run_id, "status": "running"})
        return {"run": updated, "spawned": True, "error": None}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> Dict[str, Any]:
        return get_run_or_404(run_id)

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(run_id: str) -> Dict[str, Any]:
        run = get_run_or_404(run_id)
        if run.get("status") in ("completed", "failed", "stale"):
            raise HTTPException(status_code=409, detail=f"run is already {run.get('status')}")
        info = jobs.stop(run_id)
        bus.publish({"type": "run_status", "run_id": run_id, "status": "stopped"})
        return {"run": manager.get_run(run_id), "stop": info}

    @app.post("/api/runs/{run_id}/resume")
    def resume_run(run_id: str) -> Dict[str, Any]:
        run = get_run_or_404(run_id)
        if jobs.is_running(run_id):
            raise HTTPException(status_code=409, detail="run is already running")
        checkpoints = manager.list_checkpoints(run_id=run_id, limit=1000)
        checkpoint_path = run.get("best_checkpoint")
        if not checkpoint_path and checkpoints:
            checkpoint_path = checkpoints[0].get("path")
        if not checkpoint_path:
            raise HTTPException(status_code=400, detail="no checkpoint available for this run")

        argv = [
            sys.executable,
            "-m",
            "tetrisrl",
            "train",
            "--algorithm",
            run["algorithm"],
            "--run-id",
            run_id,
            "--seed",
            str(int(run.get("seed") or 0)),
            "--resume",
            str(checkpoint_path),
        ]
        config_path = Path(run.get("results_dir") or artifacts / "runs" / run_id) / "config.json"
        if config_path.is_file():
            argv.extend(["--config", str(config_path)])
            try:
                resumed_config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                resumed_config = {}
            device = resumed_config.get("device") if isinstance(resumed_config, dict) else None
            if isinstance(device, str) and device:
                argv.extend(["--device", device])

        if not _train_module_available():
            message = (
                "training entry point is missing: `python -m tetrisrl train` is not available. "
                "The run was marked failed; no process was spawned."
            )
            manager.set_status(run_id, "failed", error=message)
            bus.publish({"type": "run_status", "run_id": run_id, "status": "failed", "error": message})
            return {"run": manager.get_run(run_id), "spawned": False, "error": message}

        env = os.environ.copy()
        env["TETRISRL_DB"] = resolved_db
        env["PYTHONUNBUFFERED"] = "1"
        try:
            jobs.start(run_id, argv, env=env)
        except Exception as exc:
            message = f"failed to spawn training process: {type(exc).__name__}: {exc}"
            manager.set_status(run_id, "failed", error=message)
            bus.publish({"type": "run_status", "run_id": run_id, "status": "failed", "error": message})
            return {"run": manager.get_run(run_id), "spawned": False, "error": message}
        bus.publish({"type": "run_status", "run_id": run_id, "status": "running"})
        return {"run": manager.get_run(run_id), "spawned": True, "error": None, "checkpoint": str(checkpoint_path)}

    @app.get("/api/runs/{run_id}/metrics")
    def run_metrics(
        run_id: str,
        names: Optional[str] = None,
        max_points: int = Query(default=500, ge=1, le=100000),
    ) -> Dict[str, Any]:
        get_run_or_404(run_id)
        selected = [n.strip() for n in names.split(",") if n.strip()] if names else None
        return metrics_payload(run_id, selected, max_points)

    @app.post("/api/runs/{run_id}/metrics")
    def push_metrics(run_id: str, payload: MetricBatch) -> Dict[str, Any]:
        """Internal extension: let an external trainer feed metrics + websocket."""
        get_run_or_404(run_id)
        manager.log_metrics(run_id, payload.timestep, payload.metrics)
        bus.publish(
            {
                "type": "metric",
                "run_id": run_id,
                "timestep": int(payload.timestep),
                "metrics": {k: float(v) for k, v in payload.metrics.items()},
            }
        )
        return {"ok": True, "run_id": run_id, "timestep": payload.timestep}

    @app.get("/api/runs/{run_id}/checkpoints")
    def run_checkpoints(run_id: str) -> Dict[str, Any]:
        get_run_or_404(run_id)
        return {"checkpoints": manager.list_checkpoints(run_id=run_id, limit=5000)}

    # -- checkpoints ------------------------------------------------------
    @app.get("/api/checkpoints")
    def checkpoints(
        run_id: Optional[str] = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> Dict[str, Any]:
        return {"checkpoints": manager.list_checkpoints(run_id=run_id, limit=limit)}

    # -- compare ----------------------------------------------------------
    @app.get("/api/compare")
    def compare(
        run_ids: str,
        metric: str,
        max_points: int = Query(default=500, ge=1, le=20000),
    ) -> Dict[str, Any]:
        ids = [item.strip() for item in run_ids.split(",") if item.strip()]
        if not ids:
            raise HTTPException(status_code=400, detail="run_ids is required")
        missing = [rid for rid in ids if manager.get_run(rid) is None]
        if missing:
            raise HTTPException(status_code=404, detail=f"runs not found: {', '.join(missing)}")
        series_by_run: List[Dict[str, Any]] = []
        all_names: set[str] = set()
        for run_id in ids:
            run = manager.get_run(run_id) or {}
            series = manager.get_metrics(run_id, names=[metric], max_points=None).get(metric, [])
            downsampled = downsample_metrics({metric: series}, max_points).get(metric, [])
            names = manager.list_metric_names(run_id)
            all_names.update(names)
            series_by_run.append(
                {
                    "run_id": run_id,
                    "name": run.get("name"),
                    "algorithm": run.get("algorithm"),
                    "status": run.get("status"),
                    "series": [[t, v] for t, v in downsampled],
                }
            )
        return {"metric": metric, "names": sorted(all_names), "runs": series_by_run}

    # -- deletion ---------------------------------------------------------
    def _safe_artifact(path: Optional[str]) -> Optional[Path]:
        """Return ``path`` only if it resolves under the artifacts root."""
        if not path:
            return None
        try:
            candidate = Path(path).resolve()
            candidate.relative_to(Path(artifacts).resolve())
        except (OSError, ValueError):
            return None
        return candidate

    def _remove_artifact(path: Optional[str], counts: Dict[str, int]) -> None:
        target = _safe_artifact(path)
        if target is None or not target.exists():
            return
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            counts["files"] += 1
        except OSError as exc:
            counts.setdefault("errors", [])
            counts["errors"].append(f"{target}: {exc}")

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> Dict[str, Any]:
        run = get_run_or_404(run_id)
        stopped = False
        if jobs.is_running(run_id) or jobs.tracked(run_id):
            try:
                jobs.stop(run_id, grace=3.0)
                stopped = True
            except Exception as exc:
                raise HTTPException(status_code=409, detail=f"could not stop run before delete: {exc}") from exc
        pid = run.get("pid")
        if not stopped and pid:
            try:
                os.kill(int(pid), 0)
            except (OSError, ValueError):
                pid = None
            if pid:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(1.0)
                    os.kill(int(pid), signal.SIGKILL)
                    stopped = True
                except OSError:
                    pass

        # Delete matches that reference this run.  Participants are stored as
        # ``ppo:<checkpoint path>``, so match on the run id, its checkpoint
        # paths and its results directory.
        removed_matches = 0
        counts: Dict[str, int] = {"files": 0}
        run_checkpoints = [c["path"] for c in manager.list_checkpoints(run_id, limit=100_000)]
        run_dir = str(run.get("results_dir") or "")
        for match in manager.list_matches(limit=100_000):
            haystack = f"{match.get('agent_a', '')} {match.get('agent_b', '')}"
            referenced = run_id in haystack or (run_dir and run_dir in haystack)
            referenced = referenced or any(str(path) in haystack for path in run_checkpoints)
            if referenced:
                _remove_artifact(match.get("replay_path"), counts)
                manager.delete_match(match["id"])
                removed_matches += 1

        result = manager.delete_run(run_id)
        for path in result.get("paths", []):
            _remove_artifact(path, counts)
        _remove_artifact(result.get("results_dir"), counts)
        bus.publish({"type": "run_deleted", "run_id": run_id})
        return {
            "deleted": True,
            "run_id": run_id,
            "stopped_process": stopped,
            "removed_matches": removed_matches,
            "removed_files": counts["files"],
            "errors": counts.get("errors", []),
        }

    @app.delete("/api/tournaments/{tournament_id}")
    def delete_tournament(tournament_id: str) -> Dict[str, Any]:
        tournament = manager.get_tournament(tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail=f"tournament {tournament_id!r} not found")
        with tournament_lock:
            thread = tournament_threads.get(tournament_id)
            if thread is not None and thread.is_alive():
                raise HTTPException(
                    status_code=409,
                    detail="tournament is still running; wait for it to finish before deleting",
                )
        result = manager.delete_tournament(tournament_id)
        counts: Dict[str, int] = {"files": 0}
        for path in result.get("paths", []):
            _remove_artifact(path, counts)
        _remove_artifact(result.get("csv_path"), counts)
        bus.publish({"type": "tournament_deleted", "tournament_id": tournament_id})
        return {
            "deleted": True,
            "tournament_id": tournament_id,
            "removed_matches": len(result.get("match_ids", [])),
            "removed_files": counts["files"],
            "errors": counts.get("errors", []),
        }

    # -- tournaments ------------------------------------------------------
    @app.get("/api/participants")
    def list_participants() -> Dict[str, Any]:
        """Dropdown source for the tournament form."""
        coldclear = _coldclear_status()
        builtin = [
            {
                "id": "coldclear",
                "label": "Cold Clear 2 (external engine)",
                "kind": "external",
                "available": bool(coldclear["available"]),
                "detail": coldclear["path"] if coldclear["available"] else "engine binary not built",
            },
            {
                "id": "riku",
                "label": "RIKU tetris-ai (TBP)",
                "kind": "external",
                "available": bool(_engine_status("riku")["available"]),
                "detail": _engine_status("riku")["path"] or "engine not built",
            },
            {
                "id": "coldclear1",
                "label": "Cold Clear 1 (C ABI, garbage-aware)",
                "kind": "external",
                "available": bool(_engine_status("coldclear1")["available"]),
                "detail": _engine_status("coldclear1")["path"] or "engine not built",
            },
            {
                "id": "hikari",
                "label": "Hikari (TBP, 24-row board)",
                "kind": "external",
                "available": bool(_engine_status("hikari")["available"]),
                "detail": _engine_status("hikari")["path"] or "engine not built",
            },
            {
                "id": "blockfish",
                "label": "Blockfish (cheese specialist, not versus)",
                "kind": "external",
                "available": bool(_engine_status("blockfish")["available"]),
                "detail": _engine_status("blockfish")["path"] or "engine not built",
            },
            {"id": "random", "label": "Random legal placement", "kind": "baseline", "available": True, "detail": None},
            {"id": "heuristic", "label": "Handcrafted heuristic", "kind": "baseline", "available": True, "detail": None},
            {"id": "search", "label": "Beam search (multi-ply)", "kind": "baseline", "available": True, "detail": None},
        ]
        checkpoints: List[Dict[str, Any]] = []
        for ckpt in manager.list_checkpoints(limit=200):
            run = manager.get_run(ckpt["run_id"]) or {}
            algorithm = run.get("algorithm") or ("ppo" if str(ckpt["run_id"]).startswith("ppo") else "dqn")
            exists = Path(ckpt["path"]).exists()
            checkpoints.append(
                {
                    "id": f"{algorithm}:{ckpt['path']}",
                    "label": f"{ckpt['run_id']} · step {int(ckpt['timestep']):,}",
                    "kind": "checkpoint",
                    "algorithm": algorithm,
                    "available": exists,
                    "detail": ckpt["path"] if exists else f"missing: {ckpt['path']}",
                    "timestep": int(ckpt["timestep"]),
                    "run_id": ckpt["run_id"],
                    "win_rate": ckpt.get("win_rate"),
                }
            )
        return {"builtin": builtin, "checkpoints": checkpoints}

    @app.get("/api/tournaments")
    def list_tournaments(limit: int = Query(default=100, ge=1, le=1000)) -> Dict[str, Any]:
        return {"tournaments": manager.list_tournaments(limit=limit)}

    @app.post("/api/tournaments")
    def create_tournament(payload: TournamentRequest) -> Dict[str, Any]:
        participants = [p.strip() for p in payload.participants if p and p.strip()]
        if len(participants) < 2:
            raise HTTPException(status_code=422, detail="at least two participants are required")
        if len(set(participants)) != len(participants):
            raise HTTPException(status_code=422, detail="participants must be unique")
        if len(participants) > 16:
            raise HTTPException(status_code=422, detail="at most 16 participants")
        if "coldclear" in participants and not _coldclear_status()["available"]:
            raise HTTPException(
                status_code=422,
                detail="Cold Clear 2 is not available: build third_party/cold-clear-2 "
                "(cargo build --release) or set TETRISRL_COLDCLEAR_BIN",
            )
        try:
            seeds = _normalize_seeds(payload.seeds)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        config = {
            "participants": participants,
            "seeds": seeds,
            "max_pieces": payload.max_pieces,
            "ruleset": "tetrio_s2",
            "limitations": _participant_limitations(participants),
        }
        tournament_id = f"tour-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        manager.create_tournament(payload.name, config=config, tournament_id=tournament_id, status="running")
        thread = threading.Thread(
            target=_run_tournament,
            args=(
                manager,
                artifacts,
                tournament_id,
                participants,
                seeds,
                payload.max_pieces,
                payload.name,
            ),
            name=f"tetrisrl-tournament-{tournament_id}",
            daemon=True,
        )
        with tournament_lock:
            tournament_threads[tournament_id] = thread
        thread.start()
        return {"tournament": manager.get_tournament(tournament_id), "matches": []}

    @app.get("/api/tournaments/{tournament_id}")
    def tournament_detail(tournament_id: str) -> Dict[str, Any]:
        tournament = manager.get_tournament(tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail=f"tournament {tournament_id!r} not found")
        return {"tournament": tournament, "matches": manager.list_matches(tournament_id=tournament_id, limit=5000)}

    @app.get("/api/tournaments/{tournament_id}/csv")
    def tournament_csv(tournament_id: str) -> Response:
        tournament = manager.get_tournament(tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail=f"tournament {tournament_id!r} not found")
        results = tournament.get("results") or {}
        matches = manager.list_matches(tournament_id=tournament_id, limit=5000)
        standings = results.get("standings") or _standings(
            (tournament.get("config") or {}).get("participants", []), matches
        )
        if not standings:
            participants = (tournament.get("config") or {}).get("participants", [])
            standings = _standings(participants, matches)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "match_id",
                "tournament_id",
                "seed",
                "agent_a",
                "agent_b",
                "winner",
                "winner_name",
                "reason",
                "ticks",
                "replay_path",
            ]
        )
        for match in matches:
            winner = match.get("winner")
            winner_name = "draw" if winner is None else ("a" if winner == 0 else "b")
            writer.writerow(
                [
                    match.get("id"),
                    tournament_id,
                    match.get("seed"),
                    match.get("agent_a"),
                    match.get("agent_b"),
                    "" if winner is None else winner,
                    winner_name,
                    match.get("reason"),
                    match.get("ticks"),
                    match.get("replay_path"),
                ]
            )
        if standings:
            writer.writerow([])
            writer.writerow(
                ["rank", "participant", "matches", "wins", "losses", "draws", "points", "score", "ticks"]
            )
            for row in standings:
                writer.writerow(
                    [
                        row.get("rank"),
                        row.get("participant"),
                        row.get("matches"),
                        row.get("wins"),
                        row.get("losses"),
                        row.get("draws"),
                        row.get("points"),
                        row.get("score"),
                        row.get("ticks"),
                    ]
                )
        csv_text = buffer.getvalue()
        return Response(
            content=csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{tournament_id}.csv"'},
        )

    # -- matches / replays ------------------------------------------------
    @app.get("/api/matches/{match_id}/replay")
    def match_replay(match_id: str) -> JSONResponse:
        match = manager.get_match(match_id)
        if match is None:
            raise HTTPException(status_code=404, detail=f"match {match_id!r} not found")
        path = _resolve_artifact_path(match.get("replay_path"), artifacts)
        if path is None:
            raise HTTPException(status_code=404, detail="replay file not found on disk")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"could not read replay: {exc}") from exc
        return JSONResponse(content=payload)

    @app.get("/api/replays")
    def list_replays(limit: int = Query(default=200, ge=1, le=2000)) -> Dict[str, Any]:
        matches = manager.list_matches(limit=limit)
        replays = []
        for match in matches:
            path = _resolve_artifact_path(match.get("replay_path"), artifacts)
            replays.append(
                {
                    "id": match.get("id"),
                    "match_id": match.get("id"),
                    "tournament_id": match.get("tournament_id"),
                    "created_at": match.get("created_at"),
                    "agent_a": match.get("agent_a"),
                    "agent_b": match.get("agent_b"),
                    "winner": match.get("winner"),
                    "reason": match.get("reason"),
                    "ticks": match.get("ticks"),
                    "seed": match.get("seed"),
                    "replay_path": match.get("replay_path"),
                    "available": path is not None,
                    "replay_url": f"/api/matches/{match.get('id')}/replay",
                }
            )
        return {"replays": replays}

    # -- websocket --------------------------------------------------------
    @app.websocket("/ws/training")
    async def ws_training(websocket: WebSocket) -> None:
        await bus.connect(websocket)
        try:
            await websocket.send_json(
                {"type": "hello", "message": "TetrisRL live training feed", "version": __version__}
            )
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            bus.disconnect(websocket)

    # -- static SPA -------------------------------------------------------
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        if not (STATIC_DIR / "index.html").is_file():
            return HTMLResponse(BUILD_HELP_HTML, status_code=200)
        static_root = STATIC_DIR.resolve()
        candidate = (STATIC_DIR / full_path).resolve() if full_path else (STATIC_DIR / "index.html")
        try:
            is_inside = candidate == static_root or static_root in candidate.parents
        except (OSError, ValueError):
            is_inside = False
        if full_path and is_inside and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")

    return app


__all__ = ["BroadcastBus", "create_app", "STATIC_DIR"]
