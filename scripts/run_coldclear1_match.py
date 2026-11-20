#!/usr/bin/env python
"""Run real Cold Clear (original, C ABI) matches against in-repo baselines.

Examples
--------
The command used for the integration report (10 games per baseline)::

    .venv/bin/python scripts/run_coldclear1_match.py --games 10 \\
        --opponent heuristic --opponent random

Probe whether pending garbage changes the engine's suggestion::

    .venv/bin/python scripts/run_coldclear1_match.py --games 5 \\
        --opponent heuristic --garbage-probe --nodes 20000

The script is honest by construction: it refuses to run when the shared library
is missing, reports the engine's accepted / invalid / fallback / timeout counts,
and never substitutes another agent silently.  If a game crashes, the partial
report is still written and the exit code is non-zero.
"""

from __future__ import annotations

import argparse
import hashlib
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
from tetrisrl.agents.opponents.coldclear1 import (  # noqa: E402
    ColdClear1Agent,
    coldclear1_available,
    coldclear1_binary_path,
)
from tetrisrl.agents.random_agent import RandomAgent  # noqa: E402
from tetrisrl.agents.search_agent import BeamSearchAgent  # noqa: E402
from tetrisrl.environment.ruleset import load_ruleset  # noqa: E402
from tetrisrl.environment.versus import VersusMatch  # noqa: E402

