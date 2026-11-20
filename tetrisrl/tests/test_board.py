"""Board representation, collision, clearing, garbage, and metrics."""

from __future__ import annotations

import pytest

from tetrisrl.environment.board import Board
from tetrisrl.tests.conftest import make_board


def test_board_dimensions():
    b = Board()
    assert b.width == 10
    assert b.height == 40
    assert b.visible_height == 20
    assert len(b.rows) == 40


def test_fits_and_collision():
    b = Board()
    assert b.fits([(0, 39), (0, 38)])
    assert not b.fits([(0, 40)])  # below floor
    assert not b.fits([(-1, 39)])  # left of wall
    assert not b.fits([(10, 39)])  # right of wall
    b.rows[39] |= 1 << 3
    assert not b.fits([(3, 39)])
    assert b.fits([(3, 38)])


def test_lock_and_clear_single_line():
    b = Board()
    for x in range(9):
        b.rows[39] |= 1 << x
    b.lock([(9, 39)])
    cleared = b.clear_lines()
    assert cleared == [39]
    assert b.is_empty()


def test_clear_multiple_rows_preserves_order():
    b = make_board(
        [
            "..........",
            "##########",
            "....#.....",
            "##########",
        ]
    )
    cleared = b.clear_lines()
    assert cleared == [37, 39]
    visible = b.visible_strings()
    assert visible[-1] == "....#....."
    assert visible[-2] == ".........."


def test_heights_holes_bumpiness():
    b = make_board(
        [
            "#.........",
            "#.#.......",
            "#...#.....",
        ]
    )
    heights = b.visible_heights()
    assert heights[0] == 3
    assert heights[2] == 2
    assert heights[4] == 1
    assert b.holes() == 1
    assert b.bumpiness() == sum(abs(a - c) for a, c in zip(heights, heights[1:]))


def test_garbage_insertion_shifts_board():
    b = Board()
    b.rows[39] |= 0b1
    overflow = b.insert_garbage(2, hole_column=4)
    assert overflow is False
    assert b.rows[39] == b.full_row_mask & ~(1 << 4)
    assert b.rows[38] == b.full_row_mask & ~(1 << 4)
    # Old floor row moved up.
    assert b.rows[37] & 0b1


def test_garbage_overflow_top_out():
    b = Board()
    b.rows[0] |= 0b1  # block in the very top row
    assert b.insert_garbage(1, hole_column=0) is True


def test_copy_is_deep():
    b = Board()
    b.rows[39] = 0b111
    c = b.copy()
    c.rows[39] = 0
    assert b.rows[39] == 0b111


def test_state_hash_changes():
    b = Board()
    h1 = b.state_hash()
    b.rows[30] = 1
    assert b.state_hash() != h1


def test_full_row_mask():
    b = Board()
    assert b.full_row_mask == 0b1111111111
    b.rows[20] = b.full_row_mask
    assert b.clear_lines() == [20]
    assert b.is_empty()
