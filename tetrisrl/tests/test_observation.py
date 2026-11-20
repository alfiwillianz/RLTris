"""Observation encoding: layout, determinism, information boundaries."""

from __future__ import annotations

import numpy as np
import pytest

from tetrisrl.environment.engine import GameState
from tetrisrl.environment.observation import (
    OBS_VERSION,
    SCALARS,
    ObservationEncoder,
    structured_observation,
)


def test_encoder_size_matches_layout():
    enc = ObservationEncoder(include_opponent=True, preview=5)
    layout = enc.layout()
    assert layout["scalars"][1] == enc.size
    assert enc.size == 400 + 400 + 10 + 10 + 8 + 35 + 7 + 4 + len(SCALARS)


def test_encoder_without_opponent_is_smaller():
    with_opp = ObservationEncoder(include_opponent=True)
    without = ObservationEncoder(include_opponent=False)
    assert without.size == with_opp.size - 400 - 10
    assert "opponent_board" not in without.layout()


def test_encoding_is_deterministic_and_float32():
    enc = ObservationEncoder()
    s = GameState(seed=3)
    a = enc.encode(s)
    b = enc.encode(s)
    assert a.dtype == np.float32
    assert np.array_equal(a, b)
    assert a.shape[0] == enc.size


def test_encoding_reflects_board_changes():
    enc = ObservationEncoder()
    s = GameState(seed=3)
    before = enc.encode(s).copy()
    s.board.rows[39] = 0b11
    after = enc.encode(s)
    assert not np.array_equal(before, after)


def test_encoder_does_not_leak_future_pieces():
    enc = ObservationEncoder(preview=5)
    s = GameState(seed=7)
    before = enc.encode(s).copy()
    # Mutate only the bag beyond the visible preview.
    if hasattr(s.piece_source, "_queue"):
        s.piece_source._queue[12] = "S" if s.piece_source._queue[12] != "S" else "Z"
    after = enc.encode(s)
    assert np.array_equal(before, after)


def test_preview_changes_do_change_observation():
    enc = ObservationEncoder(preview=5)
    s = GameState(seed=7)
    before = enc.encode(s).copy()
    if hasattr(s.piece_source, "_queue"):
        s.piece_source._queue[0] = "S" if s.piece_source._queue[0] != "S" else "Z"
    after = enc.encode(s)
    assert not np.array_equal(before, after)


def test_structured_observation_fields():
    s = GameState(seed=1)
    opp = GameState(seed=2)
    obs = structured_observation(s, opp)
    assert obs.current_piece in "IJLOSTZ"
    assert len(obs.heights) == 10
    assert len(obs.next_pieces) == 5
    assert obs.opponent_board is not None
    d = obs.as_dict()
    assert d["current_piece"] == obs.current_piece


def test_scalars_bounded():
    enc = ObservationEncoder()
    s = GameState(seed=4)
    vec = enc.encode(s)
    assert np.isfinite(vec).all()
    start, end = enc.layout()["scalars"]
    assert (vec[start:end] >= 0).all()
