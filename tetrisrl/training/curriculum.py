"""Training curriculum and opponent schedules."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..agents import make_agent
from ..agents.base import BaseAgent
from ..environment.engine import GameState


@dataclass
class Stage:
    name: str
    timesteps: int
    opponent: str = "none"
    opponents: List[str] = field(default_factory=list)
    max_pieces: int = 300
    pressure_interval: int = 0
    pressure_lines: int = 0
    reward_overrides: Dict[str, float] = field(default_factory=dict)
    #: Optional per-stage ruleset override (experiment E: b2b charging on/off).
    ruleset: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Stage":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class MixedOpponent(BaseAgent):
    """Samples one opponent per episode from a list of agent specs."""

    name = "mixed"

    def __init__(self, specs: Sequence[str], seed: int = 0, **kwargs: Any) -> None:
        self.specs = list(specs) or ["random"]
        self.seed = seed
        self.kwargs = kwargs
        self.rng = random.Random(seed)
        self.current: Optional[BaseAgent] = None
        self.history: List[str] = []

    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        spec = self.rng.choice(self.specs)
        self.current = make_agent(spec, seed=self.rng.randrange(1 << 30), **self.kwargs)
        self.current.reset(self.rng.randrange(1 << 30))
        self.history.append(spec)

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        if self.current is None:
            self.reset()
        return self.current.choose_action(state, opponent_state)  # type: ignore[union-attr]


def build_opponent(stage: Stage, seed: int) -> Any:
    if stage.opponent in ("none", "solo", ""):
        return None
    if stage.opponent in ("variant", "variants"):
        from ..agents.variants import VariantOpponent

        return VariantOpponent(seed=seed)
    if stage.opponent == "mixed":
        return MixedOpponent(stage.opponents or ["random", "heuristic", "search"], seed=seed)
    return make_agent(stage.opponent, seed=seed)


def stages_from_config(config) -> List[Stage]:  # type: ignore[no-untyped-def]
    return [Stage.from_dict(d) for d in config.scaled_stage_plan()]
