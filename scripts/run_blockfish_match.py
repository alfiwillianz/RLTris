#!/usr/bin/env python
"""Run real matches with blockfish against the in-repo baselines.

**Blockfish is a cheese / downstacking specialist, not a versus bot.**  Its
objective is to clear a garbage stack in as few pieces as possible.  It has no
attack, no B2B charging, no Surge and no TETR.IO Season 2 model.  Results from
this script are reported for adapter validation and downstacking behaviour,
never as a competitive versus benchmark.

Examples
--------
Best-effort match against the heuristic and random baselines (the task's
``max_pieces=200`` setting)::

    .venv/bin/python scripts/run_blockfish_match.py \\
        --vs heuristic random --games 5 --max-pieces 200 --seed 0

One longer game with a bigger search budget::

    .venv/bin/python scripts/run_blockfish_match.py \\
        --vs heuristic --games 1 --max-pieces 200 --node-limit 100000

The script fails loudly if the pinned service binary is not built, and also
fails if blockfish never produced a mappable placement (so an adapter that has
only ever fallen back to the heuristic is never reported as "integrated").
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
from tetrisrl.agents.opponents.blockfish import (  # noqa: E402
    BLOCKFISH_COMMIT,
    BlockfishAgent,
    blockfish_available,
    blockfish_binary_path,
)
from tetrisrl.agents.random_agent import RandomAgent  # noqa: E402
from tetrisrl.environment.ruleset import load_ruleset  # noqa: E402
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
    engine_fallbacks = engine_invalid = engine_accepted = engine_suggestions = 0
    engine_approx = engine_nodes = 0
    total_ticks = total_pieces = 0
    errors: List[str] = []

    for game in range(args.games):
        seed = args.seed + game
        engine_agent = BlockfishAgent(
            binary=args.binary,
            node_limit=args.node_limit,
            timeout=args.timeout,
            name="blockfish",
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
            match_id=f"blockfish-vs-{baseline_name}-{seed}",
        )
        t0 = time.time()
        try:
            result = match.run()
        except Exception as exc:  # keep the partial report and fail loudly
            errors.append(f"game {game} seed {seed}: {type(exc).__name__}: {exc}")
            print(
                f"  game {game + 1:2d} seed={seed:<5d} CRASHED: {type(exc).__name__}: {exc}",
                flush=True,
            )
            try:
                engine_agent.terminate()
                baseline.terminate()
            except Exception:
                pass
            continue
        elapsed = time.time() - t0

        outcome = {0: "win", 1: "loss", None: "draw"}[result.winner]
        if result.winner == 0:
            wins += 1
        elif result.winner == 1:
            losses += 1
        else:
            draws += 1

        stats = engine_agent.stats
        engine_fallbacks += stats.fallbacks
        engine_invalid += stats.rejected
        engine_accepted += stats.accepted
        engine_approx += stats.accepted_approx
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
        }
        records.append(record)
        print(
            f"  game {game + 1:2d} seed={seed:<5d} {outcome:<5s} reason={result.reason:<22s} "
            f"ticks={result.ticks:<4d} accepted={stats.accepted:<4d} "
            f"approx={stats.accepted_approx:<3d} rejected={stats.rejected:<3d} "
            f"fallbacks={stats.fallbacks:<4d} {elapsed:6.2f}s",
            flush=True,
        )
        engine_agent.terminate()
        baseline.terminate()

    games_played = len(records)
    return {
        "opponent": "blockfish",
        "specialist": "cheese",
        "versus_benchmark": False,
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
        "engine_accepted_approx": engine_approx,
        "engine_nodes_total": engine_nodes,
        "engine_nodes_per_move": (engine_nodes / engine_suggestions) if engine_suggestions else None,
        "engine_rejected": engine_invalid,
        "engine_fallbacks": engine_fallbacks,
        "fallback_rate": (engine_fallbacks / max(1, engine_accepted + engine_fallbacks)),
        "errors": errors,
        "games": records,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--vs", nargs="+", choices=BASELINES, default=["heuristic", "random"])
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--ruleset", default="tetrio_s2")
    parser.add_argument("--max-pieces", type=int, default=200)
    parser.add_argument(
        "--node-limit", type=int, default=20_000, help="blockfish search node budget per piece"
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--binary", default=None, help="path to the blockfish service binary")
    parser.add_argument("--json", default=None, help="optional output JSON path")
    args = parser.parse_args(argv)

    load_ruleset(args.ruleset)  # fail early on a bad ruleset name
    binary = blockfish_binary_path(args.binary)
    if not blockfish_available(binary):
        print(
            f"ERROR: blockfish service binary not found at {binary}\n"
            "Build it with:  (cd third_party/blockfish && "
            "cargo build --release -p blockfish --features service)",
            file=sys.stderr,
        )
        return 2

    commit = git_commit(REPO_ROOT / "third_party" / "blockfish")
    print("=" * 78)
    print("Engine:    blockfish (LGPL-2.1, subprocess/protobuf stdio)")
    print(f"Commit:    {commit or BLOCKFISH_COMMIT}")
    print(f"Ruleset:   {args.ruleset}   max_pieces={args.max_pieces}   node_limit={args.node_limit}")
    print("Specialist: cheese / downstacking ONLY.  Blockfish has no versus model,")
    print("            no attack, no B2B charging, no Surge and no TETR.IO Season 2")
    print("            mechanics.  These matches validate the adapter; they are NOT")
    print("            a competitive versus benchmark.")
    print("=" * 78)

    payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "blockfish",
        "commit": commit,
        "specialist": "cheese",
        "versus_benchmark": False,
        "binary": str(binary),
        "node_limit": args.node_limit,
        "max_pieces": args.max_pieces,
        "ruleset": args.ruleset,
        "series": [],
    }

    for baseline in args.vs:
        print(f"\n-- blockfish vs {baseline} --")
        summary = run_series(args, baseline)
        payload["series"].append(summary)
        wr = summary["win_rate"]
        print(
            f"  summary: {summary['score']}  (win_rate={wr:.2f})  "
            f"accepted={summary['engine_accepted']} "
            f"approx={summary['engine_accepted_approx']} "
            f"rejected={summary['engine_rejected']} "
            f"fallbacks={summary['engine_fallbacks']}  "
            f"fallback_rate={summary['fallback_rate']:.3f}  "
            f"elapsed={summary['elapsed_s']}s"
        )

    if args.json:
        out_path = Path(args.json).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path}")

    total_accepted = sum(s["engine_accepted"] for s in payload["series"])
    if total_accepted == 0:
        print(
            "\nERROR: blockfish never produced a placement mapped to our action space; "
            "the adapter was not exercised as an external opponent.",
            file=sys.stderr,
        )
        return 3
    print(
        "\nReminder: blockfish is a cheese/downstack specialist.  Do not report these "
        "results as a competitive versus benchmark."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
