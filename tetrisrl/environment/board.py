"""Bitboard-backed playfield.

Rows are stored as Python ints (bit ``x`` = column ``x``, bit 0 = left-most).
Row ``0`` is the top of the 40-row board; row ``height - 1`` is the floor.  The
top ``height - visible_height`` rows are hidden (TETR.IO spawn/garbage area).

The board is deliberately free of scoring/attack logic: it only knows about
occupancy, line clears, garbage rows and board-quality metrics.  This keeps the
simulation layer testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Tuple

Cell = Tuple[int, int]


@dataclass
class Board:
    width: int = 10
    height: int = 40
    visible_height: int = 20
    rows: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.rows:
            self.rows = [0] * self.height
        if len(self.rows) != self.height:
            raise ValueError(f"board must have {self.height} rows, got {len(self.rows)}")

    # -- basic geometry -----------------------------------------------------
    @property
    def full_row_mask(self) -> int:
        return (1 << self.width) - 1

    def copy(self) -> "Board":
        return Board(self.width, self.height, self.visible_height, list(self.rows))

    def reset(self) -> None:
        self.rows = [0] * self.height

    def occupied(self, x: int, y: int) -> bool:
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return True
        return bool(self.rows[y] >> x & 1)

    def fits(self, cells: Sequence[Cell]) -> bool:
        """True if every cell is inside the board and unoccupied."""
        for x, y in cells:
            if x < 0 or x >= self.width or y < 0 or y >= self.height:
                return False
            if self.rows[y] >> x & 1:
                return False
        return True

    def collides(self, cells: Sequence[Cell]) -> bool:
        return not self.fits(cells)

    # -- mutation -----------------------------------------------------------
    def lock(self, cells: Iterable[Cell]) -> None:
        for x, y in cells:
            self.rows[y] |= 1 << x

    def clear_lines(self) -> List[int]:
        """Remove full rows and return their original indices (top to bottom)."""
        cleared = [y for y, row in enumerate(self.rows) if row == self.full_row_mask]
        if not cleared:
            return []
        kept = [row for row in self.rows if row != self.full_row_mask]
        self.rows = [0] * (self.height - len(kept)) + kept
        return cleared

    def insert_garbage(self, count: int, hole_column: int) -> bool:
        """Push ``count`` garbage rows in from the bottom.

        Each inserted row has a single hole at ``hole_column``.  Returns
        ``True`` if a block was pushed out of the top (top-out condition).
        """
        if count <= 0:
            return False
        if count > self.height:
            count = self.height
        mask = self.full_row_mask & ~(1 << hole_column)
        garbage = [mask] * count
        # Garbage pushes the stack UP: the top ``count`` rows are discarded
        # (and cause a top-out if they contained blocks).
        discarded = self.rows[:count]
        remaining = self.rows[count:]
        overflowed = any(row != 0 for row in discarded)
        self.rows = remaining + garbage
        return overflowed

    def add_rows_from_bottom(self, count: int, hole_column: int) -> bool:
        return self.insert_garbage(count, hole_column)

    # -- metrics ------------------------------------------------------------
    def heights(self) -> List[int]:
        out: List[int] = []
        for x in range(self.width):
            bit = 1 << x
            h = 0
            for y in range(self.height):
                if self.rows[y] & bit:
                    h = self.height - y
                    break
            out.append(h)
        return out

    def visible_heights(self) -> List[int]:
        """Column heights clipped to the visible field (0 = empty column)."""
        out: List[int] = []
        floor = self.height
        top = self.height - self.visible_height
        for x in range(self.width):
            bit = 1 << x
            h = 0
            for y in range(top, floor):
                if self.rows[y] & bit:
                    h = floor - y
                    break
            out.append(h)
        return out

    def holes(self) -> int:
        holes = 0
        for x in range(self.width):
            bit = 1 << x
            seen_block = False
            for y in range(self.height):
                if self.rows[y] & bit:
                    seen_block = True
                elif seen_block:
                    holes += 1
        return holes

    def bumpiness(self) -> int:
        h = self.heights()
        return sum(abs(a - b) for a, b in zip(h, h[1:]))

    def aggregate_height(self) -> int:
        return sum(self.heights())

    def max_height(self) -> int:
        return max(self.heights()) if self.width else 0

    def is_empty(self) -> bool:
        return not any(self.rows)

    def filled_cells(self) -> int:
        return sum(bin(row).count("1") for row in self.rows)

    # -- serialisation ------------------------------------------------------
    def to_rows(self) -> List[int]:
        return list(self.rows)

    def to_strings(self) -> List[str]:
        """Debug/rendering form, top row first, ``#`` = filled."""
        out = []
        for row in self.rows:
            out.append("".join("#" if row >> x & 1 else "." for x in range(self.width)))
        return out

    def visible_strings(self) -> List[str]:
        return self.to_strings()[self.height - self.visible_height :]

    def state_hash(self) -> int:
        h = 1469598103934665603
        for row in self.rows:
            h ^= row
            h *= 1099511628211
        return h & ((1 << 64) - 1)

    def piece_cells(self, name: str, rotation: int, x: int, y: int, cells: Sequence[Cell]) -> List[Cell]:
        return [(x + cx, y + cy) for cx, cy in cells]
