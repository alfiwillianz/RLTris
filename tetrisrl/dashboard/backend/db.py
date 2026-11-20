"""Dashboard persistence helpers.

The SQLite schema is owned exclusively by
:class:`tetrisrl.training.experiment_manager.ExperimentManager`.  This module is
deliberately thin: it re-exports the manager and adds a few *read-only* helpers
that the dashboard needs (metric downsampling and a cursor-based live feed).

No table is created here and no schema is duplicated.  If a query is not
available on ``ExperimentManager`` yet, the small helper below reads the table
through ``ExperimentManager.connect()`` instead of opening its own connection or
changing the schema owner.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ...training.experiment_manager import (  # noqa: F401  (re-exported)
    DEFAULT_DB,
    ExperimentManager,
    default_db_path,
    utcnow,
)

Series = List[Tuple[int, float]]


def downsample_series(series: Sequence[Tuple[int, float]], max_points: Optional[int]) -> List[Tuple[int, float]]:
    """Downsample a time series while keeping its first and last samples.

    Returns at most ``max_points`` points.  ``max_points`` of ``None`` or a
    value larger than the series length returns a copy unchanged.
    """
    points = [(int(t), float(v)) for t, v in series]
    if not max_points or max_points <= 0 or len(points) <= max_points:
        return points
    if max_points == 1:
        return [points[-1]]
    n = len(points)
    out: List[Tuple[int, float]] = []
    for i in range(max_points):
        idx = int(i * n / max_points)
        if idx >= n:
            idx = n - 1
        out.append(points[idx])
    # Always expose the most recent value: it is the one users care about.
    if out[-1][0] != points[-1][0]:
        out[-1] = points[-1]
    return out


def downsample_metrics(
    metrics: Dict[str, Sequence[Tuple[int, float]]],
    max_points: Optional[int],
) -> Dict[str, List[Tuple[int, float]]]:
    return {name: downsample_series(series, max_points) for name, series in metrics.items()}


def coerce_series(raw: Iterable[Iterable[Any]]) -> Series:
    return [(int(t), float(v)) for t, v in raw]


class DashboardDB:
    """Wrapper exposing ``ExperimentManager`` plus dashboard read helpers.

    Methods not defined here are delegated to the underlying manager, so callers
    can use ``db.get_run(...)``, ``db.log_metrics(...)`` etc.  The wrapper makes
    the dependency explicit and keeps the API layer free of raw SQL.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.manager = ExperimentManager(db_path)
        self.db_path = self.manager.db_path

    # -- delegation --------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        return getattr(self.manager, name)

    def close(self) -> None:  # pragma: no cover - connections are per-call
        return None

    # -- dashboard-only reads ---------------------------------------------
    def metrics_since(
        self,
        run_id: str,
        after_timestep: int = -1,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Read metric rows newer than ``after_timestep`` (live-feed cursor).

        Read-only helper; the schema is still defined by ``ExperimentManager``.
        """
        with self.manager.connect() as conn:
            rows = conn.execute(
                "SELECT timestep, name, value FROM metrics "
                "WHERE run_id=? AND timestep>? ORDER BY timestep ASC, name ASC LIMIT ?",
                (run_id, int(after_timestep), int(limit)),
            ).fetchall()
        return [{"timestep": int(r["timestep"]), "name": r["name"], "value": float(r["value"])} for r in rows]

    def latest_timestep(self, run_id: str) -> int:
        with self.manager.connect() as conn:
            row = conn.execute("SELECT MAX(timestep) AS t FROM metrics WHERE run_id=?", (run_id,)).fetchone()
        return int(row["t"]) if row and row["t"] is not None else -1


__all__ = [
    "DEFAULT_DB",
    "DashboardDB",
    "ExperimentManager",
    "Series",
    "coerce_series",
    "default_db_path",
    "downsample_metrics",
    "downsample_series",
    "utcnow",
]
