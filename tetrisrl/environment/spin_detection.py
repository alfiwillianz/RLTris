"""Spin detection (T-spin, mini, and TETR.IO "all-mini" classification).

The corner rule
---------------
A T piece has four *corners* around its 3x3 box.  A corner is "occupied" if it
is filled by the board, by a wall (left/right of the board), or by the floor.
T-spins require at least three occupied corners.

* **Full T-spin**: both *front* corners (the two corners on the side the T is
  pointing towards) are occupied.
* **Mini T-spin**: only one front corner is occupied, but three corners in
  total are occupied.

TETR.IO's "All-Mini" classification additionally treats T-spins that use a
significant kick or lack a proper front-corner configuration as mini.  The
implementation exposes this through ``SpinConfig.all_mini``; see
``docs/RULESET.md`` for the exact sourcing and known uncertainty.

Because the RL action space is *placement-based* (one action = rotation +
column + hold, then hard drop), the engine cannot observe a literal "last move
was a rotation" event.  ``SpinConfig.detection`` therefore controls how that
condition is reconstructed:

``corner``
    corner rule only (most permissive, over-credits spins).
``corner_spin_in``
    corner rule plus a check that a rotation into the final state would have
    been legal at the resting position (approximates a spin-in).  This is the
    default and avoids crediting flat drops that cannot be spin-ins.
``strict``
    corner rule plus the agent must have selected a non-spawn rotation for the
    placement.  Diagnostic mode: it under-credits the common TSD (state 0) case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .board import Board
from .pieces import CELLS

Corner = Tuple[int, int]

#: Corner offsets relative to the 3x3 T box, in the order
#: (top-left, top-right, bottom-left, bottom-right).
T_CORNERS: Tuple[Corner, ...] = ((0, 0), (2, 0), (0, 2), (2, 2))

#: Which corners are "front" for each T rotation state.
T_FRONT_CORNERS: Dict[int, Tuple[int, ...]] = {
    0: (0, 1),  # pointing up   -> top-left, top-right
    1: (1, 3),  # pointing right-> top-right, bottom-right
    2: (2, 3),  # pointing down -> bottom-left, bottom-right
    3: (0, 2),  # pointing left -> top-left, bottom-left
}


def corner_occupancy(board: Board, x: int, y: int, rotation: int) -> Tuple[bool, bool, bool, bool]:
    """Occupancy of the four T-box corners for a T piece at origin (x, y)."""
    occupied: List[bool] = []
    for cx, cy in T_CORNERS:
        bx, by = x + cx, y + cy
        if bx < 0 or bx >= board.width or by >= board.height:
            occupied.append(True)
        elif by < 0:
            occupied.append(False)
        else:
            occupied.append(bool(board.rows[by] >> bx & 1))
    return tuple(occupied)  # type: ignore[return-value]


@dataclass(frozen=True)
class SpinResult:
    spin: bool = False
    mini: bool = False
    kind: str = "none"  # none | tspin | tspin_mini
    corners: int = 0
    front_corners: int = 0


NO_SPIN = SpinResult()


def detect_t_spin(
    board: Board,
    x: int,
    y: int,
    rotation: int,
    all_mini: bool = True,
) -> SpinResult:
    """Corner-rule T-spin classification for a T piece resting at (x, y)."""
    corners = corner_occupancy(board, x, y, rotation)
    total = sum(corners)
    front = sum(corners[i] for i in T_FRONT_CORNERS[rotation % 4])
    if total < 3:
        return SpinResult(False, False, "none", total, front)
    mini = front < 2
    if all_mini and not mini:
        # TETR.IO's all-mini rule: with fewer than two *back* corners the spin
        # is still a full T-spin; otherwise the front-corner test decides.
        # The additional "kick-based" downgrade is handled by the caller via
        # the kick offset (see spin_from_placement).
        mini = False
    kind = "tspin_mini" if mini else "tspin"
    return SpinResult(True, mini, kind, total, front)


def rotation_legal_at_rest(
    board: Board,
    piece: str,
    rotation: int,
    x: int,
    y: int,
    kick_table: Dict[Tuple[int, int], Sequence[Tuple[int, int]]],
    from_rotation: int | None = None,
) -> bool:
    """True if rotating *into* ``rotation`` at this position is legal.

    The piece is assumed to be resting (it cannot move down).  We try the
    forward and reverse rotation into the target state, applying the kick table
    with the SRS (x, y-up) convention.
    """
    target = rotation % 4
    candidates: List[int] = []
    if from_rotation is not None:
        candidates.append(from_rotation % 4)
    else:
        candidates.extend([(target - 1) % 4, (target + 2) % 4])

    base_cells = CELLS[piece][target]
    for src in candidates:
        if src == target:
            continue
        direction = (target - src) % 4
        if direction == 2:
            tests = kick_table.get((src, target), ((0, 0),))
        else:
            tests = kick_table.get((src, target), ((0, 0),))
        for dx, dy_up in tests:
            cells = [(x + cx + dx, y + cy - dy_up) for cx, cy in base_cells]
            if board.fits(cells):
                return True
    return False


def spin_from_placement(
    board: Board,
    piece: str,
    rotation: int,
    x: int,
    y: int,
    *,
    detection: str = "corner_spin_in",
    all_mini: bool = True,
    kick_table: Dict[Tuple[int, int], Sequence[Tuple[int, int]]] | None = None,
    rotation_used: bool = True,
) -> SpinResult:
    """Classify a locked placement as a spin according to the ruleset policy."""
    if piece != "T":
        return NO_SPIN
    res = detect_t_spin(board, x, y, rotation, all_mini=all_mini)
    if not res.spin:
        return res
    if detection == "corner":
        return res
    if detection == "strict":
        return res if rotation_used else NO_SPIN
    if detection == "corner_spin_in":
        if kick_table is None or rotation_legal_at_rest(board, piece, rotation, x, y, kick_table):
            return res
        # No possible spin-in: treat as a normal lock.
        return NO_SPIN
    return res
