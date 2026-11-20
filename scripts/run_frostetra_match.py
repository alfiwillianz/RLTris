#!/usr/bin/env python
"""Run real frostetra (SBP/1) matches against in-repo baselines.

Examples
--------
The command used for the integration report (10 games per baseline)::

    .venv/bin/python scripts/run_frostetra_match.py --games 10 \\
        --opponent heuristic --opponent random --max-pieces 300

The script is honest by construction: it refuses to run when the frostetra
binary is missing, reports accepted / invalid / fallback / timeout counts, and
never substitutes another agent silently.  A crashed game is reported and the
exit code is non-zero, but the partial JSON report is still written.

What the numbers do and do not show
-----------------------------------
* The engine only suggests a placement.  ``tetrisrl`` owns attack, garbage,
  cancellation, B2B charging and Surge; none of the engine's internal B2B or
  spin scoring is used.
* ``srs_plus`` and ``rot180`` are requested and the engine advertises them.
  The script counts the orientations of accepted suggestions as weak behavioural
  evidence that rotated states are used.  This is **not** proof that a concrete
  placement required an SRS+-only kick or a 180-only kick; see
  ``docs/integration_frostetra.md``.
* Pending garbage is sent as SBP ``incoming_garbage`` but the pinned engine
  discards it (verified separately with a seeded per-suggestion probe), so no
  garbage-aware play should be inferred from these matches.
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
from tetrisrl.agents.opponents.frostetra import (  # noqa: E402
    FrostetraAgent,
    frostetra_available,
    frostetra_binary_path,
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
        "accepted": 0,
        "invalid_suggestions": 0,
        "fallbacks": 0,
        "timeouts": 0,
        "protocol_errors": 0,
        "suggestions": 0,
        "engine_restarts": 0,
        "nodes_total": 0,
        "garbage_queries": 0,
    }
    orientations: Dict[str, int] = {}
    spins: Dict[str, int] = {}
    errors: List[str] = []

    for game in range(args.games):
        seed = args.seed + game
        engine = FrostetraAgent(
            think_time=args.think_time,
            timeout=args.timeout,
            allow_in_tests=True,
            use_piece_stream=not args.no_piece_stream,
            randomizer=None if args.no_randomizer else "seven_bag",
            name="frostetra",
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
            match_id=f"frostetra-vs-{baseline_name}-{seed}",
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
        totals["accepted"] += stats.accepted
        totals["invalid_suggestions"] += stats.invalid_suggestions
        totals["fallbacks"] += stats.fallbacks
        totals["timeouts"] += stats.timeouts
        totals["protocol_errors"] += stats.protocol_errors
        totals["suggestions"] += stats.suggestions
        totals["engine_restarts"] += stats.engine_restarts
        totals["nodes_total"] += stats.nodes_total
        totals["garbage_queries"] += stats.garbage_queries
        for orientation, count in stats.orientation_counts.items():
            orientations[orientation] = orientations.get(orientation, 0) + count
        for spin, count in stats.spin_counts.items():
            spins[spin] = spins.get(spin, 0) + count

        record = {
            "game": game,
            "seed": seed,
            "outcome": outcome,
            "winner": result.winner,
            "reason": result.reason,
            "ticks": result.ticks,
            "elapsed_s": round(elapsed, 3),
            "engine_stats": stats.as_dict(),
            "engine_version": engine.engine_info.get("version"),
            "engine_capabilities": engine.engine_info.get("capabilities", {}),
            "engine_box": result.stats[0].to_dict(),
            "baseline_box": result.stats[1].to_dict(),
            "invalid_actions_at_versus_layer": list(match.invalid_actions),
        }
        records.append(record)
        print(
            f"  game {game + 1:2d} seed={seed:<5d} {outcome:<5s} reason={result.reason:<22s} "
            f"ticks={result.ticks:<4d} accepted={stats.accepted:<4d} "
            f"invalid={stats.invalid_suggestions:<3d} fallbacks={stats.fallbacks:<4d} "
            f"timeouts={stats.timeouts:<3d} nodes={stats.nodes_total:<9d} "
            f"{elapsed:6.2f}s",
            flush=True,
        )
        engine.terminate()
        baseline.terminate()

    decisions = totals["accepted"] + totals["fallbacks"]
    return {
        "baseline": baseline_name,
        "ruleset": args.ruleset,
        "games_requested": args.games,
        "games_completed": len(records),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "score": f"{wins}-{losses}-{draws}",
        "win_rate": (wins / len(records)) if records else None,
        "avg_ticks": (sum(r["ticks"] for r in records) / len(records)) if records else None,
        "elapsed_s": round(time.time() - started, 2),
        "engine_accepted": totals["accepted"],
        "engine_invalid_moves": totals["invalid_suggestions"],
        "engine_fallbacks": totals["fallbacks"],
        "fallback_rate": (totals["fallbacks"] / decisions) if decisions else None,
        "acceptance_rate": (totals["accepted"] / decisions) if decisions else None,
        "engine_timeouts": totals["timeouts"],
        "engine_protocol_errors": totals["protocol_errors"],
        "engine_suggestions": totals["suggestions"],
        "engine_restarts": totals["engine_restarts"],
        "engine_nodes_total": totals["nodes_total"],
        "engine_garbage_queries": totals["garbage_queries"],
        "accepted_orientation_counts": orientations,
        "accepted_spin_counts": spins,
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
    parser.add_argument("--max-pieces", type=int, default=300)
    parser.add_argument("--think-time", type=float, default=0.08)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--no-piece-stream",
        action="store_true",
        help="ablation: omit start.piece_stream (the engine then observes the duplicated current piece)",
    )
    parser.add_argument(
        "--no-randomizer",
        action="store_true",
        help="ablation: omit rules.randomizer so the engine does not infer a seven-bag",
    )
    parser.add_argument("--json", default=None, help="output JSON path (default results/frostetra_match_<ts>.json)")
    args = parser.parse_args(argv)
    opponents = args.opponent or ["heuristic", "random"]

    load_ruleset(args.ruleset)  # fail early on a bad ruleset name
    binary = frostetra_binary_path()
    if not frostetra_available(binary):
        print(
            f"ERROR: frostetra binary not found at {binary}\n"
            "Build it with:  (cd third_party/frostetra && cargo build --release)",
            file=sys.stderr,
        )
        return 2

    commit = git_commit(REPO_ROOT / "third_party" / "frostetra")
    binary_hash = sha256(binary)
    print("=" * 82)
    print("Engine:    Frostetra (SBP/1 JSON lines over stdio)")
    print(f"Binary:    {binary}")
    print(f"Commit:    {commit or 'unknown'}")
    print(f"SHA-256:   {binary_hash}")
    print(f"Ruleset:   {args.ruleset}   max_pieces={args.max_pieces}   "
          f"think_time={args.think_time}s   timeout={args.timeout}s")
    print("Scope:     frostetra only suggests placements. tetrisrl owns attack, garbage,")
    print("           cancellation, B2B charging and Surge. Pending garbage is sent as")
    print("           SBP incoming_garbage but the pinned engine discards it.")
    print("=" * 82)

    payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "frostetra",
        "engine_commit": commit,
        "engine_binary": str(binary),
        "engine_binary_sha256": binary_hash,
        "args": vars(args),
        "series": [],
    }
    exit_code = 0
    for baseline_name in opponents:
        print(f"\n--- Frostetra vs {baseline_name} ---", flush=True)
        summary = run_series(args, baseline_name)
        payload["series"].append(summary)
        rate = summary["fallback_rate"]
        print(
            f"  SUMMARY vs {baseline_name}: {summary['score']} "
            f"({(summary['win_rate'] or 0) * 100:.1f}% wins) over {summary['games_completed']} games; "
            f"engine fallbacks {summary['engine_fallbacks']} "
            f"(rate {(rate or 0) * 100:.2f}%); "
            f"orientations {summary['accepted_orientation_counts']}"
        )
        if summary["errors"]:
            exit_code = 1
            for error in summary["errors"]:
                print(f"  ERROR: {error}")

    output = (
        Path(args.json)
        if args.json
        else REPO_ROOT / "results" / f"frostetra_match_{int(time.time())}.json"
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
