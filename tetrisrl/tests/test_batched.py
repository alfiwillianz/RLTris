"""Differential parity tests: batched NumPy core vs the reference engine."""

from __future__ import annotations

import numpy as np
import pytest

from tetrisrl.environment import placement as placement_mod
from tetrisrl.environment.batched import CELLS_PAD, LEFT_OFFSET_NP, BatchedBoard, HEIGHT, N_ACTIONS, PIECE_INDEX
from tetrisrl.environment.board import Board
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.pieces import CELLS, PIECE_NAMES, ActivePiece
from tetrisrl.environment.randomizer import FixedSequence


@pytest.fixture(autouse=True)
def _disable_spin_in(monkeypatch):
    monkeypatch.setattr(placement_mod, "SPIN_IN_PIECES", ())
    yield


def _random_state(rng: np.random.Generator, piece: str) -> GameState:
    """A state with a random low stack (spawn area clear) and a known piece."""
    state = GameState(seed=int(rng.integers(1 << 30)), piece_source=FixedSequence([piece] * 20))
    rows = np.zeros((HEIGHT, 10), dtype=bool)
    for _ in range(int(rng.integers(0, 10))):
        x = int(rng.integers(0, 10))
        h = int(rng.integers(1, 8))
        rows[HEIGHT - h :, x] = True
    for y in range(HEIGHT):
        mask = 0
        for x in range(10):
            if rows[y, x]:
                mask |= 1 << x
        state.board.rows[y] = mask
    state.current = ActivePiece(piece, 0, state._spawn_x(piece), state.ruleset.board.spawn_y)
    state.invalidate()
    return state


def test_placement_mask_and_cells_match_reference():
    rng = np.random.default_rng(7)
    n = 8
    pieces = [PIECE_NAMES[int(rng.integers(0, 7))] for _ in range(n)]
    states = [_random_state(rng, p) for p in pieces]
    batched = BatchedBoard(n)
    batched.rows = np.array([s.board.rows for s in states], dtype=np.uint16)
    batched.pieces = np.array([PIECE_INDEX[p] for p in pieces], dtype=np.int16)

    valid, ys, cells = batched.resolve_actions()
    for i, state in enumerate(states):
        ref_mask = np.array(state.action_mask())
        np.testing.assert_array_equal(valid[i], ref_mask, err_msg=f"mask mismatch board {i}")
        for action in range(N_ACTIONS):
            if not ref_mask[action]:
                continue
            placement = state.resolve(action)
            assert placement is not None
            assert int(ys[i, action]) == placement.y, (i, action, ys[i, action], placement.y)
            got = {(int(x), int(y)) for x, y in cells[i, action] if x >= 0}
            assert got == set(placement.cells), (i, action, got, placement.cells)


def test_lock_clear_and_hash_parity():
    rng = np.random.default_rng(11)
    n = 4
    states = []
    for _ in range(n):
        state = GameState(seed=int(rng.integers(1 << 30)), piece_source=FixedSequence(["O"] * 25))
        # nearly full bottom rows to exercise clearing
        for y in range(36, 40):
            state.board.rows[y] = state.board.full_row_mask & ~(1 << int(rng.integers(0, 10)))
        states.append(state)
    batched = BatchedBoard(n)
    batched.rows = np.array([s.board.rows for s in states], dtype=np.uint16)
    batched.pieces = np.array([PIECE_INDEX["O"]] * n, dtype=np.int16)

    valid, ys, cells = batched.resolve_actions()
    for i, state in enumerate(states):
        action = int(np.flatnonzero(valid[i])[0])
        ref = state.apply_action(action)
        chosen = cells[i, action]
        batched.lock(chosen[None, :, :], np.array([i]))
        cleared = batched.clear_lines()
        assert int(cleared[i]) == ref.lines, (cleared[i], ref.lines)
        assert int(batched.state_hash()[i]) == int(state.board.state_hash())


def test_garbage_insertion_parity():
    rng = np.random.default_rng(3)
    n = 3
    batched = BatchedBoard(n)
    batched.rows = np.array([np.zeros(HEIGHT, dtype=np.uint16) for _ in range(n)])
    holes = np.array([0, 4, 9], dtype=np.int16)
    amounts = np.array([2, 3, 1], dtype=np.int16)
    batched.insert_garbage(amounts, holes)
    for i in range(n):
        board = Board()
        board.insert_garbage(int(amounts[i]), int(holes[i]))
        assert list(batched.rows[i]) == board.rows


def test_batched_resolution_throughput():
    import time

    n = 256
    batched = BatchedBoard(n)
    batched.pieces = np.arange(n, dtype=np.int16) % 7
    t0 = time.time()
    steps = 25
    for _ in range(steps):
        valid, ys, cells = batched.resolve_actions()
        actions = np.argmax(valid, axis=1)
        chosen = cells[np.arange(n), actions]
        batched.lock(chosen)
        batched.clear_lines()
    dt = time.time() - t0
    rate = steps * n / dt
    assert rate > 2000, f"batched core too slow: {rate:.0f} boards/s"
    print(f"batched core: {rate:,.0f} board-steps/s")
