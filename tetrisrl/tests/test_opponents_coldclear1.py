"""Tests for the Cold Clear (original) C-ABI opponent adapter.

Unit/guard tests run without the external library.  Every test that actually
loads ``libcold_clear.so`` is skipped when the library has not been built under
``third_party/cold-clear`` (``cargo build --release -p c-api``).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tetrisrl.agents.heuristic_agent import HeuristicAgent
from tetrisrl.agents.opponents.coldclear1 import (
    CC_HEIGHT,
    CC_WIDTH,
    ColdClear1Agent,
    ColdClear1Move,
    action_for_move,
    board_to_field,
    coldclear1_available,
    coldclear1_binary_path,
)
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.versus import VersusMatch

real_engine = pytest.mark.skipif(
    not coldclear1_available(),
    reason="Cold Clear C library not built (cargo build --release -p c-api in third_party/cold-clear)",
)


def state_with_piece(*pieces: str, seed: int = 0) -> GameState:
    from tetrisrl.environment.randomizer import FixedSequence

    return GameState(seed=seed, piece_source=FixedSequence(list(pieces)))


# ---------------------------------------------------------------------------
# Availability / encoding (no engine load)
# ---------------------------------------------------------------------------
def test_availability_and_path_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("TETRISRL_COLDCLEAR1_LIB", raising=False)
    assert coldclear1_binary_path().name == "libcold_clear.so"
    assert coldclear1_binary_path().is_absolute()
    # An explicit path wins over everything.
    explicit = tmp_path / "custom.so"
    assert coldclear1_binary_path(explicit) == explicit
    # Environment override is honoured for both helpers.
    monkeypatch.setenv("TETRISRL_COLDCLEAR1_LIB", str(explicit))
    assert coldclear1_binary_path() == explicit
    assert coldclear1_available() is False  # file does not exist
    explicit.write_bytes(b"not a library")
    assert coldclear1_available() is True


def test_board_field_is_bottom_left_row_major():
    state = GameState(seed=0)
    # Bottom row: columns 0 and 9.  Top row: column 0.
    state.board.rows[39] = (1 << 0) | (1 << 9)
    state.board.rows[0] = 1 << 0
    field = board_to_field(state.board)
    assert len(field) == CC_WIDTH * CC_HEIGHT
    # Bottom-up index 0..9 is our row 39.
    assert field[0] is True and field[9] is True
    assert field[1] is False
    # Bottom-up index 39*10 is our top row.
    assert field[39 * CC_WIDTH] is True
    assert field[39 * CC_WIDTH + 1] is False
    assert sum(field) == 3


def test_move_cells_use_our_top_down_coordinates():
    move = ColdClear1Move(hold=False, cells=((4, 39), (5, 39), (4, 38), (5, 38)))
    state = state_with_piece("O", "I", "T", "S", "Z")
    action = action_for_move(move, state)
    assert action is not None
    placement = state.resolve(action)
    assert placement is not None and placement.piece == "O"
    assert set(placement.cells) == set(move.cells)
    assert placement.hold is False

    # A held-piece suggestion must select a hold action when it matches.
    held_state = state_with_piece("O", "I", "S", "Z", "J")
    held_state.hold = "T"
    held_state.can_hold = True
    t_move = ColdClear1Move(hold=True, cells=((3, 39), (4, 39), (5, 39), (4, 38)))
    held_action = action_for_move(t_move, held_state)
    assert held_action is not None
    held_placement = held_state.resolve(held_action)
    assert held_placement is not None and held_placement.piece == "T" and held_placement.hold


def test_invalid_move_returns_none():
    state = GameState(seed=0)
    assert action_for_move(ColdClear1Move(hold=False, cells=((0, 0), (1, 0), (2, 0), (3, 0))), state) is None


# ---------------------------------------------------------------------------
# Guards (never load the engine)
# ---------------------------------------------------------------------------
def test_refuses_to_load_under_pytest_without_optin():
    agent = ColdClear1Agent(allow_in_tests=False, timeout=1.0)
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.errors == 1
    assert agent.stats.fallbacks == 1
    assert "refuses to load" in agent.stats.last_error
    assert agent.library_loaded is False


def test_disable_environment_variable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TETRISRL_COLDCLEAR1_DISABLE", "1")
    agent = ColdClear1Agent(allow_in_tests=True, timeout=0.5)
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.errors == 1
    assert "disabled" in agent.stats.last_error
    assert agent.library_loaded is False


# ---------------------------------------------------------------------------
# Real engine (skipped unless built)
# ---------------------------------------------------------------------------
@real_engine
def test_real_search_returns_legal_action():
    agent = ColdClear1Agent(think_nodes=10_000, timeout=5.0, allow_in_tests=True)
    state = GameState(seed=0)
    try:
        for _ in range(5):
            action = agent.choose_action(state)
            assert action in state.legal_actions()
            assert state.resolve(action) is not None
            state.apply_action(action)
    finally:
        agent.terminate()
    assert agent.stats.searches >= 5
    assert agent.stats.accepted >= 5
    assert agent.stats.invalid_moves == 0
    assert agent.stats.timeouts == 0
    assert agent.stats.errors == 0
    assert agent.stats.last_move["cells"]
    assert agent.stats.nodes_total > 0


@real_engine
def test_real_search_accepts_incoming_garbage_count():
    agent = ColdClear1Agent(think_nodes=10_000, timeout=5.0, allow_in_tests=True)
    state = GameState(seed=0)
    state.garbage.add(10)
    assert state.pending_garbage == 10
    try:
        action = agent.choose_action(state)
    finally:
        agent.terminate()
    assert action in state.legal_actions()
    assert agent.stats.last_incoming == 10
    assert agent.stats.accepted == 1
    assert agent.stats.errors == 0


@real_engine
def test_timeout_falls_back_and_recovers():
    agent = ColdClear1Agent(think_nodes=50_000_000, timeout=0.01, allow_in_tests=True)
    state = GameState(seed=0)
    started = time.monotonic()
    action = agent.choose_action(state)
    elapsed = time.monotonic() - started
    assert action in state.legal_actions()
    assert agent.stats.timeouts == 1
    assert agent.stats.fallbacks == 1
    assert elapsed < 2.0
    agent.terminate()

    # A timed-out bot must be destroyed cleanly; a new agent still works.
    recovered = ColdClear1Agent(think_nodes=10_000, timeout=5.0, allow_in_tests=True)
    state = GameState(seed=1)
    try:
        action = recovered.choose_action(state)
        assert action in state.legal_actions()
        assert recovered.stats.accepted == 1
    finally:
        recovered.terminate()


@real_engine
def test_lifecycle_and_terminate_semantics():
    agent = ColdClear1Agent(think_nodes=10_000, timeout=5.0, allow_in_tests=True)
    agent.reset(7)
    assert agent.seed == 7
    state = GameState(seed=7)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.library_loaded is True

    agent.terminate()
    assert agent._closed is True
    # After terminate the agent refuses to launch but still plays legally.
    fallback_action = agent.choose_action(state)
    assert fallback_action in state.legal_actions()
    assert agent.stats.errors >= 1
    agent.terminate()  # idempotent

    # reset() re-enables the engine and clears the counters.
    agent.reset(8)
    assert agent.stats.searches == 0
    reopened = agent.choose_action(GameState(seed=8))
    assert reopened >= 0
    assert agent.stats.accepted >= 1
    agent.terminate()


@real_engine
def test_real_versus_match_smoke():
    engine = ColdClear1Agent(think_nodes=10_000, timeout=5.0, allow_in_tests=True)
    heuristic = HeuristicAgent(seed=11)
    try:
        match = VersusMatch(
            engine,
            heuristic,
            ruleset="tetrio_s2",
            seed=0,
            max_pieces=40,
            record_frames=False,
            record_events=False,
        )
        result = match.run()
    finally:
        engine.terminate()
        heuristic.terminate()
    assert result.ticks > 0
    assert engine.stats.searches > 0
    assert engine.stats.accepted > 0
    assert engine.stats.errors == 0
    assert engine.stats.timeouts == 0
    assert list(match.invalid_actions) == [0, 0]
