"""Deterministic match replay storage and verification.

A replay contains everything needed to play a match back **without** rerunning
neural inference: the ruleset, seeds, per-tick actions/events, and (optionally)
per-tick board snapshots for both players.  Verification re-simulates the
recorded actions and compares final board hashes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ..environment.versus import verify_replay as _verify


def save_replay(replay: Dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(replay, separators=(",", ":"))
    path.write_text(payload)
    return path


def load_replay(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text())


def verify_replay_file(path: str | Path) -> bool:
    return _verify(load_replay(path))


def replay_summary(replay: Dict[str, Any]) -> Dict[str, Any]:
    result = replay.get("result", {})
    return {
        "match_id": replay.get("match_id", ""),
        "agents": replay.get("agents", {}),
        "winner": result.get("winner"),
        "reason": result.get("reason"),
        "ticks": result.get("ticks", len(replay.get("ticks", []))),
        "stats": result.get("stats", []),
        "frames": len(replay.get("frames", [])),
    }


def replay_frames(replay: Dict[str, Any]) -> list:
    return replay.get("frames", [])
