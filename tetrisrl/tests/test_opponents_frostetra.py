"""Tests for the frostetra SBP/1 opponent adapter.

Unit and guard tests run without the external binary.  Tests that launch the
engine are skipped unless ``third_party/frostetra/target/release/frostetra``
exists (``cargo build --release`` in that directory).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tetrisrl.agents.opponents.frostetra import (
    DEFAULT_BINARY,
    FrostetraAgent,
    SBPSession,
    SBP_HEIGHT,
    action_for_sbp_move,
    board_to_sbp_rows,
    build_rules_message,
    build_start_message,
    frostetra_available,
    frostetra_binary_path,
    parse_suggestion,
    sbp_move_cells,
)
from tetrisrl.environment.actions import encode_action
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.randomizer import FixedSequence

real_engine = pytest.mark.skipif(
    not frostetra_available(),
    reason="frostetra binary not built (cargo build --release in third_party/frostetra)",
)


def state_with_pieces(*pieces: str) -> GameState:
    return GameState(seed=0, piece_source=FixedSequence(list(pieces)))


def seeded_config(tmp_path: Path, *, iterations: int = 2000, seed: int = 5) -> Path:
    """A deterministic per-suggestion engine config (no background workers)."""
    path = tmp_path / "frostetra_probe.json"
    path.write_text(
        json.dumps(
            {
                "search": {
                    "rng": {"mode": "seeded", "seed": seed},
                    "budget": {"mode": "iterations_per_suggest", "iterations": iterations},
                    "threads": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Availability / wire encoding (no engine)
# ---------------------------------------------------------------------------
def test_availability_and_path_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv("TETRISRL_FROSTETRA_BIN", raising=False)
    assert frostetra_binary_path() == DEFAULT_BINARY
    assert frostetra_binary_path().is_absolute()
    assert frostetra_binary_path().name == "frostetra"

    explicit = tmp_path / "frostetra"
    assert frostetra_binary_path(explicit) == explicit
    monkeypatch.setenv("TETRISRL_FROSTETRA_BIN", str(explicit))
    assert frostetra_binary_path() == explicit
    assert frostetra_available() is False
    explicit.write_bytes(b"#!/bin/sh\nexit 0\n")
    explicit.chmod(0o755)
    assert frostetra_available() is True


def test_board_rows_are_bottom_to_top():
    state = GameState(seed=0)
    state.board.rows[39] = (1 << 0) | (1 << 9)
    state.board.rows[0] = 1 << 0
    rows = board_to_sbp_rows(state.board)
    assert len(rows) == SBP_HEIGHT
    assert rows[0][0] == "X" and rows[0][9] == "X"
    assert rows[0][1] is None
    assert rows[SBP_HEIGHT - 1][0] == "X"
    assert sum(cell is not None for row in rows for cell in row) == 3


def test_rules_and_start_encoding():
    state = state_with_pieces("T", "I", "O", "L", "J", "S", "Z")
    state.board.rows[39] = 1 << 4
    state.clear_state.combo = 3
    state.clear_state.b2b = 2
    assert state.receive_attack(5) == 5

    rules = build_rules_message(state)
    assert rules["type"] == "rules"
    assert rules["kickset"] == "srs_plus"
    assert rules["rot180"] is True
    assert rules["sonic_drop"] == "only"
    assert rules["spin_detection"] == "t-spins"
    assert rules["board_size"] == {"width": 10, "height": 40}
    assert rules["spawn_position"] == {"x": 4, "y": 20}
    assert rules["randomizer"] == "seven_bag"

    start = build_start_message(state)
    assert start["type"] == "start"
    assert start["active"] == "T"
    # Dialect: frostetra places queue[0], so the current piece leads the queue.
    assert start["queue"][0] == "T"
    assert start["queue"][1:] == state.preview(5)
    assert start["hold"] is None
    # Our combo is -1/0/1 (none/first/second); the engine counts clears.
    assert start["combo"] == 4
    assert start["back_to_back"] == 2
    assert start["incoming_garbage"] == [5]
    assert len(start["board"]) == 40
    assert start["board"][0][4] == "X"  # our bottom row


def test_queue_discipline_depends_on_hold():
    state = GameState(seed=0, piece_source=FixedSequence(["T"], repeat=True))
    # Empty hold: the engine searches queue[0], so the current piece leads it.
    start = build_start_message(state, preview_count=0)
    assert start["queue"] == ["T"]
    assert start["hold"] is None
    # Hold set: the engine searches active first and prepends it to queue, so
    # repeating the current piece would make it search that piece twice.
    state.hold = "I"
    state.can_hold = True
    state.invalidate()
    start = build_start_message(state, preview_count=0)
    assert start["queue"] == []
    assert start["active"] == "T"
    assert start["hold"] == "I"


def test_sbp_move_cells_use_our_top_down_coordinates():
    piece, cells = sbp_move_cells(
        {"location": {"piece": "O", "orientation": "north", "x": 4, "y": 0}}
    )
    assert piece == "O"
    assert cells == {(4, 39), (5, 39), (4, 38), (5, 38)}

    # A south-facing T anchored at y=2 (bottom-up) mirrors to row 37.
    piece, cells = sbp_move_cells(
        {"location": {"piece": "T", "orientation": "south", "x": 5, "y": 2}}
    )
    assert piece == "T"
    assert cells == {(6, 37), (5, 37), (4, 37), (5, 38)}

    with pytest.raises(Exception):
        sbp_move_cells({"location": {"piece": "T", "orientation": "north", "x": 0, "y": 0}})


def test_action_mapping_matches_cells_and_hold_flag():
    state = state_with_pieces("O", "I", "L")
    action = encode_action(0, 4)
    assert action in state.legal_actions()
    move = {"location": {"piece": "O", "orientation": "north", "x": 4, "y": 0}, "spin": "none"}
    assert action_for_sbp_move(move, state) == action

    # A placement of the held piece must select a hold action.
    held = state_with_pieces("T", "O", "I", "L")
    held.hold = "O"
    held.can_hold = True
    held.invalidate()
    held_action = action_for_sbp_move(move, held)
    assert held_action is not None
    placement = held.resolve(held_action)
    assert placement is not None and placement.piece == "O" and placement.hold is True


def test_invalid_or_floating_move_returns_none():
    state = state_with_pieces("O", "I")
    floating = {"location": {"piece": "O", "orientation": "north", "x": 4, "y": 10}}
    assert action_for_sbp_move(floating, state) is None
    assert action_for_sbp_move({"location": {"piece": "X", "x": 0, "y": 0}}, state) is None


def test_parse_suggestion_validates_shape():
    assert parse_suggestion({"type": "suggestion", "moves": []}) == []
    with pytest.raises(Exception):
        parse_suggestion({"type": "info"})
    with pytest.raises(Exception):
        parse_suggestion({"type": "suggestion"})


# ---------------------------------------------------------------------------
# Guards (never launch the engine)
# ---------------------------------------------------------------------------
def test_refuses_to_launch_under_pytest_without_optin():
    agent = FrostetraAgent(allow_in_tests=False, timeout=1.0)
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.protocol_errors == 1
    assert agent.stats.fallbacks == 1
    assert "refuses to launch" in agent.stats.last_error
    assert agent._session is None


def test_disable_environment_variable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TETRISRL_FROSTETRA_DISABLE", "1")
    agent = FrostetraAgent(allow_in_tests=True, timeout=0.5)
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.protocol_errors == 1
    assert agent.stats.fallbacks == 1
    assert "disabled" in agent.stats.last_error


# ---------------------------------------------------------------------------
# Real engine (skipped unless built)
# ---------------------------------------------------------------------------
@real_engine
def test_real_suggestion_maps_to_a_legal_action():
    agent = FrostetraAgent(allow_in_tests=True, think_time=0.15, timeout=5.0)
    state = GameState(seed=0)
    try:
        action = agent.choose_action(state)
    finally:
        agent.terminate()
    assert action in state.legal_actions()
    placement = state.resolve(action)
    assert placement is not None
    assert agent.stats.engine_starts == 1
    assert agent.stats.suggestions == 1
    assert agent.stats.accepted == 1
    assert agent.stats.fallbacks == 0
    assert agent.stats.protocol_errors == 0
    assert agent.engine_info.get("name") == "Frostetra"
    assert "srs_plus" in agent.engine_info["capabilities"]["kicksets"]
    assert agent.engine_info["capabilities"]["rot180"] is True
    assert agent.stats.nodes_total > 0
    assert agent.last_suggestion is not None


@real_engine
def test_real_lifecycle_restart_and_clean_shutdown():
    agent = FrostetraAgent(allow_in_tests=True, think_time=0.05, timeout=5.0)
    first = GameState(seed=1)
    try:
        assert agent.choose_action(first) in first.legal_actions()
        proc = agent._session.proc if agent._session is not None else None
        assert proc is not None and proc.poll() is None
        agent.terminate()
        assert proc.poll() is not None  # no orphan process
        assert agent.stats.engine_starts == 1

        second = GameState(seed=2)
        assert agent.choose_action(second) in second.legal_actions()
        assert agent.stats.engine_starts == 2
    finally:
        agent.terminate()
    assert agent._session is None


def test_broken_engine_command_falls_back():
    agent = FrostetraAgent(
        command=[sys.executable, "-c", "import sys; sys.exit(1)"],
        allow_in_tests=True,
        handshake_timeout=2.0,
        timeout=1.0,
    )
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.protocol_errors == 1
    assert agent.stats.fallbacks == 1
    assert agent.stats.engine_starts == 0
    assert agent.stats.last_error


@real_engine
def test_incoming_garbage_does_not_change_the_suggestion(tmp_path: Path):
    """Empirical check of the documented 'parsed but unused' behaviour.

    The pinned build deserialises ``incoming_garbage`` and then discards it.
    Two fresh processes with an identical seeded per-suggestion budget must
    therefore return the same move whether the pending queue is empty or 8.
    """
    config = seeded_config(tmp_path)
    state = state_with_pieces("T", "I", "O", "L", "J", "S", "Z")
    rules = build_rules_message(state)

    def suggestion_for(incoming):
        session = SBPSession(
            [str(frostetra_binary_path()), "--config", str(config)], handshake_timeout=5.0
        )
        try:
            session.handshake(rules)
            session.send(build_start_message(state, incoming_garbage=incoming))
            session.send({"type": "suggest", "incoming_garbage": incoming})
            while True:
                message = session.read_message(5.0)
                if message.get("type") == "suggestion":
                    return message["moves"]
                assert message.get("type") == "info", message
        finally:
            session.close()

    without = suggestion_for([])
    with_garbage = suggestion_for([8])
    assert without == with_garbage
    assert without  # the probe is only meaningful if the engine returned a move


@real_engine
def test_real_versus_match_smoke():
    from tetrisrl.agents.heuristic_agent import HeuristicAgent
    from tetrisrl.environment.versus import VersusMatch

    engine = FrostetraAgent(allow_in_tests=True, think_time=0.05, timeout=5.0)
    baseline = HeuristicAgent(seed=42)
    try:
        match = VersusMatch(
            engine,
            baseline,
            seed=0,
            max_pieces=40,
            record_frames=False,
            record_events=False,
        )
        result = match.run()
    finally:
        engine.terminate()
    assert result.ticks > 0
    assert result.reason
    assert engine.stats.suggestions >= 30
    assert engine.stats.accepted > 0
    assert engine.stats.timeouts == 0
    assert engine.stats.protocol_errors == 0
    assert match.invalid_actions[0] == 0
