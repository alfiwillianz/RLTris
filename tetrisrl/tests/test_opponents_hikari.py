"""Tests for the SoRA-X7/hikari_rei TBP opponent adapter.

The wire-format and geometry tests are pure Python and always run.  The engine
tests are skipped unless the Rust binary has been built with
``cargo build --release`` in ``third_party/hikari_rei`` (or
``$TETRISRL_HIKARI_BIN`` points at a build).

The conventions asserted here were verified against the live binary; see
``docs/integration_hikari.md`` for the probe transcripts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tetrisrl.agents.heuristic_agent import HeuristicAgent
from tetrisrl.agents.opponents.hikari import (
    DEFAULT_HIKARI_BINARY,
    HIKARI_BOARD_ROWS,
    HIKARI_COMMIT,
    HIKARI_PROFILE,
    HikariAgent,
    build_hikari_start_message,
    hikari_available,
    hikari_binary_path,
)
from tetrisrl.agents.opponents.tbp import (
    TBP_HEIGHT,
    TBPSession,
    action_for_tbp_move,
    tbp_move_cells,
)
from tetrisrl.environment.board import Board
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.randomizer import FixedSequence
from tetrisrl.environment.versus import VersusMatch

real_engine = pytest.mark.skipif(
    not hikari_available(),
    reason=(
        "hikari_rei release binary not built "
        "(cargo build --release in third_party/hikari_rei)"
    ),
)


def state_with_piece(*pieces: str, seed: int = 0) -> GameState:
    return GameState(seed=seed, piece_source=FixedSequence(list(pieces)))


def raw_move(piece: str, orientation: str, x: int, y: int):
    return {"location": {"type": piece, "orientation": orientation, "x": x, "y": y}, "spin": "none"}


def wire_row_occupied(rows, index: int, column: int) -> bool:
    return rows[index][column] is not None


def _engine_played(agent: HikariAgent) -> bool:
    return agent.stats.accepted + agent.stats.fallbacks > 0


# ---------------------------------------------------------------------------
# Availability / path resolution (no engine needed)
# ---------------------------------------------------------------------------
def test_pinned_commit_constant():
    # Keep in sync with third_party/HIKARI_NOTICE.md.
    assert len(HIKARI_COMMIT) == 40
    assert all(c in "0123456789abcdef" for c in HIKARI_COMMIT)


def test_binary_path_default_and_env_override(monkeypatch):
    monkeypatch.delenv("TETRISRL_HIKARI_BIN", raising=False)
    assert hikari_binary_path() == DEFAULT_HIKARI_BINARY
    assert hikari_binary_path().name == "hikari_rei"

    monkeypatch.setenv("TETRISRL_HIKARI_BIN", "/tmp/somewhere/hikari_rei")
    assert hikari_binary_path() == Path("/tmp/somewhere/hikari_rei")
    # An explicit argument beats the environment.
    assert hikari_binary_path("/opt/hikari/hikari_rei") == Path("/opt/hikari/hikari_rei")


def test_availability_missing_binary(tmp_path):
    assert not hikari_available(tmp_path / "nope" / "hikari_rei")


def test_profile_matches_verified_conventions():
    assert HIKARI_PROFILE.name == "hikari"
    assert HIKARI_PROFILE.queue_mode == "current_first"
    assert HIKARI_PROFILE.b2b_type == "bool"
    assert HIKARI_PROFILE.combo_offset == 1
    assert HIKARI_PROFILE.board_rows == HIKARI_BOARD_ROWS == 24
    assert HIKARI_PROFILE.tbp_version == 1
    assert HIKARI_PROFILE.requires_opponents is False
    HIKARI_PROFILE.validate()


def test_agent_metadata_and_launch_command():
    agent = HikariAgent(allow_in_tests=True)
    assert agent.name == "hikari"
    assert agent.binary == hikari_binary_path()
    assert agent.profile is HIKARI_PROFILE
    command = agent._launch_command()
    assert command[0].endswith("hikari_rei")
    assert command[1] == "tbp"
    assert command[command.index("--threads") + 1] == "1"
    agent.terminate()

    capped = HikariAgent(threads=2, max_nodes=1000, no_hold=True, allow_in_tests=True)
    command = capped._launch_command()
    assert command[command.index("--threads") + 1] == "2"
    assert command[command.index("--max-nodes") + 1] == "1000"
    assert "--no-hold" in command
    capped.terminate()

    overridden = HikariAgent(command=["/bin/false", "tbp"], allow_in_tests=True)
    assert overridden._launch_command() == ["/bin/false", "tbp"]
    overridden.terminate()


def test_missing_binary_falls_back_cleanly(tmp_path):
    agent = HikariAgent(binary=tmp_path / "absent" / "hikari_rei", allow_in_tests=True)
    state = state_with_piece("O", "I", "T", "S", "Z")
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.fallbacks == 1
    assert agent.stats.protocol_errors == 1
    assert "not found" in agent.stats.last_error
    assert agent._session is None
    agent.terminate()


# ---------------------------------------------------------------------------
# Wire encoding: queue / board rows / combo / b2b
# ---------------------------------------------------------------------------
def test_start_message_queue_is_current_first():
    """Hikari's Search::start treats queue[0] as the active piece."""
    state = state_with_piece("T", "I", "O", "S", "Z", "J", "L")
    message = build_hikari_start_message(state)
    assert message["type"] == "start"
    assert message["queue"][0] == "T" == state.current.name
    assert message["queue"] == ["T", *state.preview(len(message["queue"]) - 1)]
    assert message["hold"] is None
    assert message["combo"] == 0  # TETR.IO -1 (no combo) -> Hikari ren 0
    assert message["back_to_back"] is False
    assert "randomizer" not in message and "bag" not in message

    # With a hold piece the current piece is still queue[0].
    state.hold_swap()
    assert state.hold == "T"
    held = build_hikari_start_message(state)
    assert held["queue"][0] == state.current.name
    assert held["hold"] == "T"


