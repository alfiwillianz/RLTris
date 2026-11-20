"""Tests for the RIKU0804/tetris-ai TBP opponent adapter.

The geometry/normalisation/queue-convention tests are pure Python and always
run.  The engine tests are skipped unless the Rust binary has been built with
``cargo build --release`` in ``third_party/riku-tetris-ai/core-rs`` (or
``$TETRISRL_RIKU_BIN`` points at a build).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tetrisrl.agents.heuristic_agent import HeuristicAgent
from tetrisrl.agents.opponents.riku import (
    DEFAULT_RIKU_BINARY,
    RIKU_COMMIT,
    RIKU_ORIENTATIONS,
    RIKU_SHAPES,
    RikuAgent,
    build_riku_start_message,
    normalise_riku_move,
    riku_available,
    riku_binary_path,
    riku_move_cells,
    riku_weights_path,
)
from tetrisrl.agents.opponents.tbp import TBP_HEIGHT, action_for_tbp_move, tbp_move_cells
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.pieces import CELLS
from tetrisrl.environment.randomizer import FixedSequence
from tetrisrl.environment.versus import VersusMatch

real_engine = pytest.mark.skipif(
    not riku_available(),
    reason=(
        "RIKU tetris-core release binary not built "
        "(cargo build --release in third_party/riku-tetris-ai/core-rs)"
    ),
)


def state_with_piece(*pieces: str, seed: int = 0) -> GameState:
    return GameState(seed=seed, piece_source=FixedSequence(list(pieces)))


def raw_move(piece: str, orientation: str, x: int, y: int):
    return {"location": {"type": piece, "orientation": orientation, "x": x, "y": y}, "spin": "none"}


def _engine_played(agent: RikuAgent) -> bool:
    return agent.stats.accepted + agent.stats.fallbacks > 0


# ---------------------------------------------------------------------------
# Availability / path resolution (no engine needed)
# ---------------------------------------------------------------------------
def test_pinned_commit_constant():
    # The adapter documents the commit it was verified against; keep it in sync
    # with third_party/RIKU_NOTICE.md.
    assert len(RIKU_COMMIT) == 40
    assert all(c in "0123456789abcdef" for c in RIKU_COMMIT)


def test_binary_path_default_and_env_override(monkeypatch):
    monkeypatch.delenv("TETRISRL_RIKU_BIN", raising=False)
    assert riku_binary_path() == DEFAULT_RIKU_BINARY
    assert riku_binary_path().name == "tetris-core"

    monkeypatch.setenv("TETRISRL_RIKU_BIN", "/tmp/somewhere/tetris-core")
    assert riku_binary_path() == Path("/tmp/somewhere/tetris-core")
    # An explicit argument beats the environment.
    assert riku_binary_path("/opt/riku/tetris-core") == Path("/opt/riku/tetris-core")


def test_availability_and_weights_resolution(tmp_path):
    missing = tmp_path / "nope" / "tetris-core"
    assert not riku_available(missing)
    assert riku_weights_path(tmp_path / "missing.json") is None


def test_move_geometry_matches_project_rotation_cells():
    """RIKU's SHAPES table must equal our SRS rotation states up to a box shift."""
    for piece, states in RIKU_SHAPES.items():
        for rot in range(4):
            ours = set(CELLS[piece][rot])
            theirs = set(states[rot])
            candidates = {(ox - tx, oy - ty) for ox, oy in ours for tx, ty in theirs}
            translations = {
                (dx, dy)
                for dx, dy in candidates
                if {(x + dx, y + dy) for x, y in theirs} == ours
            }
            assert translations, f"{piece} rotation {rot} geometry differs from our engine"


def test_riku_move_cells_uses_box_origin_convention():
    # RIKU encodes its bounding-box origin as (x - 1, 38 - y); the O piece sits
    # in a 3-wide box, so a wire x=1..2 removes any ambiguity about that shift.
    piece, cells = riku_move_cells(raw_move("T", "north", 4, 0))
    assert piece == "T"
    assert cells == {(3, 39), (4, 38), (4, 39), (5, 39)}

    # I south (180) at the floor: RIKU's own box convention puts the bar on
    # row 39 (this is the placement the engine intended), not on row 38.
    _, i_cells = riku_move_cells(raw_move("I", "south", 4, 1))
    assert i_cells == {(3, 39), (4, 39), (5, 39), (6, 39)}

    # O at the left wall: box columns 1-2 of a 3-wide box -> board columns 0-1.
    _, o_cells = riku_move_cells(raw_move("O", "north", 0, 0))
    assert o_cells == {(0, 38), (1, 38), (0, 39), (1, 39)}

    with pytest.raises(Exception):
        riku_move_cells(raw_move("T", "north", 4, 40))
    with pytest.raises(Exception):
        riku_move_cells(raw_move("X", "north", 4, 0))


def test_normalise_move_roundtrip_for_all_piece_orientations():
    """normalised moves must decode (via tbp.tbp_move_cells) to the same cells."""
    checked = 0
    for piece in RIKU_SHAPES:
        for orientation in RIKU_ORIENTATIONS:
            for x, y in ((5, 0), (3, 1), (7, 4), (2, 2), (6, 0)):
                move = raw_move(piece, orientation, x, y)
                try:
                    expected_piece, expected_cells = riku_move_cells(move)
                except Exception:
                    continue  # this anchor is outside the board for this state
                normalised = normalise_riku_move(move)
                assert normalised["location"]["type"] == piece
                decoded_piece, decoded_cells = tbp_move_cells(normalised)
                assert decoded_piece == expected_piece
                assert decoded_cells == expected_cells
                checked += 1
    assert checked >= 40  # most of the 7 * 4 * 5 combinations are in bounds


