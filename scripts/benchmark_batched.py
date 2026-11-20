"""Benchmark the batched NumPy core against the scalar reference engine.

Usage: .venv/bin/python scripts/benchmark_batched.py [--boards 256]
"""

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import argparse

import numpy as np

from tetrisrl.environment.batched import BatchedBoard, N_ACTIONS
from tetrisrl.environment.engine import GameState


def benchmark_reference(steps: int) -> float:
    state = GameState(seed=1)
    rng = np.random.default_rng(0)
    t0 = time.time()
    n = 0
    while n < steps:
        actions = state.legal_actions()
        if not actions or state.finished:
            state = GameState(seed=state.seed + 1)
            continue
        state.apply_action(int(rng.choice(actions)))
        n += 1
    return n / (time.time() - t0)


def benchmark_batched(n: int, steps: int) -> float:
    board = BatchedBoard(n)
    board.pieces = np.arange(n, dtype=np.int16) % 7
    valid = None
    t0 = time.time()
    for _ in range(steps):
        valid, ys, cells = board.resolve_actions()
        actions = np.argmax(valid, axis=1)
        board.lock(cells[np.arange(n), actions])
        board.clear_lines()
        board.pieces = (board.pieces + 1) % 7
    dt = time.time() - t0
    return steps * n / dt, dt * 1e6 / (steps * n)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boards", type=int, default=256)
    parser.add_argument("--steps", type=int, default=50)
    args = parser.parse_args()

    ref = benchmark_reference(1500)
    batched, us = benchmark_batched(args.boards, args.steps)
    print(f"reference scalar engine : {ref:>10,.0f} board-steps/s")
    print(f"batched NumPy ({args.boards:>4d} boards): {batched:>10,.0f} board-steps/s ({us:.1f} us/board-step)")
    print(f"speedup                 : {batched / ref:>10,.1f}x")
    print("note: batched core covers placement/mask/lock/clear only; spin-in, scoring,")
    print("      garbage exchange and observation assembly are not yet ported.")


if __name__ == "__main__":
    main()