def test_start_message_combo_and_b2b_conventions():
    """Wire combo is Hikari's `ren` count; TETR.IO combo -1 -> 0, 0 -> 1."""
    state = state_with_piece("I", "O", "T", "S", "Z")
    assert state.combo == -1
    assert build_hikari_start_message(state)["combo"] == 0

    for tetrio_combo, expected in ((0, 1), (3, 4), (24, 25)):
        state.clear_state.combo = tetrio_combo
        assert build_hikari_start_message(state)["combo"] == expected

    state.clear_state.b2b = 0
    assert build_hikari_start_message(state)["back_to_back"] is False
    state.clear_state.b2b = 2
    message = build_hikari_start_message(state)
    assert message["back_to_back"] is True
    assert isinstance(message["back_to_back"], bool)


def test_board_is_bottom_first_24_rows():
    """We send our bottom 24 rows (rows 39..16); rows 0..15 are not sent."""
    state = state_with_piece("T", "I", "O", "S", "Z")
    state.board = Board(10, 40, 20)
    state.board.rows[39] = 1 << 0  # floor, left column
    state.board.rows[16] = 1 << 9  # Hikari's top row (wire index 23)
    state.board.rows[20] = 1 << 3  # wire index 19
    state.board.rows[15] = 1 << 5  # above Hikari's board: must not be sent

    message = build_hikari_start_message(state)
    rows = message["board"]
    assert len(rows) == HIKARI_BOARD_ROWS == 24
    assert all(len(row) == 10 for row in rows)
    # Wire row 0 is the bottom of our board.
    assert wire_row_occupied(rows, 0, 0)
    # Wire row 23 is our row 16; wire row 19 is our row 20.
    assert wire_row_occupied(rows, 23, 9)
    assert wire_row_occupied(rows, 19, 3)
    # Our row 15 is outside Hikari's 24-row frame and is never transmitted.
    assert all(row[5] is None for row in rows)
    # Occupied cells are strings, empty cells are JSON null.
    assert rows[0][0] == "#" and rows[0][1] is None


