"""Beam-search baseline with multi-ply lookahead.

This is the project's in-repo *genuine search-based* baseline: it enumerates all
legal placements for the current piece, keeps the best ``beam_width`` board
states, then expands each with the next preview pieces up to ``depth`` plies.
Placement quality is scored with the handcrafted evaluation from
:mod:`tetrisrl.agents.heuristic_agent` plus immediate attack value.

It is honest to describe this as a beam-search agent, not as MisaMino or any
external engine.  External engines, when available, are integrated through the
adapters in :mod:`tetrisrl.agents.opponents`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .base import BaseAgent
from .heuristic_agent import HeuristicAgent, HeuristicWeights, board_features, simulate
from ..environment.board import Board
from ..environment.engine import GameState
from ..environment.placement import placements_for


@dataclass
class _BeamNode:
    board: Board
    score: float
    first_action: int
    first_piece: str


class BeamSearchAgent(BaseAgent):
    name = "search"

    def __init__(
        self,
        depth: int = 2,
        beam_width: int = 12,
        weights: Optional[HeuristicWeights] = None,
        seed: int = 0,
        attack_weight: float = 1.5,
        opponent_aware: bool = True,
    ) -> None:
        self.depth = max(1, int(depth))
        self.beam_width = max(1, int(beam_width))
        self.heuristic = HeuristicAgent(weights=weights, seed=seed, opponent_aware=opponent_aware)
        self.attack_weight = attack_weight
        self.seed = seed
        self.last_nodes = 0

    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = seed
        self.heuristic.reset(seed)

    def _score(self, board: Board, cleared: int, eroded: int, perfect: bool, ruleset) -> float:
        feats = board_features(board)
        w: HeuristicWeights = self.heuristic.weights
        score = (
            w.eroded_cells * eroded
            + w.row_transitions * feats["row_transitions"]
            + w.column_transitions * feats["column_transitions"]
            + w.holes * feats["holes"]
            + w.wells * feats["wells"]
        )
        if feats["max_height"] > w.height_threshold:
            score += w.high_stack_penalty * (feats["max_height"] - w.height_threshold)
        if cleared:
            attack = ruleset.attack.base_attack(cleared, False, False)
            if perfect:
                attack += ruleset.attack.perfect_clear
            score += w.per_line * cleared + self.attack_weight * attack
        return score

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        if state.current is None or state.finished:
            return -1
        sequence = [state.current.name] + state.preview(max(0, self.depth - 1))
        width = state.ruleset.board.width
        spawn_y = state.ruleset.board.spawn_y
        kick = state.kick_tables

        beam: List[_BeamNode] = [_BeamNode(state.board.copy(), 0.0, -1, state.current.name)]
        self.last_nodes = 0
        for ply in range(self.depth):
            piece = sequence[ply] if ply < len(sequence) else state.preview(1)[0]
            expanded: List[_BeamNode] = []
            for node in beam:
                placements = placements_for(node.board, kick[piece], piece, spawn_y, width)
                self.last_nodes += len(placements)
                for rotation, column, x, cells in placements:
                    board, cleared, eroded, perfect = simulate(node.board, cells, state.ruleset)
                    score = node.score + self._score(board, cleared, eroded, perfect, state.ruleset)
                    first_action = node.first_action
                    if ply == 0:
                        first_action = rotation * 20 + column * 2
                    expanded.append(_BeamNode(board, score, first_action, piece))
            if not expanded:
                break
            expanded.sort(key=lambda n: n.score, reverse=True)
            beam = expanded[: self.beam_width]

        if not beam:
            return -1
        best = beam[0]
        # Prefer non-hold placement; hold is a separate decision the search does
        # not model (documented limitation).
        return best.first_action
