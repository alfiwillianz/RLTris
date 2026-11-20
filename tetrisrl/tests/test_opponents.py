"""Tests for external opponent adapters (Cold Clear 2 / TBP and the mock bot).

The mock-bot tests exercise the full subprocess plumbing deterministically and
never need the external engine.  The Cold Clear 2 tests are skipped unless the
release binary has been built under ``third_party/cold-clear-2``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from tetrisrl.agents.heuristic_agent import HeuristicAgent
from tetrisrl.agents.opponents import TBPAgent
from tetrisrl.agents.opponents.mock_bot import SBPMockBot
from tetrisrl.agents.opponents.tbp import (
    DEFAULT_BINARY,
    action_for_tbp_move,
    board_to_tbp_rows,
    board_to_text_rows,
    build_start_message,
    coldclear_available,
    parse_suggestion,
    tbp_move_cells,
    tbp_rows_to_board_rows,
)
from tetrisrl.environment.actions import decode_action
from tetrisrl.environment.board import Board
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.randomizer import FixedSequence
from tetrisrl.environment.versus import VersusMatch

MOCK_MODULE = "tetrisrl.agents.opponents.mock_bot"


def mock_command(*extra: str) -> list[str]:
    return [sys.executable, "-m", MOCK_MODULE, *extra]


def state_with_piece(*pieces: str, seed: int = 0) -> GameState:
    return GameState(seed=seed, piece_source=FixedSequence(list(pieces)))


# ---------------------------------------------------------------------------
# Wire encoding / decoding
# ---------------------------------------------------------------------------
def test_board_wire_roundtrip_and_garbage_marking():
    board = Board()
    board.rows[39] = 0b0000001111  # bottom row, columns 0-3
    board.rows[38] = 0b1000000001  # second-from-bottom, columns 0 and 9
    board.rows[0] = 0b0000000001  # top row, column 0

    wire = board_to_tbp_rows(board)
    assert len(wire) == 40
    assert all(len(row) == 10 for row in wire)
    # TBP rows are bottom-up.
    assert wire[0][:5] == ["#", "#", "#", "#", None]
    assert wire[1][0] == "#" and wire[1][9] == "#"
    assert wire[39][0] == "#" and wire[39][1] is None
    # Empty cells are JSON null, occupied cells are strings.
    assert wire[2] == [None] * 10

    roundtrip = tbp_rows_to_board_rows(wire)
    assert roundtrip == board.rows
    assert board_to_text_rows(board)[0] == "#........."

    garbage_wire = board_to_tbp_rows(board, garbage_rows={39})
    assert garbage_wire[0][0] == "G"
    # "G" is occupied for our purposes too.
    assert tbp_rows_to_board_rows(garbage_wire) == board.rows


def test_board_wire_rejects_wrong_height():
    board = Board(height=20, visible_height=20)
    with pytest.raises(Exception):
        board_to_tbp_rows(board)


def test_parse_suggestion_roundtrip():
    message = {
        "type": "suggestion",
        "moves": [
            {"location": {"type": "O", "orientation": "north", "x": 4, "y": 0}, "spin": "none"}
        ],
        "move_info": {"nodes": 33416, "nps": 664555.36, "extra": "probe"},
    }
    encoded = json.dumps(message)
    moves, info = parse_suggestion(json.loads(encoded))
    assert len(moves) == 1
    assert info["nodes"] == 33416

    with pytest.raises(Exception):
        parse_suggestion({"type": "ready"})
    with pytest.raises(Exception):
        parse_suggestion({"type": "suggestion"})


def test_tbp_move_geometry_mapping():
    # Real Cold Clear 2 suggestion captured from the built binary on an empty
    # board (orientation "north", centre x=4, y=0 bottom-up).
    move = {"location": {"type": "O", "orientation": "north", "x": 4, "y": 0}, "spin": "none"}
    piece, cells = tbp_move_cells(move)
    assert piece == "O"
    assert cells == {(4, 39), (5, 39), (4, 38), (5, 38)}

    state = state_with_piece("O", "I", "T", "S", "Z")
    action = action_for_tbp_move(move, state)
    assert action is not None
    placement = state.resolve(action)
    assert placement is not None and placement.piece == "O"
    assert set(placement.cells) == cells
    assert decode_action(action) == (0, 4, False)

    # T north: bar on the bottom row, nub above it -> our rotation 2.
    t_move = {"location": {"type": "T", "orientation": "north", "x": 4, "y": 0}, "spin": "none"}
    t_state = state_with_piece("T", "I", "O", "S", "Z")
    t_action = action_for_tbp_move(t_move, t_state)
    assert t_action is not None
    t_placement = t_state.resolve(t_action)
    assert t_placement is not None and t_placement.piece == "T"
    assert set(t_placement.cells) == {(3, 39), (4, 39), (5, 39), (4, 38)}

    # I east: vertical column -> our rotation 1/3, same occupied cells.
    i_move = {"location": {"type": "I", "orientation": "east", "x": 5, "y": 2}, "spin": "none"}
    i_state = state_with_piece("I", "T", "O", "S", "Z")
    i_action = action_for_tbp_move(i_move, i_state)
    assert i_action is not None
    i_placement = i_state.resolve(i_action)
    assert i_placement is not None and i_placement.piece == "I"
    assert set(i_placement.cells) == {(5, 39), (5, 38), (5, 37), (5, 36)}


def test_action_mapping_prefers_hold_when_engine_places_other_piece():
    move = {"location": {"type": "T", "orientation": "north", "x": 4, "y": 0}, "spin": "none"}
    state = state_with_piece("O", "I", "S", "Z", "J")
    state.hold = "T"
    state.can_hold = True
    action = action_for_tbp_move(move, state)
    assert action is not None
    placement = state.resolve(action)
    assert placement is not None and placement.piece == "T" and placement.hold


def test_action_mapping_rejects_invalid_suggestions():
    state = GameState(seed=0)
    assert action_for_tbp_move({"location": {"type": "T", "orientation": "north", "x": -9, "y": 0}}, state) is None
    assert action_for_tbp_move({"location": {"type": "Q", "orientation": "north", "x": 4, "y": 0}}, state) is None
    assert action_for_tbp_move({"location": {"type": "T", "orientation": "up", "x": 4, "y": 0}}, state) is None


def test_build_start_message_queue_and_combo_conventions():
    state = GameState(seed=0)
    current = state.current.name
    previews = state.preview(5)
    message = build_start_message(state)
    assert message["type"] == "start"
    # Cold Clear 2 reads queue[1] as the current piece when hold is null.
    assert message["queue"][0] == previews[0]
    assert message["queue"][1] == current
    assert message["queue"][2:] == previews
    assert message["hold"] is None
    assert message["combo"] == 0  # our -1 "no combo" maps to TBP's 0 clears
    assert message["back_to_back"] is False
    assert len(message["board"]) == 40

    state.hold = "T"
    state.can_hold = True
    held = build_start_message(state)
    assert held["queue"][0] == current
    assert held["hold"] == "T"

    state.clear_state.combo = 3
    assert build_start_message(state)["combo"] == 4


# ---------------------------------------------------------------------------
# Mock bot: adapter plumbing, lifecycle, fallbacks
# ---------------------------------------------------------------------------
def test_mock_adapter_encodes_state_and_accepts_move(tmp_path: Path):
    telemetry = tmp_path / "starts.jsonl"
    agent = TBPAgent(
        command=mock_command("--telemetry", str(telemetry)),
        allow_in_tests=True,
        think_time=0.0,
        timeout=3.0,
    )
    state = GameState(seed=0)
    expected = build_start_message(state)

    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.accepted == 1
    assert agent.stats.invalid_suggestions == 0
    assert agent.stats.fallbacks == 0
    assert agent.stats.engine_starts == 1
    assert agent.engine_info.get("name", "").startswith("Mock TBP Bot")

    lines = telemetry.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "start"
    assert record["message"] == expected  # byte-for-byte semantic roundtrip
    agent.terminate()


def test_mock_adapter_process_lifecycle(tmp_path: Path):
    telemetry = tmp_path / "starts.jsonl"
    agent = TBPAgent(
        command=mock_command("--telemetry", str(telemetry)),
        allow_in_tests=True,
        think_time=0.0,
        timeout=3.0,
    )
    agent.reset(0)
    state = GameState(seed=0)
    first = agent.choose_action(state)
    assert first in state.legal_actions()
    session = agent._session
    assert session is not None
    proc = session.proc
    assert proc.poll() is None  # engine process is alive after a move

    state.apply_action(first)
    second = agent.choose_action(state)
    assert second in state.legal_actions()
    assert agent.stats.accepted == 2
    assert len(telemetry.read_text(encoding="utf-8").splitlines()) == 2

    agent.terminate()
    assert agent._session is None
    assert proc.poll() is not None  # clean shutdown


def test_invalid_suggestion_falls_back_to_heuristic():
    agent = TBPAgent(
        command=mock_command("--mode", "invalid"),
        allow_in_tests=True,
        think_time=0.0,
        timeout=3.0,
    )
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.invalid_suggestions == 1
    assert agent.stats.accepted == 0
    assert agent.fallback_count == 1
    assert "not expressible" in agent.stats.last_error
    agent.terminate()


def test_empty_suggestion_is_retried_not_treated_as_failure():
    agent = TBPAgent(
        command=mock_command("--empty-first"),
        allow_in_tests=True,
        think_time=0.005,
        timeout=3.0,
    )
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.accepted == 1
    assert agent.stats.suggestions == 1
    assert agent.stats.fallbacks == 0
    agent.terminate()


def test_suggestion_timeout_falls_back():
    agent = TBPAgent(
        command=mock_command("--delay-ms", "400"),
        allow_in_tests=True,
        think_time=0.0,
        timeout=0.15,
    )
    state = GameState(seed=0)
    started = time.time()
    action = agent.choose_action(state)
    elapsed = time.time() - started
    assert action in state.legal_actions()
    assert agent.stats.timeouts == 1
    assert agent.fallback_count == 1
    assert elapsed < 2.0
    agent.terminate()


def test_missing_binary_falls_back(tmp_path: Path):
    agent = TBPAgent(
        binary=tmp_path / "does-not-exist",
        allow_in_tests=True,
        think_time=0.0,
        timeout=1.0,
    )
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.protocol_errors == 1
    assert agent.fallback_count == 1
    assert "not found" in agent.stats.last_error
    agent.terminate()


def test_refuses_to_launch_under_pytest_without_optin():
    # No allow_in_tests=True: the guard must refuse to spawn a process and the
    # adapter must fall back instead of crashing the test run.
    agent = TBPAgent(binary=DEFAULT_BINARY, allow_in_tests=False, think_time=0.0, timeout=1.0)
    state = GameState(seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.protocol_errors == 1
    assert "refuses to launch" in agent.stats.last_error
    assert agent._session is None


def test_mock_bot_class_is_explicitly_labelled_mock():
    assert "mock" in SBPMockBot.__doc__.lower()
    assert "not" in SBPMockBot.__doc__.lower() and "benchmark" in SBPMockBot.__doc__.lower()


# ---------------------------------------------------------------------------
# Real engine (skipped unless built)
# ---------------------------------------------------------------------------
real_engine = pytest.mark.skipif(
    not coldclear_available(),
    reason="Cold Clear 2 release binary not built (cargo build --release in third_party/cold-clear-2)",
)


@real_engine
def test_real_engine_smoke_actions():
    agent = TBPAgent(think_time=0.03, timeout=5.0, allow_in_tests=True)
    state = GameState(seed=0)
    try:
        for _ in range(4):
            action = agent.choose_action(state)
            assert action in state.legal_actions()
            state.apply_action(action)
    finally:
        agent.terminate()
    assert agent.stats.suggestions >= 4
    assert agent.stats.accepted >= 3
    assert agent.stats.protocol_errors == 0
    assert agent.stats.timeouts == 0


@real_engine
def test_real_engine_versus_match():
    engine = TBPAgent(think_time=0.03, timeout=5.0, allow_in_tests=True)
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
    assert engine.stats.suggestions > 0
    assert engine.stats.accepted > 0
    assert engine.stats.protocol_errors == 0
    assert list(match.invalid_actions) == [0, 0]
