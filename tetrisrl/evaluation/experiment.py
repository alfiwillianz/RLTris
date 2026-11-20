"""Experiment helpers: evaluation persistence and tournament orchestration."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .tournament import export_csv, run_round_robin
from ..training.experiment_manager import ExperimentManager


def save_evaluation(result: Dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    return path


def default_participants(extra: Optional[Sequence[Dict[str, str]]] = None) -> List[Dict[str, str]]:
    participants = [
        {"name": "random", "spec": "random"},
        {"name": "heuristic", "spec": "heuristic"},
        {"name": "search", "spec": "search"},
    ]
    if extra:
        participants.extend(extra)
    return participants


def run_tournament_and_persist(
    participants: Sequence[Dict[str, Any]],
    n_seeds: int = 3,
    max_pieces: int = 1000,
    ruleset: str = "tetrio_s2",
    seed: int = 0,
    name: str = "round-robin",
    db: Optional[str] = None,
    replay_dir: str = "results/replays",
    csv_path: Optional[str] = None,
    workers: int = 1,
) -> Dict[str, Any]:
    manager = ExperimentManager(db)
    tournament_id = manager.create_tournament(name, {"participants": list(participants), "n_seeds": n_seeds, "max_pieces": max_pieces, "ruleset": ruleset})
    try:
        results = run_round_robin(
            participants,
            n_seeds=n_seeds,
            max_pieces=max_pieces,
            ruleset=ruleset,
            seed=seed,
            replay_dir=replay_dir,
            tournament_id=tournament_id,
            manager=manager,
            workers=workers,
        )
        out_csv = csv_path or f"results/tournaments/{tournament_id}.csv"
        export_csv(results, out_csv)
        results["tournament_id"] = tournament_id
        results["csv_path"] = out_csv
        manager.update_tournament(tournament_id, status="completed", results={"standings": results["standings"], "matches": results["matches"]}, csv_path=out_csv)
        return results
    except Exception as exc:
        manager.update_tournament(tournament_id, status="failed", results={"error": str(exc)})
        raise
