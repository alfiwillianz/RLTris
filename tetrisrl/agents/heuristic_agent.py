"""Handcrafted heuristic baseline (Dellacherie-style board evaluation).

For every legal placement the agent simulates the lock and scores the resulting
board with classic Tetris features, plus competitive terms (attack value,
opponent pressure).  This is a *baseline*, not a search algorithm: it is
one-ply greedy over a handcrafted evaluation function.  The genuine
search-based baseline is :class:`tetrisrl.agents.search_agent.BeamSearchAgent`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .base import BaseAgent
from ..environment.board import Board
from ..environment.engine import GameState


@dataclass(frozen=True)
class HeuristicWeights:
    landing_height: float = -4.5
    eroded_cells: float = 3.4
    row_transitions: float = -3.2
    column_transitions: float = -9.3
    holes: float = -7.9
    wells: float = -3.4
    # Competitive terms.
    per_line: float = 1.5
    per_attack: float = 2.0
    spin_bonus: float = 2.0
    #: Reward attacking while the opponent is under pressure (pending garbage).
    opponent_pressure: float = 0.35
    #: Penalty for keeping a tall stack (visible rows above ``height_threshold``).
    height_threshold: int = 14
    high_stack_penalty: float = -0.6


def board_features(board: Board) -> Dict[str, float]:
    """Classic evaluation features of a (post-clear) board."""
    heights = board.heights()
    holes = 0
    col_transitions = 0
    for x in range(board.width):
        bit = 1 << x
        seen = False
        for y in range(board.height):
            filled = bool(board.rows[y] & bit)
            if filled:
                seen = True
            elif seen:
                holes += 1
            if y > 0:
                above = bool(board.rows[y - 1] & bit)
                if filled != above:
                    col_transitions += 1
        # Transition into the floor / virtual empty row below.
        if board.rows[board.height - 1] & bit:
            col_transitions += 1

    row_transitions = 0
    for y in range(board.height):
        row = board.rows[y]
        prev = 1  # left wall
        for x in range(board.width):
            cur = (row >> x) & 1
            if cur != prev:
                row_transitions += 1
            prev = cur
        if prev != 1:  # right wall
            row_transitions += 1

    wells = 0
    for x in range(board.width):
        left_h = heights[x - 1] if x > 0 else board.height
        right_h = heights[x + 1] if x < board.width - 1 else board.height
        depth = min(left_h, right_h) - heights[x]
        if depth > 0:
            wells += depth * (depth + 1) // 2

    return {
        "row_transitions": float(row_transitions),
        "column_transitions": float(col_transitions),
        "holes": float(holes),
        "wells": float(wells),
        "max_height": float(max(heights) if heights else 0),
        "aggregate_height": float(sum(heights)),
        "bumpiness": float(board.bumpiness()),
    }


def simulate(board: Board, cells, ruleset) -> Tuple[Board, int, int, bool]:
    """Lock ``cells`` on a copy of ``board``, clear lines.

    Returns ``(new_board, lines_cleared, eroded_cells, perfect_clear)``.
    """
    new = board.copy()
    new.lock(cells)
    cleared_rows = [y for y, row in enumerate(new.rows) if row == new.full_row_mask]
    cleared = len(cleared_rows)
    eroded = sum(1 for _x, y in cells if y in cleared_rows)
    new.clear_lines()
    perfect = cleared > 0 and new.is_empty()
    return new, cleared, eroded, perfect


class HeuristicAgent(BaseAgent):
    name = "heuristic"

    def __init__(
        self,
        weights: Optional[HeuristicWeights] = None,
        seed: int = 0,
        noise: float = 0.0,
        opponent_aware: bool = True,
    ) -> None:
        self.weights = weights or HeuristicWeights()
        self.seed = int(seed)
        self.noise = float(noise)
        self.opponent_aware = opponent_aware
        self.rng = random.Random(seed)

    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        self.rng = random.Random(self.seed)

    def evaluate_placement(self, state: GameState, action: int, opponent_state: Optional[GameState] = None) -> float:
        placement = state.resolve(action)
        if placement is None:
            return float("-inf")
        board, cleared, eroded, perfect = simulate(state.board, placement.cells, state.ruleset)
        feats = board_features(board)
        w = self.weights
        landing_height = float(state.board.height - min(y for _x, y in placement.cells))
        score = (
            w.landing_height * landing_height
            + w.eroded_cells * eroded
            + w.row_transitions * feats["row_transitions"]
            + w.column_transitions * feats["column_transitions"]
            + w.holes * feats["holes"]
            + w.wells * feats["wells"]
        )
        if feats["max_height"] > w.height_threshold:
            score += w.high_stack_penalty * (feats["max_height"] - w.height_threshold)

        attack = 0
        if cleared:
            attack = state.ruleset.attack.base_attack(cleared, False, False)
            if perfect:
                attack += state.ruleset.attack.perfect_clear
            score += w.per_line * cleared
            if state.b2b_active and cleared == 4:
                score += w.per_line
        if self.opponent_aware and opponent_state is not None and attack:
            pressure = opponent_state.pending_garbage + max(0, opponent_state.board.max_height() - 10)
            score += w.per_attack * min(attack, 10) * (1.0 + w.opponent_pressure * pressure / 10.0)
        if self.noise > 0:
            score += self.rng.gauss(0.0, self.noise)
        return score

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        actions = state.legal_actions()
        if not actions:
            return -1
        best_action, best_score = actions[0], float("-inf")
        for action in actions:
            score = self.evaluate_placement(state, action, opponent_state)
            if score > best_score:
                best_action, best_score = action, score
        return best_action
