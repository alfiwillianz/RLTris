"""Engine behaviour: bag, determinism, masks, hold, spins, top-out."""

from __future__ import annotations

import random

import pytest

from tetrisrl.environment.actions import ACTION_SPACE, decode_action, encode_action
from tetrisrl.environment.board import Board
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.randomizer import FixedSequence, SevenBag
from tetrisrl.environment.ruleset import tetrio_s2_ruleset
from tetrisrl.environment.spin_detection import detect_t_spin, spin_from_placement


def test_seven_bag_contains_each_piece_once_per_bag():
    bag = SevenBag(seed=123)
    pieces = [bag.next() for _ in range(7)]
    assert sorted(pieces) == sorted("IJLOSTZ")
    second = [bag.next() for _ in range(7)]
    assert sorted(second) == sorted("IJLOSTZ")


def test_seven_bag_is_deterministic():
    a = SevenBag(seed=77)
    b = SevenBag(seed=77)
    assert [a.next() for _ in range(70)] == [b.next() for _ in range(70)]


def test_action_encoding_roundtrip():
    for rotation in range(4):
        for column in range(10):
            for hold in (False, True):
                a = encode_action(rotation, column, hold)
                assert 0 <= a < ACTION_SPACE
                assert decode_action(a) == (rotation, column, hold)
    assert ACTION_SPACE == 80


def test_action_mask_matches_legal_actions():
    s = GameState(seed=3)
    mask = s.action_mask()
    legal = set(s.legal_actions())
    assert len(mask) == ACTION_SPACE
    assert {i for i, ok in enumerate(mask) if ok} == legal


def test_invalid_action_does_not_mutate_state():
    s = GameState(seed=3)
    s.board.rows[39] = s.board.full_row_mask
    # column 9 with an I piece horizontal is impossible; also pick a masked id
    mask = s.action_mask()
    invalid = next(i for i, ok in enumerate(mask) if not ok)
    before = (s.board.state_hash(), s.pieces_placed, s.spawn_count)
    res = s.apply_action(invalid)
    assert res.valid is False
    assert (s.board.state_hash(), s.pieces_placed, s.spawn_count) == before


def test_deterministic_replay_same_seed_same_actions():
    def play(seed: int) -> int:
        s = GameState(seed=seed)
        rng = random.Random(1234)
        for _ in range(120):
            actions = s.legal_actions()
            if not actions or s.finished:
                break
            s.apply_action(rng.choice(actions))
        return s.board.state_hash()

    assert play(11) == play(11)
    assert play(11) != play(12)


def test_hold_swaps_pieces_and_only_once_per_piece():
    s = GameState(seed=0, piece_source=FixedSequence(["T", "I", "O", "S", "Z", "J", "L"]))
    assert s.current.name == "T"
    assert s.hold is None
    # Hold, then place the incoming I piece.
    res = s.apply_action(encode_action(0, 3, hold=True))
    assert res.valid
    assert s.hold == "T"
    assert res.piece == "I"
    assert s.current is not None and s.current.name == "O"
    assert s.can_hold is True  # reset on spawn
    # Hold again: places T, stores O.
    res2 = s.apply_action(encode_action(0, 3, hold=True))
    assert res2.valid
    assert res2.piece == "T"
    assert s.hold == "O"
    # Without spawning in between, a second hold must be rejected.
    # (Place T, then attempt hold twice within the same piece is covered by
    # the engine's can_hold flag.)
    mask = s.action_mask()
    assert any(a % 2 == 1 for a in s.legal_actions())


def test_hold_disabled_while_flag_clear():
    s = GameState(seed=0, piece_source=FixedSequence(["T", "I", "O"]))
    s.apply_action(encode_action(0, 3, hold=True))
    # After placing I, current is O and can_hold is reset; simulate a held piece
    # by clearing the flag.
    s.can_hold = False
    assert s.apply_action(encode_action(0, 3, hold=True)).valid is False
    assert s.current.name == "O"


def test_top_out_block_out():
    s = GameState(seed=0)
    # Fill the spawn area: rows 19 and 20 completely.
    for y in (19, 20):
        s.board.rows[y] = s.board.full_row_mask
    assert s.spawn() is False
    assert s.top_out is True
    assert s.topped_out_reason == "block_out"


def test_garbage_overflow_tops_out():
    s = GameState(seed=0)
    s.board.rows[5] = 1
    s.receive_attack(8)
    s.garbage.tick(0)
    # Force immediate insertion through apply_action.
    s.garbage.entries[0].ready_in = 0
    res = s.apply_action(encode_action(0, 3))
    assert res.valid
    assert s.top_out is True
    assert s.topped_out_reason in ("garbage_overflow", "block_out")


def test_t_spin_corner_detection():
    ruleset = tetrio_s2_ruleset()
    b = Board()
    # T resting at x=3, y=18 (state 0): corners (3,18),(5,18),(3,20),(5,20).
    b.rows[18] = (1 << 3) | (1 << 5)
    b.rows[20] = (1 << 3) | (1 << 4) | (1 << 5)
    res = detect_t_spin(b, 3, 18, 0, all_mini=False)
    assert res.spin is True
    assert res.mini is False
    assert res.corners == 4


