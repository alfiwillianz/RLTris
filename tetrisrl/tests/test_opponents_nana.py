"""Tests for the nightcrab/nana TBP2 opponent adapter.

The path/config/start-message tests are pure Python and always run.  The
engine tests are skipped unless ``nana_tbp`` has been built in
``third_party/nana/build/cpp`` (or ``$TETRISRL_NANA_BIN`` points at a build).

No test spawns nana during collection: every real-engine test is marked
``skipif`` on :func:`nana_available` and passes ``allow_in_tests=True``
explicitly, and the inherited pytest guard is exercised by its own test.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from tetrisrl.agents.heuristic_agent import HeuristicAgent
from tetrisrl.agents.opponents.nana import (
    DEFAULT_NANA_BINARY,
    DEFAULT_NANA_THREADS,
    DEFAULT_THINK_TIME,
    DEFAULT_TIMEOUT,
    NANA_COMMIT,
    NANA_CONFIG_FILENAME,
    NANA_PROFILE,
    NanaAgent,
    build_nana_start_message,
    ensure_nana_config,
    nana_available,
    nana_binary_path,
    nana_config,
    nana_config_path,
)
from tetrisrl.agents.opponents.tbp import TBP_HEIGHT, action_for_tbp_move, tbp_move_cells
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.randomizer import FixedSequence
from tetrisrl.environment.versus import VersusMatch

real_engine = pytest.mark.skipif(
    not nana_available(),
    reason=(
        "nana_tbp release binary not built "
        "(cmake --build third_party/nana/build -j)"
    ),
)


def state_with_piece(*pieces: str, seed: int = 0) -> GameState:
    return GameState(seed=seed, piece_source=FixedSequence(list(pieces)))


def raw_move(piece: str, orientation: str, x: int, y: int):
    return {"location": {"type": piece, "orientation": orientation, "x": x, "y": y}, "spin": "none"}


def _engine_played(agent: NanaAgent) -> bool:
    return agent.stats.accepted + agent.stats.fallbacks > 0


# ---------------------------------------------------------------------------
# Availability / path / config (no engine needed)
# ---------------------------------------------------------------------------
def test_pinned_commit_constant():
    # Keep in sync with third_party/NANA_NOTICE.md.
    assert len(NANA_COMMIT) == 40
    assert all(c in "0123456789abcdef" for c in NANA_COMMIT)


def test_binary_path_default_and_env_override(monkeypatch):
    monkeypatch.delenv("TETRISRL_NANA_BIN", raising=False)
    assert nana_binary_path() == DEFAULT_NANA_BINARY
    assert nana_binary_path().name == "nana_tbp"

    monkeypatch.setenv("TETRISRL_NANA_BIN", "/tmp/elsewhere/nana_tbp")
    assert nana_binary_path() == Path("/tmp/elsewhere/nana_tbp")
    # An explicit argument beats the environment.
    assert nana_binary_path("/opt/nana/nana_tbp") == Path("/opt/nana/nana_tbp")


def test_config_path_is_beside_binary_and_env_overridable(monkeypatch, tmp_path):
    monkeypatch.delenv("TETRISRL_NANA_CONFIG", raising=False)
    binary = tmp_path / "bin" / "nana_tbp"
    assert nana_config_path(binary) == binary.parent / NANA_CONFIG_FILENAME

    monkeypatch.setenv("TETRISRL_NANA_CONFIG", "/tmp/template.json")
    assert nana_config_path(binary) == Path("/tmp/template.json")
    assert nana_config_path(binary, "/tmp/explicit.json") == Path("/tmp/explicit.json")


def test_availability_checks_executable(tmp_path):
    missing = tmp_path / "nope" / "nana_tbp"
    assert not nana_available(missing)
    # A non-executable regular file is not "available".
    placeholder = tmp_path / "nana_tbp"
    placeholder.write_text("not a binary")
    assert not os.access(placeholder, os.X_OK)
    assert not nana_available(placeholder)


def test_default_profile_is_tbp2_current_first_int_b2b_40_rows():
    assert NANA_PROFILE.tbp_version == 2
    assert NANA_PROFILE.queue_mode == "current_first"
    assert NANA_PROFILE.b2b_type == "int"
    assert NANA_PROFILE.board_rows == 40
    assert NANA_PROFILE.requires_opponents is True
    assert NANA_PROFILE.combo_offset == 1
    NANA_PROFILE.validate()


def test_think_time_and_timeout_defaults_are_mcts_friendly():
    assert 0.05 <= DEFAULT_THINK_TIME <= 0.5
    assert DEFAULT_TIMEOUT >= 5.0


def test_ensure_nana_config_writes_only_known_keys(tmp_path):
    path = tmp_path / "build" / "cpp" / NANA_CONFIG_FILENAME
    written = ensure_nana_config(path)
    assert written == path
    data = json.loads(path.read_text())
    # nana rejects unknown keys (Config.cpp), so this must stay minimal.
    assert data == {"rules": "tetrio", "threads": DEFAULT_NANA_THREADS}
    assert set(data) <= {"rules", "threads", "pin_layout", "variant"}

    # An existing file is not overwritten by default.
    path.write_text('{"rules": "tetrio", "threads": 1}\n')
    ensure_nana_config(path)
    assert json.loads(path.read_text())["threads"] == 1
    ensure_nana_config(path, threads=2, overwrite=True)
    assert json.loads(path.read_text())["threads"] == 2

    with pytest.raises(ValueError):
        ensure_nana_config(tmp_path / "bad.json", threads=0)
    with pytest.raises(ValueError):
        ensure_nana_config(tmp_path / "bad2.json", rules="guideline")

    assert nana_config() == {"rules": "tetrio", "threads": DEFAULT_NANA_THREADS}


# ---------------------------------------------------------------------------
# TBP2 start message (no engine needed)
# ---------------------------------------------------------------------------
def test_start_message_has_required_tbp2_fields_and_current_first_queue():
    state = state_with_piece("T", "I", "O", "S", "Z", "J", "L", seed=0)
    opponent = state_with_piece("L", "J", "S", "Z", "O", "T", "I", seed=1)
    message = build_nana_start_message(state, opponent)

    assert message["type"] == "start"
    # queue[0] is the current piece; the rest are previews (no CC2 reserve).
    assert message["queue"][0] == state.current.name == "T"
    assert message["queue"][1:] == state.preview(state.ruleset.board.preview)
    assert message["hold"] is None
    assert isinstance(message["back_to_back"], int)  # TBP2 native type
    assert isinstance(message["combo"], int)
    # Standard bottom-first 40-row board; nana only reads the bottom 32.
    assert len(message["board"]) == 40
    assert all(len(row) == 10 for row in message["board"])

    opponents = message["opponents"]
    assert isinstance(opponents, list) and len(opponents) == 1
    assert set(opponents[0]) >= {"board", "combo", "back_to_back", "queue", "hold", "meter"}
    assert len(opponents[0]["board"]) == 40


def test_start_message_meter_uses_opponent_pending_garbage():
    state = state_with_piece("T", "I", "O", seed=0)
    opponent = state_with_piece("L", "J", "S", seed=1)
    state.receive_attack(4)
    opponent.receive_attack(2)
    message = build_nana_start_message(state, opponent)

    # nana reads pending garbage from opponents[0]["meter"] (readOpponent),
    # not from the top-level player-1 meter.
    assert message["meter"] == state.garbage.total() == 4
    assert message["opponents"][0]["meter"] == opponent.garbage.total() == 2


def test_start_message_synthesises_opponent_when_none_given():
    # CRITICAL: nana dereferences message["opponents"][0] unconditionally and
    # dies without it, so the adapter must never omit the field.
    state = state_with_piece("T", "I", "O", seed=0)
    state.receive_attack(3)
    message = build_nana_start_message(state, None)
    opponent = message["opponents"][0]

    assert opponent["board"] == [[None] * 10 for _ in range(40)]
    assert opponent["meter"] == 0
    assert opponent["hold"] is None
    assert message["meter"] == 3


def test_start_message_combo_and_b2b_encoding():
    # TETR.IO combo -1 (no combo) must be sent as the TBP count 0.
    fresh = state_with_piece("T", "I", "O", seed=0)
    assert fresh.combo == -1
    assert build_nana_start_message(fresh, state_with_piece("L", seed=1))["combo"] == 0

    combo_state = state_with_piece("T", "I", "O", seed=0)
    combo_state.clear_state.combo = 2
    assert build_nana_start_message(combo_state, None)["combo"] == 3

    b2b_state = state_with_piece("T", "I", "O", seed=0)
    b2b_state.clear_state.b2b = 5
    message = build_nana_start_message(b2b_state, None)
    assert message["back_to_back"] == 5
    assert isinstance(message["back_to_back"], int)


# ---------------------------------------------------------------------------
# Lifecycle / guard paths (no real engine needed)
# ---------------------------------------------------------------------------
def test_refuses_to_launch_under_pytest_without_optin():
    agent = NanaAgent(allow_in_tests=False, think_time=0.0, timeout=1.0)
    state = state_with_piece("T", "I", "O", seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.protocol_errors == 1
    assert "refuses to launch" in agent.stats.last_error
    assert agent._session is None


def test_missing_binary_falls_back_with_nana_specific_error(tmp_path):
    agent = NanaAgent(
        binary=tmp_path / "does-not-exist",
        allow_in_tests=True,
        think_time=0.0,
        timeout=1.0,
    )
    state = state_with_piece("T", "I", "O", seed=0)
    action = agent.choose_action(state)
    assert action in state.legal_actions()
    assert agent.stats.protocol_errors == 1
    assert agent.fallback_count == 1
    assert "nana binary not found" in agent.stats.last_error
    agent.terminate()


def test_agent_is_named_nana_and_uses_tbp2_profile():
    agent = NanaAgent(allow_in_tests=False)
    assert agent.name == "nana"
    assert agent.profile.tbp_version == 2
    assert agent.profile.queue_mode == "current_first"
    assert agent.config_path.name == NANA_CONFIG_FILENAME
    agent.terminate()


# ---------------------------------------------------------------------------
# Real engine (skipped when not built)
# ---------------------------------------------------------------------------
@real_engine
def test_real_engine_handshake_reports_nana():
    agent = NanaAgent(allow_in_tests=True, timeout=5.0, think_time=0.0)
    try:
        session = agent._ensure_session()
        info = agent.engine_info
        assert session.alive()
        assert info.get("name") == "Nana"
        assert agent.stats.engine_starts == 1
    finally:
        agent.terminate()
    assert agent._session is None


@real_engine
def test_real_engine_raw_suggestions_are_legal_placements():
    """Decode raw suggestions: no collisions and every piece comes to rest."""
    agent = NanaAgent(allow_in_tests=True, timeout=10.0, think_time=0.05)
    state = state_with_piece("T", "I", "O", "S", "Z", "J", "L", "I", "O", "T", seed=3)
    opponent = state_with_piece("L", "J", "S", "Z", "O", "T", "I", seed=4)
    try:
        session = agent._ensure_session()
        checked = 0
        mapped = 0
        for _ in range(6):
            session.drain()
            session.send(build_nana_start_message(state, opponent))
            session.send({"type": "suggest"})
            reply = session.wait_for(("suggestion",), 10.0)
            moves = reply.get("moves") or []
            assert moves, "nana returned no moves for a live board"
            piece, cells = tbp_move_cells(moves[0], state.board.height)
            assert piece in "IJLOSTZ"
            assert len(cells) == 4
            occupied = {
                (x, y)
                for y in range(state.board.height)
                for x in range(state.board.width)
                if (state.board.rows[y] >> x) & 1
            }
            assert not (cells & occupied), f"nana placement overlaps the board: {moves[0]}"
            resting = any(y + 1 >= state.board.height or (x, y + 1) in occupied for x, y in cells)
            assert resting, f"nana placement does not rest: {moves[0]}"
            action = action_for_tbp_move(moves[0], state)
            if action is not None:
                assert action in state.legal_actions()
                mapped += 1
            else:
                # A tuck/slide can appear once the stack forms; that is the
                # documented action-space gap, not a coordinate-mapping bug.
                action = state.legal_actions()[0]
            state.apply_action(action)
            checked += 1
        assert checked == 6
        assert mapped >= 4, "nana's geometry stopped mapping to hard-drop actions"
    finally:
        agent.terminate()


@real_engine
def test_real_engine_smoke_actions_and_counters():
    agent = NanaAgent(allow_in_tests=True, timeout=10.0, think_time=0.05)
    state = state_with_piece("T", "I", "O", "S", "Z", "J", "L", "I", seed=0)
    opponent = state_with_piece("L", "J", "S", "Z", "O", "T", "I", "L", seed=1)
    try:
        for _ in range(6):
            action = agent.choose_action(state, opponent)
            assert action in state.legal_actions()
            state.apply_action(action)
    finally:
        agent.terminate()
    assert agent.stats.suggestions >= 6
    assert agent.stats.accepted >= 1
    assert agent.stats.protocol_errors == 0
    assert agent.stats.timeouts == 0


@real_engine
def test_real_engine_choose_action_without_opponent_state_uses_synthetic_opponent():
    # VersusMatch always passes an opponent, but a standalone caller may not.
    # The adapter must still send opponents[0], so this must not kill nana.
    agent = NanaAgent(allow_in_tests=True, timeout=10.0, think_time=0.05)
    state = state_with_piece("T", "I", "O", "S", "Z", "J", "L", seed=2)
    try:
        action = agent.choose_action(state)  # no opponent_state
    finally:
        agent.terminate()
    assert action in state.legal_actions()
    assert agent.stats.accepted == 1
    assert agent.stats.fallbacks == 0
    assert agent.stats.protocol_errors == 0


@real_engine
def test_real_engine_missing_opponents_kills_the_process():
    """Source guard: ``start`` without ``opponents[0]`` is fatal for nana."""
    binary = str(nana_binary_path())
    proc = subprocess.Popen(
        [binary],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        info = json.loads(proc.stdout.readline())
        assert info["type"] == "info"

        def send(message):
            # nana uses std::cin >>, so messages must be compact JSON.
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            proc.stdin.flush()

        send({"type": "rules"})
        assert json.loads(proc.stdout.readline())["type"] == "ready"
        empty = [[None] * 10 for _ in range(TBP_HEIGHT)]
        send(
            {
                "type": "start",
                "board": empty,
                "queue": ["T", "I", "O", "S", "Z", "J", "L"],
                "hold": None,
                "combo": 0,
                "back_to_back": 0,
                "meter": 0,
            }
        )
        if proc.stdin is not None:
            proc.stdin.close()
        code = proc.wait(timeout=10.0)
        assert code != 0, "nana accepted a start without opponents (guard changed?)"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)


@real_engine
def test_real_engine_versus_match_smoke():
    engine = NanaAgent(allow_in_tests=True, timeout=10.0, think_time=0.05)
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
    assert engine.stats.timeouts == 0
    assert _engine_played(engine), "engine never made a move (accepted or fallback)"
    assert list(match.invalid_actions) == [0, 0]