BASELINES = ("heuristic", "random", "search")


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
    totals: Dict[str, int] = {
        "searches": 0,
        "accepted": 0,
        "invalid_moves": 0,
        "fallbacks": 0,
        "timeouts": 0,
        "errors": 0,
        "engine_dead": 0,
        "garbage_probes": 0,
        "garbage_probe_differences": 0,
        "garbage_probe_errors": 0,
        "nodes": 0,
        "incoming_searches": 0,
    }
    errors: List[str] = []

    for game in range(args.games):
        seed = args.seed + game
        engine = ColdClear1Agent(
            library=args.library,
            think_nodes=args.nodes,
            timeout=args.timeout,
            allow_in_tests=True,
            garbage_probe=args.garbage_probe,
            name="coldclear1",
        )
        baseline = make_baseline(baseline_name, seed + 10_000)
        match = VersusMatch(
            engine,
            baseline,
            ruleset=args.ruleset,
            seed=seed,
            max_pieces=args.max_pieces,
            record_frames=False,
            record_events=False,
            match_id=f"coldclear1-vs-{baseline_name}-{seed}",
        )
        t0 = time.time()
        try:
            result = match.run()
        except Exception as exc:  # keep the partial report and fail loudly
            errors.append(f"game {game} seed {seed}: {type(exc).__name__}: {exc}")
            print(f"  game {game + 1:2d} seed={seed:<5d} CRASHED: {type(exc).__name__}: {exc}", flush=True)
            engine.terminate()
            baseline.terminate()
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

        stats = engine.stats
        totals["searches"] += stats.searches
        totals["accepted"] += stats.accepted
        totals["invalid_moves"] += stats.invalid_moves
        totals["fallbacks"] += stats.fallbacks
        totals["timeouts"] += stats.timeouts
        totals["errors"] += stats.errors
        totals["engine_dead"] += stats.engine_dead
        totals["garbage_probes"] += stats.garbage_probes
        totals["garbage_probe_differences"] += stats.garbage_probe_differences
        totals["garbage_probe_errors"] += stats.garbage_probe_errors
        totals["nodes"] += stats.nodes_total
        totals["incoming_searches"] += stats.incoming_searches
        record = {
            "game": game,
            "seed": seed,
            "outcome": outcome,
            "winner": result.winner,
            "reason": result.reason,
            "ticks": result.ticks,
            "elapsed_s": round(elapsed, 3),
            "engine_stats": stats.as_dict(),
            "engine_box": result.stats[0].to_dict(),
            "baseline_box": result.stats[1].to_dict(),
            "invalid_actions_at_versus_layer": list(match.invalid_actions),
        }
        records.append(record)
        print(
            f"  game {game + 1:2d} seed={seed:<5d} {outcome:<5s} reason={result.reason:<22s} "
            f"ticks={result.ticks:<4d} accepted={stats.accepted:<4d} "
            f"invalid={stats.invalid_moves:<3d} fallbacks={stats.fallbacks:<4d} "
            f"timeouts={stats.timeouts:<3d} probes={stats.garbage_probes:<3d}/"
            f"{stats.garbage_probe_differences:<3d} {elapsed:6.2f}s",
            flush=True,
        )
        engine.terminate()
        baseline.terminate()

    games_played = len(records)
    accepted = totals["accepted"]
    fallback_rate = totals["fallbacks"] / max(1, accepted + totals["fallbacks"])
    probe_difference_rate = (
        totals["garbage_probe_differences"] / totals["garbage_probes"]
        if totals["garbage_probes"]
        else None
    )
    return {
        "baseline": baseline_name,
        "ruleset": args.ruleset,
        "games_requested": args.games,
        "games_completed": games_played,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "score": f"{wins}-{losses}-{draws}",
        "win_rate": (wins / games_played) if games_played else None,
        "avg_ticks": (sum(r["ticks"] for r in records) / games_played) if games_played else None,
        "elapsed_s": round(time.time() - started, 2),
        "engine_searches": totals["searches"],
        "engine_accepted": accepted,
        "engine_invalid_moves": totals["invalid_moves"],
        "engine_fallbacks": totals["fallbacks"],
        "fallback_rate": fallback_rate,
        "engine_timeouts": totals["timeouts"],
        "engine_errors": totals["errors"],
        "engine_dead": totals["engine_dead"],
        "engine_nodes_total": totals["nodes"],
        "engine_nodes_per_search": (totals["nodes"] / totals["searches"]) if totals["searches"] else None,
        "garbage_probes": totals["garbage_probes"],
        "garbage_probe_differences": totals["garbage_probe_differences"],
        "garbage_probe_difference_rate": probe_difference_rate,
        "garbage_probe_errors": totals["garbage_probe_errors"],
        "engine_incoming_searches": totals["incoming_searches"],
        "errors": errors,
        "games": records,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--opponent",
        action="append",
        choices=BASELINES,
        default=None,
        help="baseline to play against; repeat for several (default: heuristic and random)",
    )
    parser.add_argument("--games", type=int, default=10, help="games per baseline (paired seeds)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--ruleset", default="tetrio_s2")
    parser.add_argument("--max-pieces", type=int, default=400)
    parser.add_argument("--nodes", type=int, default=20_000, help="CCOptions.min_nodes per decision")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--library", default=None, help="path to libcold_clear.so")
    parser.add_argument(
        "--garbage-probe",
        action="store_true",
        help="also search with incoming=0 and count changed suggestions (doubles work while garbage is pending)",
    )
    parser.add_argument("--json", default=None, help="output JSON path (default results/coldclear1_match_<ts>.json)")
    args = parser.parse_args(argv)
    opponents = args.opponent or ["heuristic", "random"]

    load_ruleset(args.ruleset)  # fail early on a bad ruleset name
    library = coldclear1_binary_path(args.library)
    if not coldclear1_available(library):
        print(
            f"ERROR: Cold Clear library not found at {library}\n"
            "Build it with:  (cd third_party/cold-clear && cargo build --release -p c-api)",
            file=sys.stderr,
        )
        return 2

    commit = git_commit(REPO_ROOT / "third_party" / "cold-clear")
    binary_hash = sha256(library)
    print("=" * 82)
    print("Engine:    Cold Clear (original) via C ABI, dynamically linked cdylib")
    print(f"Library:   {library}")
    print(f"Commit:    {commit or 'unknown'}")
    print(f"SHA-256:   {binary_hash}")
    print(f"Ruleset:   {args.ruleset}   max_pieces={args.max_pieces}   nodes={args.nodes}   timeout={args.timeout}s")
    print("Scope:     Cold Clear only suggests placements. tetrisrl owns attack, garbage,")
    print("           cancellation, B2B charging and Surge. Pending garbage is passed via")
    print("           cc_request_next_move(incoming); the engine has no Season 2 model.")
    print("=" * 82)

    payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "coldclear1",
        "engine_commit": commit,
        "engine_library": str(library),
        "engine_library_sha256": binary_hash,
        "args": vars(args),
        "series": [],
    }
    exit_code = 0
    for baseline_name in opponents:
        print(f"\n--- Cold Clear 1 (C ABI) vs {baseline_name} ---", flush=True)
        summary = run_series(args, baseline_name)
        payload["series"].append(summary)
        differences = summary["garbage_probe_differences"]
        probes = summary["garbage_probes"]
        print(
            f"  SUMMARY vs {baseline_name}: {summary['score']} "
            f"({(summary['win_rate'] or 0) * 100:.1f}% wins) over {summary['games_completed']} games; "
            f"engine fallbacks {summary['engine_fallbacks']} "
            f"(rate {summary['fallback_rate'] * 100:.2f}%); "
            f"garbage probes {differences}/{probes} changed suggestion"
        )
        if summary["errors"]:
            exit_code = 1
            for error in summary["errors"]:
                print(f"  ERROR: {error}")

    output = (
        Path(args.json)
        if args.json
        else REPO_ROOT / "results" / f"coldclear1_match_{int(time.time())}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nJSON report: {output}")

    if any(series["games_completed"] == 0 for series in payload["series"]):
        print("No games completed; this is NOT an integration result.", file=sys.stderr)
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
