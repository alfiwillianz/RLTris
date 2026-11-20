"""Agent interface shared by baselines, opponents, and RL policies.

The interface intentionally mirrors the opponent adapter contract required by
the project specification::

    reset() / observe() / choose_action() / receive_result() / terminate()

RL policies additionally expose ``act(observation, mask)`` and are wrapped by
:class:`PolicyAgent` so they can play in the arena like any other agent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from ..environment.engine import GameState


class Agent(Protocol):
    name: str

    def reset(self, seed: Optional[int] = None) -> None: ...

    def observe(self, state: GameState, opponent_state: Optional[GameState] = None) -> Dict[str, Any]: ...

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int: ...

    def receive_result(self, result: Any) -> None: ...

    def terminate(self) -> None: ...


class BaseAgent:
    """Convenience base class with no-op bookkeeping hooks."""

    name = "base"

    def reset(self, seed: Optional[int] = None) -> None:
        return None

    def observe(self, state: GameState, opponent_state: Optional[GameState] = None) -> Dict[str, Any]:
        return {}

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        raise NotImplementedError

    def receive_result(self, result: Any) -> None:
        return None

    def terminate(self) -> None:
        return None


