"""Placement-based action encoding.

The agent chooses a *placement*, not a key sequence::

    action = rotation * 20 + column * 2 + hold

* ``rotation`` in ``0..3`` (0 spawn, 1 clockwise, 2 180, 3 counter-clockwise)
* ``column`` in ``0..9`` -- the **left-most occupied column** of the piece, so
  every reachable column is expressible for every rotation
* ``hold`` in ``0..1`` -- 0: place the current piece; 1: swap with hold first

Total action space: 4 x 10 x 2 = **80**.  The engine resolves a valid action to
a concrete piece, final rotation, box origin, and lock position, then hard
drops.  ``action_mask()`` enumerates exactly the placements that are physically
legal in the current state, which is what both RL algorithms use for masking.

Duplicate ids (O-piece rotations, I-piece 0/2 and 1/3) are all kept valid and
map to identical outcomes; this keeps the action space fixed-size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

from .pieces import CELLS, LEFT_OFFSET, PIECE_NAMES

if TYPE_CHECKING:  # pragma: no cover
    from .engine import GameState

ACTION_SPACE: int = 4 * 10 * 2
HOLD_ACTIONS: int = 40


def encode_action(rotation: int, column: int, hold: bool = False) -> int:
    if not (0 <= rotation < 4):
        raise ValueError(f"rotation out of range: {rotation}")
    if not (0 <= column < 10):
        raise ValueError(f"column out of range: {column}")
    return rotation * 20 + column * 2 + (1 if hold else 0)


def decode_action(action: int) -> Tuple[int, int, bool]:
    if not (0 <= action < ACTION_SPACE):
        raise ValueError(f"action out of range: {action}")
    rotation, rest = divmod(action, 20)
    column, hold = divmod(rest, 2)
    return rotation, column, bool(hold)


@dataclass(frozen=True)
class Placement:
    action: int
    piece: str
    rotation: int
    column: int
    x: int
    y: int
    cells: Tuple[Tuple[int, int], ...]
    hold: bool = False


def describe_action(action: int) -> str:
    rotation, column, hold = decode_action(action)
    rot_names = {0: "0", 1: "R", 2: "2", 3: "L"}
    return f"rot={rot_names[rotation]} col={column} hold={int(hold)}"