def test_board_rows_must_be_full_height():
    state = state_with_piece("T", "I", "O")
    state.board = Board(10, 20, 20)
    with pytest.raises(Exception):
        build_hikari_start_message(state)


# ---------------------------------------------------------------------------
# Suggestion geometry: live wire moves must map to our legal actions
# ---------------------------------------------------------------------------
#: (piece, orientation, x, y) -> absolute cells in our top-down 40-row frame,
#: recorded from live Hikari suggestions on an empty board (see the integration
#: doc).  These are the standard TBP true-rotation-centre coordinates.
LIVE_EMPTY_BOARD_MOVES = {
    "T": (raw_move("T", "north", 1, 0), {(0, 39), (1, 38), (1, 39), (2, 39)}),
    "I": (raw_move("I", "north", 4, 0), {(3, 39), (4, 39), (5, 39), (6, 39)}),
    "O": (raw_move("O", "north", 8, 0), {(8, 38), (9, 38), (8, 39), (9, 39)}),
    "S": (raw_move("S", "north", 5, 0), {(4, 39), (5, 38), (5, 39), (6, 38)}),
    "Z": (raw_move("Z", "north", 8, 0), {(7, 38), (8, 38), (8, 39), (9, 39)}),
    "J": (raw_move("J", "north", 1, 0), {(0, 38), (0, 39), (1, 39), (2, 39)}),
    "L": (raw_move("L", "north", 7, 0), {(6, 39), (7, 39), (8, 38), (8, 39)}),
}


def test_live_moves_decode_to_expected_cells_and_actions():
    for piece, (move, expected) in LIVE_EMPTY_BOARD_MOVES.items():
        decoded_piece, cells = tbp_move_cells(move, TBP_HEIGHT)
        assert decoded_piece == piece
        assert cells == expected, f"{piece} decoded cells differ: {sorted(cells)}"

        state = state_with_piece(piece, "I", "O", "S", "Z")
        action = action_for_tbp_move(move, state)
        assert action is not None, f"{piece} move did not map to a legal action"
        assert action in state.legal_actions()
        placement = state.resolve(action)
        assert placement is not None
        assert placement.piece == piece
        assert set(placement.cells) == expected


def test_hold_suggestion_maps_to_hold_action():
    """A suggestion for the held piece must select our hold action."""
    state = state_with_piece("J", "I", "O", "S", "Z")
    state.hold = "T"
    state.can_hold = True
    move, expected = LIVE_EMPTY_BOARD_MOVES["T"]
    action = action_for_tbp_move(move, state)
    assert action is not None
    assert action in state.legal_actions()
    placement = state.resolve(action)
    assert placement is not None
    assert placement.piece == "T"
    assert bool(placement.hold) is True
    assert set(placement.cells) == expected


def test_empty_hold_suggestion_maps_to_empty_hold_action():
    """With hold empty, Hikari's next-piece (empty hold) move maps to hold=True."""
    state = state_with_piece("J", "T", "I", "O", "S")
    assert state.hold is None
    move, expected = LIVE_EMPTY_BOARD_MOVES["T"]  # T is the next preview
    action = action_for_tbp_move(move, state)
    assert action is not None
    placement = state.resolve(action)
    assert placement is not None
    assert placement.piece == "T"
    assert bool(placement.hold) is True
    assert set(placement.cells) == expected


# ---------------------------------------------------------------------------
# Real engine (skipped unless built)
# ---------------------------------------------------------------------------
@real_engine
def test_real_engine_handshake_reports_hikari():
    agent = HikariAgent(allow_in_tests=True, timeout=5.0)
    try:
        session = agent._ensure_session()
        info = agent.engine_info
        assert session.alive()
        assert info.get("name") == "Hikari Rust"
        assert info.get("author") == "SoRA_X7"
        assert info.get("version") == "0.2.0"
        assert info.get("reference_commit") == "90aef085a53d6048cbd19de7f4c9c53a6f3c8960"
        assert agent.stats.engine_starts == 1
    finally:
        agent.terminate()
    assert agent._session is None


