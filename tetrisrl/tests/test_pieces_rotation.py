"""Piece geometry, SRS/SRS+ kick tables, and rotation behaviour."""

from __future__ import annotations

import pytest

from tetrisrl.environment.pieces import CELLS, LEFT_OFFSET, PIECE_NAMES, ActivePiece
from tetrisrl.environment.rotation import (
    SRS_I,
    SRS_JLSTZ,
    KICK_TABLE_PRESETS,
    build_kick_tables,
    kick_tests,
)
from tetrisrl.environment.board import Board
from tetrisrl.environment.placement import resolve_placement, spawn_x


def test_all_pieces_have_four_states():
    for name in PIECE_NAMES:
        assert len(CELLS[name]) == 4
        for state in range(4):
            assert len(CELLS[name][state]) == 4, (name, state)


def test_rotation_states_are_consistent():
    # T spawn points up; clockwise points right; 180 points down.
    t0 = set(CELLS["T"][0])
    t1 = set(CELLS["T"][1])
    t2 = set(CELLS["T"][2])
    assert t0 == {(0, 1), (1, 1), (2, 1), (1, 0)}
    assert t1 == {(1, 0), (1, 1), (1, 2), (2, 1)}
    assert t2 == {(0, 1), (1, 1), (2, 1), (1, 2)}


def test_i_piece_spawn_geometry():
    assert set(CELLS["I"][0]) == {(0, 1), (1, 1), (2, 1), (3, 1)}
    assert set(CELLS["I"][1]) == {(2, 0), (2, 1), (2, 2), (2, 3)}
    assert set(CELLS["I"][2]) == {(0, 2), (1, 2), (2, 2), (3, 2)}


def test_left_offsets_match_cells():
    for name in PIECE_NAMES:
        for state in range(4):
            assert LEFT_OFFSET[name][state] == min(x for x, _ in CELLS[name][state])


def test_srs_tables_have_five_tests_except_o():
    for key, tests in SRS_JLSTZ.items():
        assert len(tests) == 5, (key, tests)
    for key, tests in SRS_I.items():
        assert len(tests) == 5, (key, tests)
    tables = build_kick_tables("srs")
    for name in ("J", "L", "S", "T", "Z"):
        assert len(tables[name][(0, 1)]) == 5
        assert tables[name][(0, 1)][0] == (0, 0)
    assert len(tables["I"][(0, 1)]) == 5
    assert tables["O"][(0, 1)] == ((0, 0),)


def test_srs_plus_has_180_and_preset_validation():
    tables = build_kick_tables("srs_plus")
    for name in PIECE_NAMES:
        assert (0, 2) in tables[name]
        assert (2, 0) in tables[name]
        assert len(tables[name][(0, 2)]) >= 1
    # JLSTZ 180 tables start with the basic rotation; the I 180 table uses the
    # frame-corrected cobra-movegen ordering (docs/RULESET.md §3.4).
    assert tables["T"][(0, 2)][0] == (0, 0)
    assert tables["I"][(0, 2)][0] == (0, -1)
    # SRS+ reorders the I test list relative to plain SRS.
    assert build_kick_tables("srs")["I"][(0, 1)] != tables["I"][(0, 1)]
    plain = build_kick_tables("srs")
    for name in PIECE_NAMES:
        assert plain[name][(0, 2)] == ((0, 0),)
    with pytest.raises(ValueError):
        build_kick_tables("not_a_preset")
    assert "srs_plus" in KICK_TABLE_PRESETS


def test_kick_tests_direction():
    table = build_kick_tables("srs")["T"]
    assert kick_tests(table, 0, 1) == SRS_JLSTZ[(0, 1)]
    assert kick_tests(table, 1, -1) == SRS_JLSTZ[(1, 0)]


def test_spawn_positions_and_resolution():
    board = Board()
    for name in PIECE_NAMES:
        x = spawn_x(name)
        cells = [(x + cx, 18 + cy) for cx, cy in CELLS[name][0]]
        assert board.fits(cells), name
    # I spawns over columns 3-6, O over 4-5.
    assert min(x for x, _ in [(spawn_x("I") + cx, 0) for cx, _ in CELLS["I"][0]]) == 3
    assert spawn_x("O") == 4


def test_hard_drop_lands_on_floor():
    board = Board()
    kicks = build_kick_tables("srs_plus")
    res = resolve_placement(board, kicks["T"], "T", 0, 3, 18, 10)
    assert res is not None
    x, y, cells = res
    assert max(y for _, y in cells) == 39
    assert all(0 <= cx < 10 for cx, _ in cells)


def test_wall_kick_when_rotating_against_wall():
    # I piece rotated vertically next to the right wall must be able to shift.
    board = Board()
    kicks = build_kick_tables("srs")["I"]
    res = resolve_placement(board, kicks, "I", 1, 9, 18, 10)
    assert res is not None
    x, y, cells = res
    assert all(0 <= cx < 10 for cx, _ in cells)
    assert min(cx for cx, _ in cells) == 9


def test_placement_blocks_collision():
    board = Board()
    # Fill the floor completely; any placement's cells remain above the floor,
    # so the piece should rest on top instead of colliding.
    board.rows[39] = board.full_row_mask
    kicks = build_kick_tables("srs_plus")["O"]
    res = resolve_placement(board, kicks, "O", 0, 0, 18, 10)
    assert res is not None
    cells = res[2]
    assert max(y for _, y in cells) == 38


def test_active_piece_cells_and_move():
    p = ActivePiece("O", 0, 4, 19)
    assert p.cells() == ((4, 19), (5, 19), (4, 20), (5, 20))
    moved = p.moved(dx=1, dy=-1)
    assert moved.cells() == ((5, 18), (6, 18), (5, 19), (6, 19))
