"""Parameterised in-repo opponent variants for mixed-opponent training.

Fixed opponents overfit quickly.  These variants sample a *different* but
plausible agent per episode from the in-repo families:

* heuristic agents with jittered Dellacherie weights, evaluation noise and a
  randomised awareness of the opponent,
* beam-search agents with randomised depth, beam width and attack weighting.

The sampled parameters are deterministic given the episode seed, so replays and
mixed-opponent training remain reproducible.  They are *not* external engines;
the external adapters live in :mod:`tetrisrl.agents.opponents`.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any, Optional

from .base import BaseAgent
from .heuristic_agent import HeuristicAgent, HeuristicWeights
from .search_agent import BeamSearchAgent
from ..environment.engine import GameState


@dataclass(frozen=True)
class VariantSpec:
    kind: str
    weights: dict
    noise: float
    depth: int
    beam_width: int
    attack_weight: float
    opponent_aware: bool

    def to_dict(self) -> dict:
        return asdict(self)


def sample_variant(rng: random.Random, pool: tuple[str, ...] = ("heuristic", "search")) -> VariantSpec:
    base = HeuristicWeights()
    jitter = lambda value: value * rng.uniform(0.7, 1.3)  # noqa: E731
    weights = {
        "landing_height": jitter(base.landing_height),
        "eroded_cells": jitter(base.eroded_cells),
        "row_transitions": jitter(base.row_transitions),
        "column_transitions": jitter(base.column_transitions),
        "holes": jitter(base.holes) * rng.uniform(0.8, 1.5),
        "wells": jitter(base.wells),
        "per_line": jitter(base.per_line),
        "per_attack": rng.uniform(0.5, 4.0),
        "spin_bonus": jitter(base.spin_bonus),
        "opponent_pressure": rng.uniform(0.0, 0.8),
        "height_threshold": float(rng.randint(10, 16)),
        "high_stack_penalty": base.high_stack_penalty * rng.uniform(0.5, 1.5),
    }
    return VariantSpec(
        kind=rng.choice(pool),
        weights=weights,
        noise=rng.choice([0.0, 0.0, 0.05, 0.15]),
        depth=rng.randint(1, 3),
        beam_width=rng.choice([4, 6, 8, 12, 16, 24]),
        attack_weight=rng.uniform(0.5, 3.0),
        opponent_aware=rng.random() < 0.75,
    )


def build_variant(spec: VariantSpec, seed: int) -> BaseAgent:
    weights = HeuristicWeights(**{k: float(v) for k, v in spec.weights.items()})
    if spec.kind == "search":
        return BeamSearchAgent(
            depth=spec.depth,
            beam_width=spec.beam_width,
            weights=weights,
            seed=seed,
            attack_weight=spec.attack_weight,
            opponent_aware=spec.opponent_aware,
        )
    return HeuristicAgent(
        weights=weights,
        seed=seed,
        noise=spec.noise,
        opponent_aware=spec.opponent_aware,
    )


class VariantOpponent(BaseAgent):
    """Samples a fresh in-repo variant at the start of every episode."""

    name = "variant"

    def __init__(self, seed: int = 0, pool: tuple[str, ...] = ("heuristic", "search"), fixed: Optional[VariantSpec] = None) -> None:
        self.seed = int(seed)
        self.pool = pool
        self.fixed = fixed
        self.rng = random.Random(seed)
        self.current: Optional[BaseAgent] = None
        self.current_spec: Optional[VariantSpec] = None
        self.history: list[dict] = []

    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.current_spec = self.fixed or sample_variant(self.rng, self.pool)
        self.current = build_variant(self.current_spec, seed=self.rng.randrange(1 << 30))
        self.current.reset(self.rng.randrange(1 << 30))
        self.history.append(self.current_spec.to_dict())
        if len(self.history) > 50:
            self.history = self.history[-25:]

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        if self.current is None:
            self.reset()
        return self.current.choose_action(state, opponent_state)  # type: ignore[union-attr]
