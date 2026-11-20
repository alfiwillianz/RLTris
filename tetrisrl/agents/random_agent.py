"""Uniform random legal-placement baseline."""

from __future__ import annotations

import random
from typing import Optional

from .base import BaseAgent
from ..environment.engine import GameState


class RandomAgent(BaseAgent):
    """Chooses uniformly among the legal placements (never plays an illegal one)."""

    name = "random"

    def __init__(self, seed: int = 0, hold_probability: float = 0.5) -> None:
        self.seed = int(seed)
        self.hold_probability = hold_probability
        self.rng = random.Random(seed)
        self.actions_taken = 0

    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.actions_taken = 0

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        actions = state.legal_actions()
        if not actions:
            return -1
        # Prefer non-hold actions unless the configured probability says otherwise.
        non_hold = [a for a in actions if not (a & 1)]
        if non_hold and self.rng.random() > self.hold_probability:
            choices = non_hold
        else:
            choices = actions
        self.actions_taken += 1
        return self.rng.choice(choices)
