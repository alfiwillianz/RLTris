"""Observation encoding.

Two representations are produced from a :class:`GameState`:

1. :class:`StructuredObservation` -- named, human-readable fields (used by the
   heuristic/search agents, the dashboard, and debugging).
2. A flat ``float32`` tensor vector built by :class:`ObservationEncoder` (used
   by PPO / Double DQN).  The layout is documented and versioned so checkpoints
   remain loadable.

Information rules
-----------------
Only information a real player has is exposed:

* own board (including hidden rows the player can see in the buffer),
* current piece, hold, and the configured preview,
* the opponent's *visible* board and pending garbage,
* recent incoming/outgoing attack history,
* competitive state (combo, b2b, charge, surge).

The randomizer's future beyond the configured preview is **never** read.  The
opponent and ensemble toggles exist so the observation ablation experiment can
train/evaluate with and without opponent channels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .engine import GameState
from .pieces import PIECE_INDEX, PIECE_NAMES

OBS_VERSION = 1

#: Canonical feature vector layout.  ``N`` = number of preview pieces.
#: Kept as a module constant so tests can assert the exact size.
SCALARS = (
    "combo",
    "b2b_active",
    "b2b_charge",
    "surge_pending",
    "pending_garbage",
    "incoming_1s",
    "outgoing_1s",
    "lines_total",
    "attack_total",
    "pieces",
    "max_height",
    "aggregate_height",
    "holes",
    "bumpiness",
    "time_fraction",
)


@dataclass
class BoardConfig:
    include_opponent: bool = True
    include_pending: bool = True
    preview: int = 5
    height: int = 40
    width: int = 10


@dataclass
class StructuredObservation:
    board: List[List[int]]  # full board rows, top to bottom
    heights: List[int]
    holes: int
    bumpiness: int
    aggregate_height: int
    current_piece: str
    current_rotation: int
    hold_piece: Optional[str]
    hold_available: bool
    next_pieces: List[str]
    opponent_board: Optional[List[int]] = None
    opponent_heights: Optional[List[int]] = None
    opponent_pending: int = 0
    pending_garbage: int = 0
    combo: int = 0
    b2b_active: bool = False
    b2b_charge: float = 0.0
    surge_pending: bool = False
    incoming_history: List[int] = field(default_factory=list)
    outgoing_history: List[int] = field(default_factory=list)
    lines_total: int = 0
    attack_total: int = 0
    pieces: int = 0
    max_pieces: int = 1000

    def as_dict(self) -> dict:
        return {
            "board": self.board,
            "heights": self.heights,
            "holes": self.holes,
            "bumpiness": self.bumpiness,
            "aggregate_height": self.aggregate_height,
            "current_piece": self.current_piece,
            "current_rotation": self.current_rotation,
            "hold_piece": self.hold_piece,
            "hold_available": self.hold_available,
            "next_pieces": self.next_pieces,
            "opponent_board": self.opponent_board,
            "opponent_heights": self.opponent_heights,
            "opponent_pending": self.opponent_pending,
            "pending_garbage": self.pending_garbage,
            "combo": self.combo,
            "b2b_active": self.b2b_active,
            "b2b_charge": self.b2b_charge,
            "surge_pending": self.surge_pending,
            "incoming_history": self.incoming_history,
            "outgoing_history": self.outgoing_history,
            "lines_total": self.lines_total,
            "attack_total": self.attack_total,
            "pieces": self.pieces,
        }


def structured_observation(
    state: GameState,
    opponent: Optional[GameState] = None,
    include_opponent: bool = True,
    preview: int = 5,
    max_pieces: int = 1000,
) -> StructuredObservation:
    board = state.board
    return StructuredObservation(
        board=list(board.rows),
        heights=board.visible_heights(),
        holes=board.holes(),
        bumpiness=board.bumpiness(),
        aggregate_height=board.aggregate_height(),
        current_piece=state.current.name if state.current else "",
        current_rotation=state.current.rotation if state.current else 0,
        hold_piece=state.hold,
        hold_available=state.can_hold,
        next_pieces=state.preview(preview),
        opponent_board=list(opponent.board.rows) if (include_opponent and opponent) else None,
        opponent_heights=opponent.board.visible_heights() if (include_opponent and opponent) else None,
        opponent_pending=opponent.pending_garbage if (include_opponent and opponent) else 0,
        pending_garbage=state.pending_garbage,
        combo=state.combo,
        b2b_active=state.b2b_active,
        b2b_charge=state.b2b_charge,
        surge_pending=state.surge_pending,
        incoming_history=list(state.incoming_history[-16:]),
        outgoing_history=list(state.outgoing_history[-16:]),
        lines_total=state.clear_state.total_lines,
        attack_total=state.clear_state.total_attack,
        pieces=state.pieces_placed,
        max_pieces=max_pieces,
    )


def _one_hot(index: Optional[int], size: int) -> List[float]:
    vec = [0.0] * size
    if index is not None and 0 <= index < size:
        vec[index] = 1.0
    return vec


class ObservationEncoder:
    """Deterministic, configurable flat-vector encoder."""

    def __init__(
        self,
        include_opponent: bool = True,
        include_pending: bool = True,
        preview: int = 5,
        height: int = 40,
        width: int = 10,
        max_pieces: int = 1000,
    ) -> None:
        self.include_opponent = include_opponent
        self.include_pending = include_pending
        self.preview = preview
        self.height = height
        self.width = width
        self.max_pieces = max_pieces

    # -- layout ------------------------------------------------------------
    @property
    def own_board_size(self) -> int:
        return self.height * self.width

    @property
    def opponent_board_size(self) -> int:
        return self.height * self.width if self.include_opponent else 0

    @property
    def size(self) -> int:
        size = self.own_board_size + self.opponent_board_size
        size += self.width  # own heights
        if self.include_opponent:
            size += self.width  # opponent heights
        size += 8  # hold (7 pieces + empty)
        size += self.preview * 7  # preview pieces
        size += 7 + 4  # current piece one-hot, rotation one-hot
        size += len(SCALARS)
        return size

    def layout(self) -> Dict[str, Tuple[int, int]]:
        """Return ``{name: (start, end)}`` slices of the flat vector."""
        out: Dict[str, Tuple[int, int]] = {}
        i = 0
        out["own_board"] = (i, i + self.own_board_size)
        i += self.own_board_size
        if self.include_opponent:
            out["opponent_board"] = (i, i + self.opponent_board_size)
            i += self.opponent_board_size
        out["own_heights"] = (i, i + self.width)
        i += self.width
        if self.include_opponent:
            out["opponent_heights"] = (i, i + self.width)
            i += self.width
        out["hold"] = (i, i + 8)
        i += 8
        out["preview"] = (i, i + self.preview * 7)
        i += self.preview * 7
        out["current_piece"] = (i, i + 7)
        i += 7
        out["current_rotation"] = (i, i + 4)
        i += 4
        out["scalars"] = (i, i + len(SCALARS))
        i += len(SCALARS)
        assert i == self.size, (i, self.size)
        return out

    # -- encoding ----------------------------------------------------------
    def encode(self, state: GameState, opponent: Optional[GameState] = None) -> np.ndarray:
        vec = np.zeros(self.size, dtype=np.float32)
        layout = self.layout()

        def put(name: str, values: Sequence[float]) -> None:
            start, end = layout[name]
            vec[start:end] = np.asarray(values, dtype=np.float32)[: end - start]

        # Own board: 1.0 = filled.  Full 40 rows so the agent can see its buffer.
        put("own_board", [1.0 if row >> x & 1 else 0.0 for row in state.board.rows for x in range(self.width)])

        if self.include_opponent:
            if opponent is not None:
                put("opponent_board", [1.0 if row >> x & 1 else 0.0 for row in opponent.board.rows for x in range(self.width)])
            else:
                put("opponent_board", [0.0] * self.opponent_board_size)

        put("own_heights", [h / self.height for h in state.board.visible_heights()])
        if self.include_opponent:
            heights = opponent.board.visible_heights() if opponent is not None else [0] * self.width
            put("opponent_heights", [h / self.height for h in heights])

        hold_idx = PIECE_INDEX.get(state.hold) if state.hold else None
        put("hold", _one_hot(hold_idx, 7) + [1.0 if state.can_hold else 0.0])

        next_pieces = state.preview(self.preview)
        preview_vec: List[float] = []
        for i in range(self.preview):
            name = next_pieces[i] if i < len(next_pieces) else None
            preview_vec.extend(_one_hot(PIECE_INDEX.get(name) if name else None, 7))
        put("preview", preview_vec)

        cur_idx = PIECE_INDEX.get(state.current.name) if state.current else None
        cur_rot = state.current.rotation if state.current else 0
        put("current_piece", _one_hot(cur_idx, 7))
        put("current_rotation", _one_hot(cur_rot, 4))

        max_height = state.board.max_height()
        scalars = {
            "combo": max(0.0, state.combo + 1) / 20.0,
            "b2b_active": 1.0 if state.b2b_active else 0.0,
            "b2b_charge": state.surge_value / 20.0,
            "surge_pending": 1.0 if state.surge_pending else 0.0,
            "pending_garbage": state.pending_garbage / 20.0,
            "incoming_1s": sum(state.incoming_history[-8:]) / 20.0,
            "outgoing_1s": sum(state.outgoing_history[-8:]) / 20.0,
            "lines_total": state.clear_state.total_lines / 100.0,
            "attack_total": state.clear_state.total_attack / 100.0,
            "pieces": state.pieces_placed / max(1, self.max_pieces),
            "max_height": max_height / self.height,
            "aggregate_height": state.board.aggregate_height() / (self.width * self.height),
            "holes": state.board.holes() / (self.width * self.height),
            "bumpiness": state.board.bumpiness() / (self.width * self.height),
            "time_fraction": state.pieces_placed / max(1, self.max_pieces),
        }
        put("scalars", [scalars[name] for name in SCALARS])
        return vec

    def batch_encode(self, states: Sequence[GameState], opponents: Optional[Sequence[GameState]] = None) -> np.ndarray:
        if opponents is None:
            opponents = [None] * len(states)  # type: ignore[list-item]
        return np.stack([self.encode(s, o) for s, o in zip(states, opponents)])


def observation_size(**kwargs) -> int:
    return ObservationEncoder(**kwargs).size
