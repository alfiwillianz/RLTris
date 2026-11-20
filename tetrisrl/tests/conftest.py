"""Shared pytest fixtures and helpers."""

from __future__ import annotations

from typing import List, Sequence

import pytest

from tetrisrl.environment.board import Board


def make_board(rows: Sequence[str], height: int = 40) -> Board:
    """Build a 10-wide board from bottom-aligned strings ('#' = filled).

    Rows are given top-to-bottom and placed against the floor.
    """
    b = Board(width=10, height=height, visible_height=20)
    offset = height - len(rows)
    for i, row in enumerate(rows):
        mask = 0
        for x, ch in enumerate(row):
            if ch == "#":
                mask |= 1 << x
        b.rows[offset + i] = mask
    return b


def board_rows(board: Board) -> List[str]:
    return board.to_strings()


@pytest.fixture
def empty_board() -> Board:
    return Board()


@pytest.fixture
def ruleset():
    from tetrisrl.environment.ruleset import tetrio_s2_ruleset

    return tetrio_s2_ruleset()
