"""Baseline agents and factory helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import Agent, BaseAgent
from .heuristic_agent import HeuristicAgent, HeuristicWeights
from .policy_agent import PolicyAgent
from .random_agent import RandomAgent
from .search_agent import BeamSearchAgent

__all__ = [
    "Agent",
    "BaseAgent",
    "RandomAgent",
    "HeuristicAgent",
    "HeuristicWeights",
    "BeamSearchAgent",
    "PolicyAgent",
    "make_agent",
]


def make_agent(spec: str, seed: int = 0, **kwargs: Any) -> Any:
    """Create an agent from a spec string.

    ``random``, ``heuristic``, ``search``, ``ppo:<checkpoint>``, ``dqn:<checkpoint>``.
    """
    spec = spec.strip()
    if spec == "random":
        return RandomAgent(seed=seed)
    if spec == "heuristic":
        return HeuristicAgent(seed=seed, **kwargs)
    if spec in ("search", "beam"):
        return BeamSearchAgent(seed=seed, **kwargs)
    if spec == "coldclear":
        # External engine: the adapter ignores our RNG seed (the engine is a
        # separate process with its own search).
        from .opponents.tbp import TBPAgent

        kwargs.pop("seed", None)
        return TBPAgent(**kwargs)
    if spec.startswith("ppo:") or spec.startswith("dqn:"):
        _, path = spec.split(":", 1)
        return PolicyAgent.from_checkpoint(path, name=spec.split(":")[0], **kwargs)
    raise ValueError(f"unknown agent spec {spec!r}")
