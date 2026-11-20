#!/usr/bin/env python
"""Run real external-engine matches against the in-repo baselines.

Examples
--------
Cold Clear 2 vs the heuristic and random baselines, 10 paired-seed games each::

    .venv/bin/python scripts/external_match.py --opponent coldclear --games 10 --seed 0

Cold Clear 2 vs only the heuristic, with a longer think budget::

    .venv/bin/python scripts/external_match.py --opponent coldclear --vs heuristic \\
        --games 5 --think-ms 100 --max-pieces 300

Adapter plumbing check without the external engine (mock bot, not a benchmark)::

    .venv/bin/python scripts/external_match.py --opponent mock --games 2 --max-pieces 20

The script is honest by construction: it reports the engine's accepted /
invalid / fallback counts, and if Cold Clear 2 is not built it exits with an
error instead of silently substituting another agent.
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
from tetrisrl.agents.opponents import (  # noqa: E402
    TBPAgent,
    coldclear_available,
    coldclear_binary_path,
)
from tetrisrl.agents.random_agent import RandomAgent  # noqa: E402
from tetrisrl.agents.search_agent import BeamSearchAgent  # noqa: E402
from tetrisrl.environment.ruleset import load_ruleset  # noqa: E402
from tetrisrl.environment.versus import VersusMatch  # noqa: E402

BASELINES = ("heuristic", "random", "search")
OPPONENTS = ("coldclear", "mock")


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


def make_engine_agent(args: argparse.Namespace) -> TBPAgent:
    if args.opponent == "coldclear":
        binary = coldclear_binary_path(args.binary)
        if not coldclear_available(binary):
            raise SystemExit(
                f"Cold Clear 2 binary not found/executable at {binary}\n"
                "Build it first:  (cd third_party/cold-clear-2 && cargo build --release)"
            )
        return TBPAgent(
            binary=binary,
            config_path=args.config,
            think_time=args.think_ms / 1000.0,
            timeout=args.timeout,
            name="coldclear",
        )
    command = [
        sys.executable,
        "-m",
        "tetrisrl.agents.opponents.mock_bot",
        "--mode",
        "drop",
        "--empty-first",
    ]
    return TBPAgent(
        command=command,
        think_time=args.think_ms / 1000.0,
        timeout=max(1.0, args.timeout),
        allow_in_tests=True,
        name="mock",
    )


def make_baseline(name: str, seed: int) -> Any:
    if name == "heuristic":
        return HeuristicAgent(seed=seed)
    if name == "random":
        return RandomAgent(seed=seed)
    if name == "search":
        return BeamSearchAgent(depth=2, beam_width=10, seed=seed)
    raise SystemExit(f"unknown baseline {name!r}; choose from {BASELINES}")


def run_series(args: argparse.Namespace, baseline_name: str) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    wins = losses = draws = 0
    started = time.time()
    engine_fallbacks = 0
    engine_invalid = 0
    engine_accepted = 0
    engine_suggestions = 0
    engine_nodes = 0
    total_ticks = 0
    total_pieces = 0
    errors: List[str] = []

    for game in range(args.games):
        seed = args.seed + game
        engine_agent = make_engine_agent(args)
        baseline = make_baseline(baseline_name, seed + 10_000)
        match = VersusMatch(
            engine_agent,
            baseline,
            ruleset=args.ruleset,
            seed=seed,
            max_pieces=args.max_pieces,
            record_frames=False,
            record_events=False,
            match_id=f"{args.opponent}-vs-{baseline_name}-{seed}",
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
        engine_nodes += stats.nodes_total
        total_ticks += result.ticks
        total_pieces += result.stats[0].pieces

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
            "engine_box": result.stats[0].to_dict(),
            "baseline_box": result.stats[1].to_dict(),
            "invalid_actions_at_versus_layer": list(match.invalid_actions),
            "ruleset": result.replay.get("ruleset", {}).get("name"),
        }
        records.append(record)
        print(
            f"  game {game + 1:2d} seed={seed:<5d} {outcome:<5s} reason={result.reason:<22s} "
            f"ticks={result.ticks:<4d} accepted={stats.accepted:<4d} "
            f"invalid={stats.invalid_suggestions:<3d} fallbacks={stats.fallbacks:<4d} "
            f"topout={result.stats[1].top_out_reason or '-':<16s} {elapsed:6.2f}s",
            flush=True,
        )
        engine_agent.terminate()
        baseline.terminate()

    games_played = len(records)
    summary = {
        "opponent": args.opponent,
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
        "avg_engine_pieces": (total_pieces / games_played) if games_played else None,
        "elapsed_s": round(time.time() - started, 2),
        "engine_suggestions": engine_suggestions,
        "engine_accepted": engine_accepted,
        "engine_nodes_total": engine_nodes,
        "engine_nodes_per_move": (engine_nodes / engine_suggestions) if engine_suggestions else None,
        "engine_invalid_suggestions": engine_invalid,
        "engine_fallbacks": engine_fallbacks,
        "fallback_rate": (engine_fallbacks / max(1, engine_accepted + engine_fallbacks)),
        "errors": errors,
        "games": records,
    }
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--opponent", choices=OPPONENTS, default="coldclear")
    parser.add_argument("--vs", nargs="+", choices=BASELINES, default=["heuristic", "random"])
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--ruleset", default="tetrio_s2")
    parser.add_argument("--max-pieces", type=int, default=400)
    parser.add_argument("--think-ms", type=float, default=60.0, help="Cold Clear 2 search budget per piece")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--binary", default=None, help="path to the cold-clear-2 executable")
    parser.add_argument("--config", default=None, help="optional Cold Clear 2 JSON config")
    parser.add_argument("--json", default=None, help="output JSON path (default results/external_match_<ts>.json)")
    args = parser.parse_args(argv)

    load_ruleset(args.ruleset)  # fail early on a bad ruleset name
    if args.opponent == "coldclear" and not coldclear_available(args.binary):
        print(
            f"ERROR: Cold Clear 2 binary not found at {coldclear_binary_path(args.binary)}\n"
            "Build it with:  (cd third_party/cold-clear-2 && cargo build --release)",
            file=sys.stderr,
        )
        return 2

    commit = git_commit(REPO_ROOT / "third_party" / "cold-clear-2")
    label = "Cold Clear 2 (TBP subprocess)" if args.opponent == "coldclear" else "MOCK TBP bot (plumbing only, NOT a benchmark)"
    print("=" * 78)
    print(f"Engine:    {label}")
    print(f"Commit:    {commit or 'unknown'}")
    print(f"Ruleset:   {args.ruleset}   max_pieces={args.max_pieces}   think_ms={args.think_ms}")
    print("Scope:     Cold Clear 2 only suggests placements. tetrisrl owns attack,")
    print("           garbage, cancellation, B2B charging and surge; the engine has")
    print("           no TETR.IO Season 2 charging model and no TBP garbage channel.")
    print("=" * 78)

    payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": args.opponent,
        "engine_commit": commit,
        "engine_binary": str(coldclear_binary_path(args.binary)) if args.opponent == "coldclear" else "mock",
        "args": vars(args),
        "series": [],
    }
    exit_code = 0
    for baseline_name in args.vs:
        print(f"\n--- {label} vs {baseline_name} ---", flush=True)
        summary = run_series(args, baseline_name)
        payload["series"].append(summary)
        print(
            f"  SUMMARY vs {baseline_name}: {summary['score']} "
            f"({summary['win_rate'] * 100 if summary['win_rate'] is not None else 0:.1f}% wins) "
            f"over {summary['games_completed']} games; "
            f"engine fallbacks {summary['engine_fallbacks']} "
            f"(rate {summary['fallback_rate'] * 100:.1f}%)"
        )
        if summary["errors"]:
            exit_code = 1
            for error in summary["errors"]:
                print(f"  ERROR: {error}")

    output = Path(args.json) if args.json else REPO_ROOT / "results" / f"external_match_{args.opponent}_{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nJSON report: {output}")

    if any(series["games_completed"] == 0 for series in payload["series"]):
        print("No games completed; this is NOT an integration result.", file=sys.stderr)
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
