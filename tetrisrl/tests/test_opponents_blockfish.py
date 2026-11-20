"""Tests for the blockfish cheese/downstack adapter.

The live-engine tests are skipped when the pinned blockfish service binary has
not been built.  Build it with::

    (cd third_party/blockfish && cargo build --release -p blockfish --features service)

Blockfish is a cheese-race specialist, not a versus benchmark; these tests only
check protocol plumbing, board mapping, action legality and lifecycle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tetrisrl.agents.heuristic_agent import HeuristicAgent
from tetrisrl.agents.opponents.blockfish import (
    BLOCKFISH_ROWS,
    BLOCKFISH_WIDTH,
    BlockfishAgent,
    action_for_simulated_placement,
    blockfish_available,
    blockfish_binary_path,
    board_to_blockfish_rows,
    build_snapshot,
    simulate_inputs,
)
from tetrisrl.environment.engine import GameState

requires_blockfish = pytest.mark.skipif(
    not blockfish_available(),
    reason="blockfish service binary not built (third_party/blockfish)",
)


def _garbage_state(seed: int = 0) -> GameState:
    """A deterministic board with two cheese-like bottom rows."""
    state = GameState(seed=seed, max_pieces=200)
    mask = state.board.full_row_mask
    state.board.rows[state.board.height - 1] = mask & ~(1 << 4)
    state.board.rows[state.board.height - 2] = mask & ~(1 << 7)
    state.invalidate()
    return state


# ---------------------------------------------------------------------------
# Availability / path resolution
# ---------------------------------------------------------------------------
def test_availability_reports_binary_state():
    assert isinstance(blockfish_available(), bool)
    assert blockfish_binary_path().name == "blockfish"


def test_binary_path_env_override(monkeypatch, tmp_path):
    missing = tmp_path / "not-blockfish"
    monkeypatch.setenv("TETRISRL_BLOCKFISH_BIN", str(missing))
    assert blockfish_binary_path() == missing
    assert not blockfish_available()
    assert not blockfish_available(missing)


# ---------------------------------------------------------------------------
# Board / snapshot mapping
# ---------------------------------------------------------------------------
def test_board_rows_are_bottom_first_10x25():
    state = GameState(seed=0)
    board = state.board
    mask = board.full_row_mask
    board.rows[board.height - 1] = mask  # bottom row full
    board.rows[0] = mask  # above blockfish's 25-row window
    rows, unrepresentable = board_to_blockfish_rows(board)

    assert len(rows) == BLOCKFISH_ROWS
    assert all(len(row) == BLOCKFISH_WIDTH for row in rows)
    assert rows[0] == "X" * BLOCKFISH_WIDTH  # our bottom row is sent first
    assert unrepresentable == 1


def test_snapshot_queue_starts_with_current_piece():
    state = GameState(seed=0)
    snapshot = build_snapshot(state)
    assert snapshot.queue[0] == state.current.name
    assert snapshot.queue[1:] == state.preview(state.ruleset.board.preview)
    assert snapshot.hold == (state.hold or "")


# ---------------------------------------------------------------------------
# Input replay -> placement action (no engine needed)
# ---------------------------------------------------------------------------
def test_simulated_hard_drop_maps_to_legal_action():
    state = GameState(seed=0)
    simulated = simulate_inputs(state, ["hd"])
    assert simulated is not None
    assert simulated.piece == state.current.name
    action, exact = action_for_simulated_placement(state, simulated)
    assert exact is True
    assert action in state.legal_actions()
    resolved = state.resolve(action)
    assert set(resolved.cells) == set(simulated.cells)


def test_simulated_hold_uses_hold_piece():
    state = GameState(seed=0)
    state.hold = "T"
    state.can_hold = True
    state.invalidate()
    simulated = simulate_inputs(state, ["hold", "hd"])
    assert simulated is not None
    assert simulated.piece == "T"
    assert simulated.hold_used is True
    action, _exact = action_for_simulated_placement(state, simulated)
    assert action is not None
    assert state.resolve(action).hold is True


# ---------------------------------------------------------------------------
# Live engine: one real suggestion mapped to a legal action
# ---------------------------------------------------------------------------
@requires_blockfish
def test_live_suggestion_maps_to_legal_action():
    state = _garbage_state(seed=0)
    agent = BlockfishAgent(node_limit=20_000, allow_in_tests=True)
    try:
        action = agent.choose_action(state)
        assert action in state.legal_actions()
        assert agent.stats.suggestions == 1
        assert agent.stats.last_inputs
        assert agent.stats.fallbacks == 0
        assert agent.stats.accepted + agent.stats.rejected == 1
        assert agent.stats.accepted == 1
        assert agent.engine_info.get("version")
    finally:
        agent.terminate()


# ---------------------------------------------------------------------------
# Fallback when the engine is unavailable
# ---------------------------------------------------------------------------
def test_fallback_on_unavailable_engine(tmp_path):
    state = GameState(seed=0)
    fallback = HeuristicAgent(seed=1)
    agent = BlockfishAgent(
        binary=tmp_path / "missing-blockfish",
        fallback=fallback,
        allow_in_tests=True,
    )
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.fallbacks == 1
    assert agent.stats.protocol_errors == 1
    assert agent.stats.accepted == 0
    assert agent.stats.engine_starts == 0


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
@requires_blockfish
def test_lifecycle_launch_and_terminate():
    state = _garbage_state(seed=1)
    agent = BlockfishAgent(node_limit=5_000, allow_in_tests=True)
    try:
        assert agent.choose_action(state) in state.legal_actions()
        assert agent.stats.engine_starts == 1
        session = agent._session
        assert session is not None and session.alive()
        agent.terminate()
        assert agent._session is None
        assert not session.alive()

        # A terminated agent restarts cleanly on the next request.
        assert agent.choose_action(state) in state.legal_actions()
        assert agent.stats.engine_starts == 2
    finally:
        agent.terminate()
