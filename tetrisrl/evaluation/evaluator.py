"""Match evaluation with paired seeds and side swapping."""

from __future__ import annotations

import random
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..agents import make_agent
from ..environment.versus import MatchResult, VersusMatch
from .metrics import summarize_matches


def play_match(
    agent_a: Any,
    agent_b: Any,
    seed: int,
    max_pieces: int = 1000,
    ruleset: str | Dict[str, Any] = "tetrio_s2",
    record_frames: bool = False,
    record_events: bool = True,
    match_id: str = "",
) -> Dict[str, Any]:
    match = VersusMatch(
        agent_a,
        agent_b,
        ruleset=ruleset,
        seed=seed,
        max_pieces=max_pieces,
        record_frames=record_frames,
        record_events=record_events,
        match_id=match_id,
    )
    result = match.run()
    return {
        "match_id": match_id,
        "seed": seed,
        "winner": result.winner,
        "reason": result.reason,
        "ticks": result.ticks,
        "stats": [s.to_dict() for s in result.stats],
        "agents": {"a": getattr(agent_a, "name", "?"), "b": getattr(agent_b, "name", "?")},
        "replay": result.replay if record_events else {},
        "final_hashes": list(result.final_hashes),
    }


def evaluate_agent(
    agent_factory: Callable[[], Any],
    opponent_spec: str,
    n_matches: int,
    seed: int = 0,
    max_pieces: int = 1000,
    ruleset: str | Dict[str, Any] = "tetrio_s2",
    opponent_kwargs: Optional[Dict[str, Any]] = None,
    progress: Optional[Callable[[int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Evaluate an agent against one opponent over paired seeds.

    The agent plays half the matches as player A and half as player B.  Seed
    ``seed + i`` is shared by the pair so opponent piece sequences are
    comparable across checkpoints.
    """
    matches: List[Dict[str, Any]] = []
    opponent_kwargs = opponent_kwargs or {}
    for i in range(n_matches):
        match_seed = (seed + i) & 0x7FFFFFFF
        agent = agent_factory()
        opponent = make_agent(opponent_spec, seed=match_seed, **opponent_kwargs)
        if i % 2 == 0:
            record = play_match(agent, opponent, match_seed, max_pieces, ruleset)
        else:
            record = play_match(opponent, agent, match_seed, max_pieces, ruleset)
            # Normalise the record so index 0 is always the evaluated agent.
            record["stats"] = [record["stats"][1], record["stats"][0]]
            if record["winner"] is not None:
                record["winner"] = 1 - record["winner"]
            record["agents"] = {"a": record["agents"]["b"], "b": record["agents"]["a"]}
        matches.append(record)
        if progress:
            progress(i + 1, record)
    summary = summarize_matches(matches, perspective="a")
    summary["opponent"] = opponent_spec
    summary["seed"] = seed
    summary["library"] = best_library_notes()
    return {"summary": summary, "matches": matches}


def best_library_notes() -> Dict[str, str]:
    return {
        "heuristic": "in-repo handcrafted evaluation baseline",
        "search": "in-repo beam-search baseline (genuine multi-ply search)",
        "random": "uniform legal-placement baseline",
    }
