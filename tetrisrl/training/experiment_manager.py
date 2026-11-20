"""Persistent experiment tracking (SQLite).

This module is the single schema owner for both the training processes and the
dashboard.  Large artifacts (checkpoints, replays) live on disk; SQLite stores
metadata and metric series only.

Design notes
------------
* Every operation opens its own short-lived connection (WAL mode) so a training
  child process, the dashboard backend, and CLI tools can write/read safely
  without shared-state bugs.
* Metric writes are idempotent upserts keyed by ``(run_id, timestep, name)``.
* No in-memory state is required for the dashboard to work after a restart.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_DB = "results/tetrisrl.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    name TEXT,
    algorithm TEXT NOT NULL,
    status TEXT NOT NULL,
    config_json TEXT,
    env_json TEXT,
    seed INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    updated_at TEXT,
    notes TEXT,
    total_timesteps INTEGER DEFAULT 0,
    best_checkpoint TEXT,
    results_dir TEXT,
    pid INTEGER,
    error TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
    run_id TEXT NOT NULL,
    timestep INTEGER NOT NULL,
    name TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (run_id, timestep, name)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    path TEXT NOT NULL,
    timestep INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    mean_reward REAL,
    win_rate REAL,
    metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS tournaments (
    id TEXT PRIMARY KEY,
    name TEXT,
    created_at TEXT NOT NULL,
    config_json TEXT,
    status TEXT,
    results_json TEXT,
    csv_path TEXT
);
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    tournament_id TEXT,
    created_at TEXT NOT NULL,
    agent_a TEXT,
    agent_b TEXT,
    winner INTEGER,
    reason TEXT,
    ticks INTEGER,
    seed INTEGER,
    replay_path TEXT,
    stats_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_metrics_run ON metrics(run_id, name, timestep);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id, timestep);
CREATE INDEX IF NOT EXISTS idx_matches_tournament ON matches(tournament_id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> str:
    return os.environ.get("TETRISRL_DB", DEFAULT_DB)


class ExperimentManager:
    def __init__(self, db_path: Optional[str] = None, create: bool = True) -> None:
        self.db_path = str(db_path or default_db_path())
        if create:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self.init_db()

    # -- infrastructure ----------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    # -- runs --------------------------------------------------------------
    def create_run(
        self,
        algorithm: str,
        config: Optional[Dict[str, Any]] = None,
        seed: int = 0,
        name: Optional[str] = None,
        notes: str = "",
        results_dir: Optional[str] = None,
        run_id: Optional[str] = None,
        status: str = "created",
        env: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        run_id = run_id or f"{algorithm}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        now = utcnow()
        results_dir = results_dir or f"results/runs/{run_id}"
        Path(results_dir).mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, name, algorithm, status, config_json, env_json, seed, created_at, "
                "started_at, ended_at, updated_at, notes, total_timesteps, best_checkpoint, results_dir, pid, error) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    name or run_id,
                    algorithm,
                    status,
                    json.dumps(config or {}),
                    json.dumps(env or {}),
                    int(seed),
                    now,
                    None,
                    None,
                    now,
                    notes,
                    0,
                    None,
                    results_dir,
                    None,
                    None,
                ),
            )
            conn.commit()
        return self.get_run(run_id)  # type: ignore[return-value]

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {
            "name",
            "status",
            "config_json",
            "env_json",
            "seed",
            "started_at",
            "ended_at",
            "notes",
            "total_timesteps",
            "best_checkpoint",
            "results_dir",
            "pid",
            "error",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = utcnow()
        cols = ", ".join(f"{k}=?" for k in updates)
        with self.connect() as conn:
            conn.execute(f"UPDATE runs SET {cols} WHERE id=?", (*updates.values(), run_id))
            conn.commit()

    def set_status(self, run_id: str, status: str, error: Optional[str] = None) -> None:
        fields: Dict[str, Any] = {"status": status, "error": error}
        if status == "running":
            fields["started_at"] = utcnow()
        if status in ("completed", "failed", "stopped"):
            fields["ended_at"] = utcnow()
        self.update_run(run_id, **fields)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self._run_row(row) if row else None

    def list_runs(
        self,
        algorithm: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = 200,
    ) -> List[Dict[str, Any]]:
        q = "SELECT * FROM runs WHERE 1=1"
        params: List[Any] = []
        if algorithm:
            q += " AND algorithm=?"
            params.append(algorithm)
        if status:
            q += " AND status=?"
            params.append(status)
        q += " ORDER BY created_at DESC"
        if limit:
            q += " LIMIT ?"
            params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(q, params).fetchall()
        return [self._run_row(r) for r in rows]

    def _run_row(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for key in ("config_json", "env_json"):
            try:
                d[key.replace("_json", "")] = json.loads(d.pop(key) or "{}")
            except json.JSONDecodeError:
                d[key.replace("_json", "")] = {}
        return d

    # -- metrics -----------------------------------------------------------
    def log_metrics(self, run_id: str, timestep: int, metrics: Dict[str, float]) -> None:
        rows = [(run_id, int(timestep), str(k), float(v)) for k, v in metrics.items() if v is not None]
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO metrics (run_id, timestep, name, value) VALUES (?,?,?,?) "
                "ON CONFLICT(run_id, timestep, name) DO UPDATE SET value=excluded.value",
                rows,
            )
            conn.execute(
                "UPDATE runs SET total_timesteps=MAX(total_timesteps, ?), updated_at=? WHERE id=?",
                (int(timestep), utcnow(), run_id),
            )
            conn.commit()

    def get_metrics(
        self,
        run_id: str,
        names: Optional[Sequence[str]] = None,
        max_points: Optional[int] = None,
    ) -> Dict[str, List[Tuple[int, float]]]:
        q = "SELECT name, timestep, value FROM metrics WHERE run_id=?"
        params: List[Any] = [run_id]
        if names:
            q += " AND name IN (" + ",".join("?" for _ in names) + ")"
            params.extend(names)
        q += " ORDER BY timestep ASC"
        with self.connect() as conn:
            rows = conn.execute(q, params).fetchall()
        out: Dict[str, List[Tuple[int, float]]] = {}
        for r in rows:
            out.setdefault(r["name"], []).append((int(r["timestep"]), float(r["value"])))
        if max_points:
            for name, series in out.items():
                if len(series) > max_points:
                    step = max(1, len(series) // max_points)
                    out[name] = series[::step]
        return out

    def list_metric_names(self, run_id: str) -> List[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT name FROM metrics WHERE run_id=? ORDER BY name", (run_id,)
            ).fetchall()
        return [r["name"] for r in rows]

    # -- checkpoints -------------------------------------------------------
    def add_checkpoint(
        self,
        run_id: str,
        path: str,
        timestep: int,
        mean_reward: Optional[float] = None,
        win_rate: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        checkpoint_id = f"{run_id}@{int(timestep)}"
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO checkpoints (id, run_id, path, timestep, created_at, mean_reward, win_rate, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path, "
                "mean_reward=excluded.mean_reward, win_rate=excluded.win_rate, metadata_json=excluded.metadata_json",
                (
                    checkpoint_id,
                    run_id,
                    path,
                    int(timestep),
                    utcnow(),
                    mean_reward,
                    win_rate,
                    json.dumps(metadata or {}),
                ),
            )
            conn.commit()
        return checkpoint_id

    def list_checkpoints(self, run_id: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        q = "SELECT * FROM checkpoints"
        params: List[Any] = []
        if run_id:
            q += " WHERE run_id=?"
            params.append(run_id)
        q += " ORDER BY timestep DESC LIMIT ?"
        params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                d["metadata"] = {}
            out.append(d)
        return out

    # -- tournaments -------------------------------------------------------
    def create_tournament(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None,
        tournament_id: Optional[str] = None,
        status: str = "running",
    ) -> str:
        tid = tournament_id or f"tour-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO tournaments (id, name, created_at, config_json, status, results_json, csv_path) "
                "VALUES (?,?,?,?,?,?,?)",
                (tid, name, utcnow(), json.dumps(config or {}), status, None, None),
            )
            conn.commit()
        return tid

    def update_tournament(
        self,
        tournament_id: str,
        status: Optional[str] = None,
        results: Optional[Dict[str, Any]] = None,
        csv_path: Optional[str] = None,
    ) -> None:
        fields: Dict[str, Any] = {}
        if status is not None:
            fields["status"] = status
        if results is not None:
            fields["results_json"] = json.dumps(results)
        if csv_path is not None:
            fields["csv_path"] = csv_path
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.connect() as conn:
            conn.execute(f"UPDATE tournaments SET {cols} WHERE id=?", (*fields.values(), tournament_id))
            conn.commit()

    def list_tournaments(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tournaments ORDER BY created_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["config"] = json.loads(d.pop("config_json") or "{}")
            d["results"] = json.loads(d.pop("results_json") or "null")
            out.append(d)
        return out

    def get_tournament(self, tournament_id: str) -> Optional[Dict[str, Any]]:
        for t in self.list_tournaments(limit=10000):
            if t["id"] == tournament_id:
                return t
        return None

    def add_match(
        self,
        match_id: str,
        agent_a: str,
        agent_b: str,
        winner: Optional[int],
        reason: str,
        ticks: int,
        seed: int,
        replay_path: Optional[str] = None,
        stats: Optional[Dict[str, Any]] = None,
        tournament_id: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO matches (id, tournament_id, created_at, agent_a, agent_b, winner, reason, ticks, seed, replay_path, stats_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    match_id,
                    tournament_id,
                    utcnow(),
                    agent_a,
                    agent_b,
                    winner,
                    reason,
                    int(ticks),
                    int(seed),
                    replay_path,
                    json.dumps(stats or {}),
                ),
            )
            conn.commit()

    def list_matches(self, tournament_id: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        q = "SELECT * FROM matches"
        params: List[Any] = []
        if tournament_id:
            q += " WHERE tournament_id=?"
            params.append(tournament_id)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["stats"] = json.loads(d.pop("stats_json") or "{}")
            out.append(d)
        return out

    def get_match(self, match_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["stats"] = json.loads(d.pop("stats_json") or "{}")
        return d

    # -- overview ----------------------------------------------------------
    def overview(self) -> Dict[str, Any]:
        with self.connect() as conn:
            def scalar(q: str, params: Sequence[Any] = ()) -> Any:
                row = conn.execute(q, params).fetchone()
                return row[0] if row else 0

            total_runs = scalar("SELECT COUNT(*) FROM runs")
            active = scalar("SELECT COUNT(*) FROM runs WHERE status IN ('running','starting')")
            completed = scalar("SELECT COUNT(*) FROM runs WHERE status='completed'")
            failed = scalar("SELECT COUNT(*) FROM runs WHERE status='failed'")
            total_steps = scalar("SELECT COALESCE(SUM(total_timesteps),0) FROM runs")
            best = conn.execute(
                "SELECT id, best_checkpoint, algorithm FROM runs WHERE best_checkpoint IS NOT NULL ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            latest_tournament = conn.execute(
                "SELECT id, name, created_at, status FROM tournaments ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            algorithm_counts = {
                r["algorithm"]: r["n"] for r in conn.execute("SELECT algorithm, COUNT(*) n FROM runs GROUP BY algorithm")
            }
            latest_evals = {}
            for algo in ("ppo", "dqn"):
                row = conn.execute(
                    "SELECT run_id, timestep, value FROM metrics WHERE name='eval/win_rate' AND run_id IN "
                    "(SELECT id FROM runs WHERE algorithm=?) ORDER BY timestep DESC LIMIT 1",
                    (algo,),
                ).fetchone()
                if row:
                    latest_evals[algo] = dict(row)
        return {
            "total_runs": total_runs,
            "active_runs": active,
            "completed_runs": completed,
            "failed_runs": failed,
            "total_timesteps": total_steps,
            "by_algorithm": algorithm_counts,
            "best": dict(best) if best else None,
            "latest_tournament": dict(latest_tournament) if latest_tournament else None,
            "latest_evaluations": latest_evals,
        }

    # -- deletion ----------------------------------------------------------
    def delete_match(self, match_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
            conn.commit()

    def delete_run(self, run_id: str) -> Dict[str, Any]:
        """Delete a run's metadata, metrics and checkpoint index.

        Returns the artifact paths so the caller (dashboard) can remove files
        after validating they live under its artifacts root.
        """
        run = self.get_run(run_id)
        if run is None:
            return {"deleted": False, "paths": [], "results_dir": None}
        checkpoint_paths = [c["path"] for c in self.list_checkpoints(run_id, limit=100_000)]
        with self.connect() as conn:
            conn.execute("DELETE FROM metrics WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM checkpoints WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
            conn.commit()
        return {"deleted": True, "paths": checkpoint_paths, "results_dir": run.get("results_dir")}

    def delete_tournament(self, tournament_id: str) -> Dict[str, Any]:
        """Delete a tournament, its matches and return replay/CSV artifact paths."""
        tournament = self.get_tournament(tournament_id)
        if tournament is None:
            return {"deleted": False, "match_ids": [], "paths": [], "csv_path": None}
        matches = self.list_matches(tournament_id=tournament_id, limit=100_000)
        paths = [m["replay_path"] for m in matches if m.get("replay_path")]
        with self.connect() as conn:
            conn.execute("DELETE FROM matches WHERE tournament_id=?", (tournament_id,))
            conn.execute("DELETE FROM tournaments WHERE id=?", (tournament_id,))
            conn.commit()
        return {
            "deleted": True,
            "match_ids": [m["id"] for m in matches],
            "paths": paths,
            "csv_path": tournament.get("csv_path"),
        }