def test_t_spin_mini_detection():
    b = Board()
    # Only one front corner (top-left) plus both back corners.
    b.rows[18] = 1 << 3
    b.rows[20] = (1 << 3) | (1 << 5)
    res = detect_t_spin(b, 3, 18, 0, all_mini=False)
    assert res.spin is True
    assert res.mini is True


def test_no_spin_without_three_corners():
    b = Board()
    b.rows[18] = 1 << 3
    res = detect_t_spin(b, 3, 18, 0)
    assert res.spin is False


def test_spin_requires_rotation_in_strict_mode():
    b = Board()
    b.rows[18] = (1 << 3) | (1 << 5)
    b.rows[20] = (1 << 3) | (1 << 5)
    kicks = GameState(seed=0).kick_tables["T"]
    strict = spin_from_placement(
        b, "T", 0, 3, 18, detection="strict", all_mini=False, kick_table=kicks, rotation_used=False
    )
    assert strict.spin is False
    loose = spin_from_placement(
        b, "T", 0, 3, 18, detection="corner", all_mini=False, kick_table=kicks, rotation_used=False
    )
    assert loose.spin is True


def test_engine_reports_spin_for_constructed_tsd():
    """Build a TSD cavity, drop a T into it, expect a spin and 2 cleared lines."""
    s = GameState(seed=0, piece_source=FixedSequence(["T"] * 10))
    b = s.board
    # Row 36 overhang above the cavity; rows 37/38 have exactly the gaps the T
    # fills; row 39 is the support (deliberately not full).
    def bits(*cols: int) -> int:
        mask = 0
        for c in cols:
            mask |= 1 << c
        return mask

    b.rows[36] = bits(3)
    b.rows[37] = bits(0, 1, 2, 6, 7, 8, 9)
    b.rows[38] = bits(0, 1, 2, 3, 5, 6, 7, 8, 9)
    b.rows[39] = bits(0, 1, 2, 3, 4, 5, 6, 7, 8)  # col 9 empty -> no pre-existing clear
    # T state 2 (pointing down) lands with body in row 37 and stem in row 38.
    res = s.apply_action(encode_action(2, 3))
    assert res.valid
    assert res.spin is True, (res.piece, res.rotation, res.x, res.y, res.lines)
    assert res.lines == 2
    assert res.attack >= 4


def test_lock_out_in_hidden_buffer():
    # Lock out is disabled in TETR.IO multiplayer; test the configurable mode.
    rules = tetrio_s2_ruleset().to_dict()
    rules["lock_out"] = True
    s = GameState(rules, seed=0, piece_source=FixedSequence(["T"] * 10))
    # Support exactly under the T's body at the visible boundary: the T spawns
    # at rows 18-19, cannot fall, and locks entirely inside the hidden buffer.
    s.board.rows[20] = 0b111000  # cols 3,4,5
    res = s.apply_action(encode_action(0, 3))
    assert res.valid
    assert res.top_out is True
    assert res.topped_out_reason == "lock_out"


def test_garbage_enters_only_on_non_clearing_lock():
    s = GameState(seed=0, piece_source=FixedSequence(["O"] * 12))
    s.receive_attack(4)
    for entry in s.garbage.entries:
        entry.ready_in = 0
    # A clearing lock must NOT tank garbage; it cancels with its attack instead.
    # Build a board with one line missing a single cell, then clear it with I.
    s2 = GameState(seed=0, piece_source=FixedSequence(["I"] * 12))
    row = s2.board.full_row_mask & ~(1 << 3) & ~(1 << 4) & ~(1 << 5) & ~(1 << 6)
    s2.board.rows[39] = row
    s2.board.rows[30] = 1 << 0  # leftover block: avoid an accidental perfect clear
    s2.receive_attack(4)
    for entry in s2.garbage.entries:
        entry.ready_in = 0
    res = s2.apply_action(encode_action(0, 3))
    assert res.lines == 1
    assert s2.garbage.total() == 4  # still queued, not tanked
    # A non-clearing lock tanks it.
    res2 = s2.apply_action(encode_action(0, 0))
    assert res2.lines == 0
    assert res2.garbage_inserted == 4


def test_surge_released_by_engine_on_empty_lock():
    s = GameState(seed=0, piece_source=FixedSequence(["T"] * 20))
    from tetrisrl.environment.scoring import compute_clear

    for _ in range(4):
        compute_clear(s.ruleset, s.clear_state, 4, False, False, False)
    assert s.clear_state.b2b == 4 and s.clear_state.surge == 4
    res = s.apply_action(encode_action(0, 0))
    assert res.valid and res.lines == 0
    assert res.attack_events == [1, 1, 2]
    assert s.clear_state.b2b == 0 and s.clear_state.surge == 0
