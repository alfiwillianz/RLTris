"""Round-robin tournaments with persistent match records and replays."""

from __future__ import annotations

import csv
import itertools
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..agents import make_agent
from ..environment.versus import VersusMatch
from .evaluator import play_match


def _participant_name(p: Dict[str, Any]) -> str:
    return str(p.get("name") or p.get("spec") or "agent")


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
    pair_index = 0

    for a, b in itertools.combinations(participants, 2):
        name_a, name_b = _participant_name(a), _participant_name(b)
        spec_a, spec_b = a.get("spec", name_a), b.get("spec", name_b)
        for i in range(n_seeds):
            match_seed = (seed + pair_index * 1000 + i) & 0x7FFFFFFF
            swap = i % 2 == 1
            agent_a = make_agent(spec_a, seed=match_seed)
            agent_b = make_agent(spec_b, seed=match_seed + 1)
            if swap:
                agent_a, agent_b, name_a, name_b = agent_b, agent_a, name_b, name_a
            match_id = f"{tournament_id}-{pair_index:03d}-{i}"
            record = play_match(
                agent_a,
                agent_b,
                match_seed,
                max_pieces=max_pieces,
                ruleset=ruleset,
                record_frames=record_frames,
                match_id=match_id,
            )
            record["participants"] = [name_a, name_b]
            replay_path = replay_dir / f"{match_id}.json"
            from .match_replay import save_replay

            save_replay(record["replay"], replay_path)
            record["replay_path"] = str(replay_path)
            winner_name = None if record["winner"] is None else (name_a if record["winner"] == 0 else name_b)
            for idx, name in enumerate((name_a, name_b)):
                s = standings[name]
                s["matches"] += 1
                stats = record["stats"][idx]
                s["attack"] += stats["attack"]
                s["lines"] += stats["lines"]
                s["pieces"] += stats["pieces"]
                s["ticks"] += record["ticks"]
                if winner_name is None:
                    s["draws"] += 1
                elif winner_name == name:
                    s["wins"] += 1
                else:
                    s["losses"] += 1
            if manager is not None:
                try:
                    manager.add_match(
                        match_id=match_id,
                        agent_a=name_a,
                        agent_b=name_b,
                        winner=record["winner"],
                        reason=record["reason"],
                        ticks=record["ticks"],
                        seed=match_seed,
                        replay_path=str(replay_path),
                        stats={"stats": record["stats"], "agents": [name_a, name_b]},
                        tournament_id=tournament_id,
                    )
                except Exception:
                    pass
            matches.append(
                {
                    "match_id": match_id,
                    "seed": match_seed,
                    "a": name_a,
                    "b": name_b,
                    "winner": winner_name,
                    "reason": record["reason"],
                    "ticks": record["ticks"],
                    "replay_path": str(replay_path),
                    "stats": record["stats"],
                }
            )
            pair_index += 1
            if progress:
                progress(len(matches), matches[-1])

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
