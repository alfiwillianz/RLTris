"""Benchmark simulation and update throughput.

Usage: .venv/bin/python scripts/benchmark_throughput.py [--steps 20000]
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import argparse
import json
import time

from tetrisrl.agents import HeuristicAgent, RandomAgent
from tetrisrl.environment.engine import GameState


def bench_engine(steps: int) -> dict:
    state = GameState(seed=1)
    rng = RandomAgent(seed=2)
    t0 = time.time()
    n = 0
    while n < steps:
        actions = state.legal_actions()
        if not actions or state.finished:
            state = GameState(seed=state.seed + 1)
            continue
        state.apply_action(actions[rng.rng.randrange(len(actions))])
        n += 1
    dt = time.time() - t0
    return {"placements": n, "seconds": dt, "placements_per_second": n / dt}


def bench_versus(steps: int) -> dict:
    from tetrisrl.environment.versus import VersusMatch

    t0 = time.time()
    match = VersusMatch(HeuristicAgent(seed=1), HeuristicAgent(seed=2), seed=3, max_pieces=steps, record_frames=False)
    result = match.run()
    dt = time.time() - t0
    return {"ticks": result.ticks, "seconds": dt, "ticks_per_second": result.ticks / dt}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=5000)
    args = parser.parse_args()
    report = {
        "engine": bench_engine(args.steps),
        "versus_heuristic_vs_heuristic": bench_versus(max(50, args.steps // 10)),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