def test_normalised_move_maps_to_legal_action_on_empty_board():
    state = state_with_piece("I", "O", "T", "S", "Z")
    raw = raw_move("I", "south", 4, 1)  # bar on the floor, columns 3-6
    action = action_for_tbp_move(normalise_riku_move(raw), state)
    assert action is not None
    placement = state.resolve(action)
    assert placement is not None and placement.piece == "I"
    assert set(placement.cells) == {(3, 39), (4, 39), (5, 39), (6, 39)}


def test_start_message_uses_current_first_queue():
    """RIKU always treats queue[0] as the current piece (unlike Cold Clear 2)."""
    state = state_with_piece("T", "I", "O", "S", "Z", "J", "L")
    message = build_riku_start_message(state)
    assert message["type"] == "start"
    assert message["queue"][0] == "T"
    assert message["queue"] == ["T", *state.preview(len(message["queue"]) - 1)]
    assert message["hold"] is None
    assert message["combo"] == 0  # TETR.IO -1 -> TBP 0
    assert message["back_to_back"] is False
    assert len(message["board"]) == TBP_HEIGHT
    assert all(len(row) == 10 for row in message["board"])

    state.hold_swap()
    assert state.hold == "T"
    held = build_riku_start_message(state)
    assert held["queue"][0] == state.current.name
    assert held["hold"] == "T"

    state.apply_action(state.legal_actions()[0])
    assert build_riku_start_message(state)["queue"][0] == state.current.name


def test_launch_command_contains_tbp_subcommand_and_weights():
    agent = RikuAgent(weights=None, width=24, depth=4, allow_in_tests=True)
    command = agent._launch_command()
    assert command[1] == "tbp"
    assert command[command.index("--width") + 1] == "24"
    assert command[command.index("--depth") + 1] == "4"
    if agent.weights is not None:
        assert "--weights" in command
        assert Path(command[command.index("--weights") + 1]) == agent.weights
    agent.terminate()

    overridden = RikuAgent(command=["/bin/false", "tbp"], allow_in_tests=True)
    assert overridden._launch_command() == ["/bin/false", "tbp"]
    overridden.terminate()


def test_explicit_missing_weights_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        RikuAgent(weights=tmp_path / "absent-weights.json", allow_in_tests=True)


def test_missing_binary_falls_back_cleanly(tmp_path):
    agent = RikuAgent(binary=tmp_path / "absent" / "tetris-core", allow_in_tests=True)
    state = state_with_piece("O", "I", "T", "S", "Z")
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.fallbacks == 1
    assert agent.stats.protocol_errors == 1
    assert "not found" in agent.stats.last_error
    assert agent._session is None
    agent.terminate()


def test_agent_metadata():
    agent = RikuAgent(allow_in_tests=True)
    assert agent.name == "riku"
    assert agent.binary == riku_binary_path()
    agent.terminate()


# ---------------------------------------------------------------------------
# Real engine (skipped unless built)
# ---------------------------------------------------------------------------
@real_engine
def test_real_engine_handshake_reports_riku():
    agent = RikuAgent(allow_in_tests=True, timeout=5.0)
    try:
        session = agent._ensure_session()
        info = agent.engine_info
        assert session.alive()
        assert info.get("name") == "RikuBot"
        assert info.get("author") == "riku"
        assert agent.stats.engine_starts == 1
    finally:
        agent.terminate()
    assert agent._session is None


@real_engine
def test_real_engine_raw_suggestions_are_valid_placements():
    """Decode raw suggestions: no collisions and every piece comes to rest."""
    agent = RikuAgent(allow_in_tests=True, timeout=5.0)
    state = state_with_piece(
        "T", "I", "O", "S", "Z", "J", "L", "I", "O", "T", seed=3
    )
    try:
        session = agent._ensure_session()
        checked = 0
        for _ in range(8):
            session.drain()
            session.send(build_riku_start_message(state))
            session.send({"type": "suggest"})
            reply = session.wait_for(("suggestion",), 5.0)
            moves = reply.get("moves") or []
            assert moves, "engine returned no moves for a live board"
            piece, cells = riku_move_cells(moves[0])
            assert piece in CELLS
            assert len(cells) == 4
            occupied = {
                (x, y)
                for y in range(state.board.height)
                for x in range(state.board.width)
                if (state.board.rows[y] >> x) & 1
            }
            assert not (cells & occupied), f"engine placement overlaps the board: {moves[0]}"
            resting = any(y + 1 >= state.board.height or (x, y + 1) in occupied for x, y in cells)
            assert resting, f"engine placement does not rest: {moves[0]}"
            action = action_for_tbp_move(normalise_riku_move(moves[0]), state)
            if action is not None:
                assert action in state.legal_actions()
                state.apply_action(action)
            checked += 1
        assert checked == 8
    finally:
        agent.terminate()


@real_engine
def test_real_engine_smoke_actions_and_counters():
    agent = RikuAgent(allow_in_tests=True, timeout=5.0)
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


@real_engine
def test_real_engine_versus_match_smoke():
    engine = RikuAgent(allow_in_tests=True, timeout=5.0)
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
