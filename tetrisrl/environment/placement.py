"""Pure placement resolution shared by the engine, baselines and search agents.

A placement is (piece, rotation, left-most occupied column).  Resolution finds
the spawn-space position (applying the rotation kicks), translates the piece so
its left-most occupied cell lands on the requested column, and hard-drops it.

**Spin-in resolution**: TETR.IO's SRS+ allows pieces (especially T) to reach
cavities that cannot be entered from above by rotating at rest.  For a target
placement whose final orientation cannot be dropped in vertically, the engine
also drops an adjacent orientation at the *same box origin* and rotates into the
target orientation at rest using the official kick tests.  The deepest legal
result wins (a player would prefer the spin if it reaches further).  Every
result corresponds to a legal SRS rotation sequence, so pieces never pass
through walls.  Spin classification is done separately by
:mod:`tetrisrl.environment.spin_detection`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .board import Board
from .pieces import CELLS, LEFT_OFFSET
from .rotation import kick_tests

SPAWN_LEFT = {"I": 3, "O": 4}
SPIN_SOURCES = {1: (2, 0), 2: (1, 3), 3: (0, 2)}
#: Pieces for which spin-in (rotation-at-rest) resolution is attempted.  T is
#: the piece whose competitive utility depends on kicks; I-spins are enabled by
#: adding ``"I"``.  Restricting this keeps the action-mask computation cheap.
SPIN_IN_PIECES = ("T",)


def spawn_x(name: str) -> int:
    return SPAWN_LEFT.get(name, 3) - LEFT_OFFSET[name][0]


def rotation_direction(rotation: int) -> int:
    return {0: 0, 1: 1, 2: 2, 3: -1}[rotation % 4]


def _drop_box(
    board: Board,
    kick_table: Dict[Tuple[int, int], Sequence[Tuple[int, int]]],
    piece: str,
    rotation: int,
    x: int,
    spawn_y: int,
) -> Optional[Tuple[int, int, Tuple[Tuple[int, int], ...]]]:
    """Hard-drop ``piece`` in ``rotation`` with box origin ``x``."""
    base_cells = CELLS[piece][rotation]
    # Spawn-space rotation is performed in the open buffer, so the basic
    # (0, 0) test always applies except when the stack reaches the spawn rows
    # (in which case the position is not a legal placement anyway).  Applying
    # spawn kicks here would silently move the piece off the requested column.
    kicks = ((0, 0),)
    for dx, dy_up in kicks:
        x0 = x + dx
        y0 = spawn_y - dy_up
        cells = [(x0 + cx, y0 + cy) for cx, cy in base_cells]
        if not board.fits(cells):
            continue
        y = y0
        while True:
            moved = [(x0 + cx, y + 1 + cy) for cx, cy in base_cells]
            if board.fits(moved):
                y += 1
            else:
                break
        final_cells = tuple((x0 + cx, y + cy) for cx, cy in base_cells)
        return x0, y, final_cells
    return None


def _resting(board: Board, cells: Sequence[Tuple[int, int]]) -> bool:
    return not board.fits([(x, y + 1) for x, y in cells])


def resolve_placement(
    board: Board,
    kick_table: Dict[Tuple[int, int], Sequence[Tuple[int, int]]],
    piece: str,
    rotation: int,
    column: int,
    spawn_y: int,
    width: int,
) -> Optional[Tuple[int, int, Tuple[Tuple[int, int], ...]]]:
    """Return ``(x, y, cells)`` for a hard-dropped placement, or ``None``."""
    if not (0 <= rotation <= 3) or not (0 <= column < width):
        return None

    origin_x = column - LEFT_OFFSET[piece][rotation]
    best = _drop_box(board, kick_table, piece, rotation, origin_x, spawn_y)
    if rotation == 0 or piece not in SPIN_IN_PIECES:
        return best

    target_cells = CELLS[piece][rotation]
    for source in SPIN_SOURCES[rotation]:
        if source == rotation:
            continue
        src = _drop_box(board, kick_table, piece, source, origin_x, spawn_y)
        if src is None:
            continue
        x_src, y_src, src_cells = src
        for dx, dy_up in kick_tests(kick_table, source, rotation_direction((rotation - source) % 4)):
            x_new = x_src + dx
            y_new = y_src - dy_up
            cells = tuple((x_new + cx, y_new + cy) for cx, cy in target_cells)
            if not board.fits(cells):
                continue
            if min(cx for cx, _ in cells) != column:
                continue
            if not _resting(board, cells):
                continue
            if set(cells) == set(src_cells):
                continue
            if best is None or max(y for _, y in cells) > max(y for _, y in best[2]):
                best = (x_new, y_new, cells)
    return best


def placements_for(
    board: Board,
    kick_table: Dict[Tuple[int, int], Sequence[Tuple[int, int]]],
    piece: str,
    spawn_y: int,
    width: int,
) -> List[Tuple[int, int, int, Tuple[Tuple[int, int], ...]]]:
    """All legal ``(rotation, column, x, cells)`` placements for ``piece``."""
    out: List[Tuple[int, int, int, Tuple[Tuple[int, int], ...]]] = []
    seen: set[Tuple[Tuple[int, int], ...]] = set()
    for rotation in range(4):
        for column in range(width):
            res = resolve_placement(board, kick_table, piece, rotation, column, spawn_y, width)
            if res is None:
                continue
            x, y, cells = res
            if cells in seen:
                continue
            seen.add(cells)
            out.append((rotation, column, x, cells))
    return out