@real_engine
def test_real_engine_echoes_wire_conventions():
    """Live check: 24-row board orientation, queue[0], combo->ren, b2b bool."""
    agent = HikariAgent(allow_in_tests=True, timeout=5.0)
    state = state_with_piece("T", "I", "O", "S", "Z", "J", "L")
    state.board.rows[39] = 1 << 0
    state.board.rows[16] = 1 << 9
    state.board.rows[20] = 1 << 3
    state.board.rows[15] = 1 << 5
    state.clear_state.combo = 2
    state.clear_state.b2b = 1
    try:
        session: TBPSession = agent._ensure_session()
        session.drain()
        session.send(build_hikari_start_message(state))
        session.send({"type": "suggest"})
        reply = session.wait_for(("suggestion", "error"), 5.0)
        assert reply.get("type") == "suggestion", reply
        echoed = reply["board"]
        assert len(echoed["rows"]) == HIKARI_BOARD_ROWS
        assert echoed["rows"][0] & 1  # our floor row
        assert echoed["rows"][23] & (1 << 9)  # our row 16
        assert echoed["rows"][19] & (1 << 3)  # our row 20
        # Our row 15 (column 5) is above Hikari's board and must not appear.
        assert not any(row & (1 << 5) for row in echoed["rows"])
        assert echoed["ren"] == 3  # TETR.IO combo 2 -> Hikari ren 3
        assert echoed["back_to_back"] is True
        assert reply["queue"][0] == "T"  # current piece is queue[0]
        assert reply["moves"], "engine returned no move for an empty board"
    finally:
        agent.terminate()


@real_engine
def test_real_engine_rejects_non_empty_rows_above_23():
    """40-row wire boards are accepted only while rows 24..39 stay empty."""
    agent = HikariAgent(allow_in_tests=True, timeout=5.0)
    try:
        session: TBPSession = agent._ensure_session()
        rows = [[None] * 10 for _ in range(TBP_HEIGHT)]
        rows[24][4] = "#"  # first row outside Hikari's 24-row board
        session.send(
            {
                "type": "start",
                "board": rows,
                "queue": ["T", "I", "O"],
                "hold": None,
                "combo": 0,
                "back_to_back": False,
            }
        )
        reply = session.read_message(5.0)
        assert reply.get("type") == "error"
        assert "rows 0 through 23" in reply.get("reason", "")
    finally:
        agent.terminate()


@real_engine
def test_real_engine_smoke_actions_and_counters():
    agent = HikariAgent(allow_in_tests=True, think_time=0.01, timeout=5.0)
    state = GameState(seed=0)
    try:
        for _ in range(6):
            action = agent.choose_action(state)
            assert action in state.legal_actions()
            state.apply_action(action)
    finally:
        agent.terminate()
    assert agent.stats.suggestions >= 6
    assert agent.stats.accepted >= 1
    assert agent.stats.protocol_errors == 0
    assert agent.stats.timeouts == 0
    assert agent.stats.nodes_total > 0
    assert agent.stats.last_move_info  # Hikari returns move_info


@real_engine
def test_real_engine_versus_match_smoke():
    engine = HikariAgent(allow_in_tests=True, think_time=0.01, timeout=5.0)
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
    assert result.winner in (0, 1, None)
    assert engine.stats.suggestions > 0
    assert engine.stats.protocol_errors == 0
    assert _engine_played(engine), "engine never made a move (accepted or fallback)"
    assert list(match.invalid_actions) == [0, 0]


@real_engine
def test_pytest_guard_refuses_launch_without_opt_in():
    """The inherited guard must prevent accidental engine launches in tests."""
    from tetrisrl.agents.opponents.tbp import TBPError

    agent = HikariAgent(allow_in_tests=False)
    with pytest.raises(TBPError, match="refuses to launch"):
        agent._ensure_session()
    assert agent._session is None
    agent.terminate()
