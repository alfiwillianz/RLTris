"""Round-robin tournaments with persistent match records and replays."""

from __future__ import annotations

import csv
import itertools
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..agents import make_agent
from ..environment.versus import VersusMatch
from .evaluator import play_match


def _participant_name(p: Dict[str, Any]) -> str:
    return str(p.get("name") or p.get("spec") or "agent")


def _play_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Worker: build agents, play one match, write its replay, return a record.

    Matches are independent and seeded, so running them in separate processes
    is deterministic.  Replay files are written in the worker (large payloads
    never cross the process boundary); SQLite writes stay in the parent.
    """
    from .evaluator import play_match
    from ..agents import make_agent
    from .match_replay import save_replay

    try:
        agent_a = make_agent(task["spec_a"], seed=task["seed"])
        agent_b = make_agent(task["spec_b"], seed=task["seed"] + 1)
        record = play_match(
            agent_a,
            agent_b,
            task["seed"],
            max_pieces=task["max_pieces"],
            ruleset=task["ruleset"],
            record_frames=task["record_frames"],
            match_id=task["match_id"],
        )
        save_replay(record["replay"], task["replay_path"])
        record["replay_path"] = task["replay_path"]
        record["participants"] = task["participants"]
        record["seed"] = task["seed"]
        record.pop("replay", None)
        return record
    except Exception as exc:  # surfaced to the parent as a failed match
        return {
            "match_id": task["match_id"],
            "seed": task["seed"],
            "participants": task["participants"],
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_round_robin(
    participants: Sequence[Dict[str, Any]],
    n_seeds: int = 3,
    max_pieces: int = 1000,
    ruleset: str = "tetrio_s2",
    seed: int = 0,
    replay_dir: str = "results/replays",
    tournament_id: str = "",
    manager: Any = None,
    record_frames: bool = True,
    progress: Optional[Any] = None,
    workers: int = 1,
) -> Dict[str, Any]:
    """Play every participant against every other participant.

    Each pairing plays ``n_seeds`` matches; the sides are swapped on odd matches
    so the first-player tick order does not systematically favour one agent.
    """
    replay_dir = Path(replay_dir)
    replay_dir.mkdir(parents=True, exist_ok=True)
    names = [_participant_name(p) for p in participants]
    standings = {name: {"wins": 0, "losses": 0, "draws": 0, "matches": 0, "attack": 0, "lines": 0, "pieces": 0, "ticks": 0} for name in names}
    matches: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    pair_index = 0

    for a, b in itertools.combinations(participants, 2):
        name_a, name_b = _participant_name(a), _participant_name(b)
        spec_a, spec_b = a.get("spec", name_a), b.get("spec", name_b)
        for i in range(n_seeds):
            match_seed = (seed + pair_index * 1000 + i) & 0x7FFFFFFF
            swap = i % 2 == 1
            left_name, right_name = (name_b, name_a) if swap else (name_a, name_b)
            left_spec, right_spec = (spec_b, spec_a) if swap else (spec_a, spec_b)
            match_id = f"{tournament_id}-{pair_index:03d}-{i}"
            replay_path = replay_dir / f"{match_id}.json"
            tasks.append(
                {
                    "spec_a": left_spec,
                    "spec_b": right_spec,
                    "participants": [left_name, right_name],
                    "seed": match_seed,
                    "max_pieces": max_pieces,
                    "ruleset": ruleset,
                    "record_frames": record_frames,
                    "match_id": match_id,
                    "replay_path": str(replay_path),
                }
            )
            pair_index += 1

    workers = max(1, min(int(workers or 1), len(tasks) or 1))
    if workers == 1:
        records = [_play_task(task) for task in tasks]
    else:
        # spawn (not fork) keeps CUDA/threads in the parent untouched; the
        # worker only imports the CPU simulation and engines.
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork")) as pool:
            records = list(pool.map(_play_task, tasks))

    for record in records:
        if "error" in record:
            matches.append(record)
            continue
        name_a, name_b = record["participants"]
        winner_name = None if record["winner"] is None else (name_a if record["winner"] == 0 else name_b)
        for idx, name in enumerate((name_a, name_b)):
            s_row = standings[name]
            stats = record["stats"][idx]
            s_row["matches"] += 1
            s_row["attack"] += stats["attack"]
            s_row["lines"] += stats["lines"]
            s_row["pieces"] += stats["pieces"]
            s_row["ticks"] += record["ticks"]
            if winner_name is None:
                s_row["draws"] += 1
            elif winner_name == name:
                s_row["wins"] += 1
            else:
                s_row["losses"] += 1
        if manager is not None:
            try:
                manager.add_match(
                    match_id=record["match_id"],
                    agent_a=name_a,
                    agent_b=name_b,
                    winner=record["winner"],
                    reason=record["reason"],
                    ticks=record["ticks"],
                    seed=record["seed"],
                    replay_path=record["replay_path"],
                    stats={"stats": record["stats"], "agents": [name_a, name_b]},
                    tournament_id=tournament_id,
                )
            except Exception:
                pass
        matches.append(record)
        if progress:
            progress(len(matches), record)

    table = []
    for name, s in standings.items():
        total = s["matches"] or 1
        table.append(
            {
                "name": name,
                **s,
                "win_rate": s["wins"] / total,
                "attack_per_minute": s["attack"] / max(1e-9, s["ticks"] / 60.0),
                "lines_per_match": s["lines"] / total,
            }
        )
    table.sort(key=lambda r: (r["win_rate"], r["wins"]), reverse=True)
    return {"standings": table, "matches": matches}


def export_csv(results: Dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "matches", "wins", "losses", "draws", "win_rate", "attack_per_minute", "lines_per_match"]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in results.get("standings", []):
            writer.writerow(row)
    return path
