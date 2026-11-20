#!/usr/bin/env python
"""Run real RIKU0804/tetris-ai matches against the in-repo baselines.

The RIKU Rust core is driven as a subprocess over the Tetris Bot Protocol; this
script starts one engine process per game, plays ``--games`` paired-seed games
against each requested baseline under the project's TETR.IO Season 2 ruleset,
and reports the engine's accepted/invalid/fallback counters alongside the arena
statistics.

Examples
--------
The two commands used in ``docs/integration_riku.md``::

    .venv/bin/python scripts/run_riku_match.py --games 10 --opponent heuristic
    .venv/bin/python scripts/run_riku_match.py --games 10 --opponent random

A quick plumbing check (5 games, 120-piece cap, both baselines)::

    .venv/bin/python scripts/run_riku_match.py --games 5 --max-pieces 120 \\
        --opponent heuristic random

The script is honest by construction: it exits with an error when the RIKU
binary is missing, never substitutes another agent for the engine, and reports
every heuristic fallback (placements our hard-drop action space cannot express).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tetrisrl.agents.heuristic_agent import HeuristicAgent  # noqa: E402
from tetrisrl.agents.opponents.riku import (  # noqa: E402
    RIKU_COMMIT,
    RikuAgent,
    riku_available,
    riku_binary_path,
    riku_weights_path,
)
from tetrisrl.agents.random_agent import RandomAgent  # noqa: E402
from tetrisrl.environment.versus import VersusMatch  # noqa: E402

BASELINES = ("heuristic", "random")


def git_commit(path: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def make_baseline(name: str, seed: int) -> Any:
    if name == "heuristic":
        return HeuristicAgent(seed=seed)
    if name == "random":
        return RandomAgent(seed=seed)
    raise SystemExit(f"unknown baseline {name!r}; choose from {BASELINES}")


def run_series(args: argparse.Namespace, baseline_name: str) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    wins = losses = draws = 0
    started = time.time()
    engine_fallbacks = 0
    engine_invalid = 0
    engine_accepted = 0
    engine_suggestions = 0
    total_ticks = 0
    totals = {
        "pieces": [0, 0],
        "lines": [0, 0],
        "attack": [0, 0],
        "attack_sent": [0, 0],
        "garbage_received": [0, 0],
        "garbage_inserted": [0, 0],
        "four_lines": [0, 0],
        "tspins": [0, 0],
        "max_combo": [0, 0],
        "max_b2b": [0, 0],
        "holds": [0, 0],
        "final_height": [0, 0],
        "final_holes": [0, 0],
    }
    errors: List[str] = []
    first_engine_info: Dict[str, Any] = {}

    for game in range(args.games):
        seed = args.seed + game
        engine_agent = RikuAgent(
            binary=args.binary,
            weights=args.weights,
            width=args.width,
            depth=args.depth,
            think_time=0.0,
            timeout=args.timeout,
        )
        baseline = make_baseline(baseline_name, seed + 10_000)
        match = VersusMatch(
            engine_agent,
            baseline,
            ruleset=args.ruleset,
            seed=seed,
            max_pieces=args.max_pieces,
            record_frames=False,
            record_events=False,
            match_id=f"riku-vs-{baseline_name}-{seed}",
        )
        t0 = time.time()
        try:
            result = match.run()
        except Exception as exc:  # keep the partial report and fail loudly
            errors.append(f"game {game} seed {seed}: {type(exc).__name__}: {exc}")
            print(f"  game {game + 1:2d} seed={seed:<5d} CRASHED: {type(exc).__name__}: {exc}", flush=True)
            try:
                engine_agent.terminate()
            except Exception:
                pass
            continue
        elapsed = time.time() - t0

        if result.winner == 0:
            outcome = "win"
            wins += 1
        elif result.winner == 1:
            outcome = "loss"
            losses += 1
        else:
            outcome = "draw"
            draws += 1

        stats = engine_agent.stats
        engine_fallbacks += stats.fallbacks
        engine_invalid += stats.invalid_suggestions
        engine_accepted += stats.accepted
        engine_suggestions += stats.suggestions
        total_ticks += result.ticks
        if not first_engine_info:
            first_engine_info = dict(engine_agent.engine_info)
        for idx, player_stats in enumerate(result.stats):
            for field in totals:
                totals[field][idx] += getattr(player_stats, field)

        record = {
            "game": game,
            "seed": seed,
            "outcome": outcome,
            "winner": result.winner,
            "reason": result.reason,
            "ticks": result.ticks,
            "elapsed_s": round(elapsed, 3),
            "engine_stats": stats.as_dict(),
            "engine_info": engine_agent.engine_info,
            "engine_moves_accepted": stats.accepted,
            "engine_moves_fallback": stats.fallbacks,
            "engine_box": result.stats[0].to_dict(),
            "baseline_box": result.stats[1].to_dict(),
            "invalid_actions_at_versus_layer": list(match.invalid_actions),
        }
        records.append(record)
        print(
            f"  game {game + 1:2d} seed={seed:<5d} {outcome:<5s} reason={result.reason:<22s} "
            f"ticks={result.ticks:<4d} accepted={stats.accepted:<4d} "
            f"fallbacks={stats.fallbacks:<4d} invalid={stats.invalid_suggestions:<3d} "
            f"topout={result.stats[1].top_out_reason or '-':<16s} {elapsed:6.2f}s",
            flush=True,
        )
        engine_agent.terminate()
        baseline.terminate()

    games_played = len(records)
    pieces = [v / games_played for v in totals["pieces"]] if games_played else [0.0, 0.0]
    summary = {
        "opponent": "riku",
        "baseline": baseline_name,
        "ruleset": args.ruleset,
        "games_requested": args.games,
        "games_completed": games_played,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": (wins / games_played) if games_played else None,
        "score": f"{wins}-{losses}-{draws}",
        "avg_ticks": (total_ticks / games_played) if games_played else None,
        "elapsed_s": round(time.time() - started, 2),
        "engine_suggestions": engine_suggestions,
        "engine_accepted": engine_accepted,
        "engine_invalid_suggestions": engine_invalid,
        "engine_fallbacks": engine_fallbacks,
        "fallback_rate": (engine_fallbacks / max(1, engine_accepted + engine_fallbacks)),
        "mean_answer_latency_ms": (
            sum(r["engine_stats"]["answer_latency_ms"] for r in records) / engine_suggestions
            if engine_suggestions
            else None
        ),
        "engine_info": first_engine_info,
        "per_player_averages": {
            field: [value / games_played for value in values] for field, values in totals.items()
        },
        "engine_mean_pieces": pieces[0],
        "baseline_mean_pieces": pieces[1],
        "errors": errors,
        "games": records,
    }
    print(
        f"  SUMMARY vs {baseline_name}: {wins}-{losses}-{draws} "
        f"({100.0 * wins / max(1, games_played):.1f}% wins) over {games_played} games; "
        f"engine suggestions {engine_suggestions}, accepted {engine_accepted}, "
        f"fallbacks {engine_fallbacks} "
        f"(rate {100.0 * engine_fallbacks / max(1, engine_accepted + engine_fallbacks):.2f}%)",
        flush=True,
    )
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--opponent", nargs="+", choices=BASELINES, default=["heuristic", "random"])
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0, help="first seed; games use seed..seed+games-1")
    parser.add_argument("--ruleset", default="tetrio_s2")
    parser.add_argument("--max-pieces", type=int, default=400)
    parser.add_argument("--timeout", type=float, default=5.0, help="TBP suggestion timeout (seconds)")
    parser.add_argument("--binary", default=None, help="path to the tetris-core executable")
    parser.add_argument("--weights", default=None, help="optional RIKU weights JSON")
    parser.add_argument("--width", type=int, default=16, help="beam width passed to `tetris-core tbp`")
    parser.add_argument("--depth", type=int, default=6, help="lookahead depth passed to `tetris-core tbp`")
    parser.add_argument("--json", default=None, help="output JSON path (default results/riku_match_<ts>.json)")
    args = parser.parse_args(argv)

    binary = riku_binary_path(args.binary)
    if not riku_available(binary):
        raise SystemExit(
            f"RIKU tetris-core binary not found/executable at {binary}\n"
            "Build it first:  (cd third_party/riku-tetris-ai/core-rs && cargo build --release)"
        )
    weights = riku_weights_path(args.weights)
    args.binary = str(binary)
    args.weights = str(weights) if weights else None

    clone = binary.parents[3] if len(binary.parents) > 3 else None
    clone_commit = git_commit(clone) if clone else None
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "RIKU0804/tetris-ai",
        "adapter_commit": RIKU_COMMIT,
        "clone_commit": clone_commit,
        "binary": str(binary),
        "binary_size": binary.stat().st_size,
        "weights": args.weights,
        "beam_width": args.width,
        "beam_depth": args.depth,
        "max_pieces": args.max_pieces,
        "ruleset": args.ruleset,
        "series": [],
    }
    print(f"RIKU engine: {binary}")
    print(f"clone commit: {clone_commit} (adapter verified against {RIKU_COMMIT})")
    print(f"weights: {args.weights}")
    print(f"config: ruleset={args.ruleset} max_pieces={args.max_pieces} width={args.width} depth={args.depth}")

    for baseline in args.opponent:
        print(f"\n--- RIKU (TBP subprocess) vs {baseline} ---", flush=True)
        report["series"].append(run_series(args, baseline))

    if args.json:
        out = Path(args.json)
    else:
        stamp = int(time.time())
        out = REPO_ROOT / "results" / f"riku_match_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\nJSON report: {out}")

    any_error = any(series["errors"] for series in report["series"])
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
