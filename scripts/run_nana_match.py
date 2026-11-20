#!/usr/bin/env python
"""Run real nightcrab/nana matches against the in-repo baselines.

nana is driven as a subprocess over TBP2 (JSON lines on stdin/stdout); this
script starts one engine process per game, plays ``--games`` paired-seed games
against each requested baseline under the project's TETR.IO Season 2 ruleset,
and reports nana's accepted/fallback/timeout counters alongside the arena
statistics.

Examples
--------
The two commands used in ``docs/integration_nana.md``::

    .venv/bin/python scripts/run_nana_match.py --games 10 --opponent heuristic
    .venv/bin/python scripts/run_nana_match.py --games 10 --opponent random

A quick plumbing check (3 games, 120-piece cap, both baselines)::

    .venv/bin/python scripts/run_nana_match.py --games 3 --max-pieces 120 \\
        --opponent heuristic random

The script is honest by construction: it exits with an error when the nana
binary is missing, never substitutes another agent for the engine, and reports
every heuristic fallback (placements our hard-drop action space cannot
express).  nana v0.1 does not emit search telemetry (no ``move_info``), so the
report records latency but no node counts.
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
from tetrisrl.agents.opponents.nana import (  # noqa: E402
    DEFAULT_NANA_THREADS,
    NANA_COMMIT,
    NanaAgent,
    ensure_nana_config,
    nana_available,
    nana_binary_path,
    nana_config_path,
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
    engine_timeouts = 0
    engine_protocol_errors = 0
    total_ticks = 0
    total_nodes = 0
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
        engine_agent = NanaAgent(
            binary=args.binary,
            config_path=args.config,
            think_time=args.think_ms / 1000.0,
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
            match_id=f"nana-vs-{baseline_name}-{seed}",
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
        engine_timeouts += stats.timeouts
        engine_protocol_errors += stats.protocol_errors
        total_ticks += result.ticks
        total_nodes += stats.nodes_total
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
            f"timeouts={stats.timeouts:<2d} topout={result.stats[1].top_out_reason or '-':<16s} "
            f"{elapsed:6.2f}s",
            flush=True,
        )
        engine_agent.terminate()
        baseline.terminate()

    games_played = len(records)
    pieces = [v / games_played for v in totals["pieces"]] if games_played else [0.0, 0.0]
    summary = {
        "opponent": "nana",
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
        "engine_timeouts": engine_timeouts,
        "engine_protocol_errors": engine_protocol_errors,
        "fallback_rate": (engine_fallbacks / max(1, engine_accepted + engine_fallbacks)),
        "mean_answer_latency_ms": (
            sum(r["engine_stats"]["answer_latency_ms"] for r in records) / engine_suggestions
            if engine_suggestions
            else None
        ),
        "engine_nodes_total": total_nodes,
        "nodes_exposed": total_nodes > 0,
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
        f"nana suggestions {engine_suggestions}, accepted {engine_accepted}, "
        f"fallbacks {engine_fallbacks} "
        f"(rate {100.0 * engine_fallbacks / max(1, engine_accepted + engine_fallbacks):.2f}%), "
        f"timeouts {engine_timeouts}, protocol errors {engine_protocol_errors}",
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
    parser.add_argument("--max-pieces", type=int, default=300)
    parser.add_argument("--think-ms", type=float, default=150.0, help="nana search budget per placement (ms)")
    parser.add_argument("--timeout", type=float, default=10.0, help="TBP2 suggestion timeout (seconds)")
    parser.add_argument("--binary", default=None, help="path to the nana_tbp executable")
    parser.add_argument("--config", default=None, help="path to nana.json (default: beside the binary)")
    parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_NANA_THREADS,
        help="threads written to nana.json when it is created (nana reads it beside the binary)",
    )
    parser.add_argument("--json", default=None, help="output JSON path (default results/nana_match_<ts>.json)")
    args = parser.parse_args(argv)

    binary = nana_binary_path(args.binary)
    if not nana_available(binary):
        raise SystemExit(
            f"nana_tbp binary not found/executable at {binary}\n"
            "Build it first:  cmake -S third_party/nana -B third_party/nana/build "
            "-DCMAKE_BUILD_TYPE=Release && cmake --build third_party/nana/build -j"
        )
    config = nana_config_path(binary, args.config)
    ensure_nana_config(config, threads=args.threads)
    args.binary = str(binary)
    args.config = str(config)

    clone = binary.parents[2] if len(binary.parents) > 2 else None
    clone_commit = git_commit(clone) if clone else None
    try:
        config_data = json.loads(Path(config).read_text())
    except (OSError, json.JSONDecodeError):
        config_data = None
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "nightcrab/nana",
        "adapter_commit": NANA_COMMIT,
        "clone_commit": clone_commit,
        "binary": str(binary),
        "binary_size": binary.stat().st_size,
        "config_path": str(config),
        "config": config_data,
        "think_ms": args.think_ms,
        "timeout_s": args.timeout,
        "max_pieces": args.max_pieces,
        "ruleset": args.ruleset,
        "series": [],
    }
    print(f"nana engine: {binary}")
    print(f"clone commit: {clone_commit} (adapter verified against {NANA_COMMIT})")
    print(f"config: {config} -> {config_data}")
    print(
        f"config: ruleset={args.ruleset} max_pieces={args.max_pieces} "
        f"think={args.think_ms:.0f}ms timeout={args.timeout:.1f}s"
    )

    for baseline in args.opponent:
        print(f"\n--- nana (TBP2 subprocess) vs {baseline} ---", flush=True)
        report["series"].append(run_series(args, baseline))

    if args.json:
        out = Path(args.json)
    else:
        stamp = int(time.time())
        out = REPO_ROOT / "results" / f"nana_match_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\nJSON report: {out}")

    any_error = any(series["errors"] for series in report["series"])
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
