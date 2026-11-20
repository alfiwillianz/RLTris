"""Wrap a trained PPO / DQN model as an arena agent."""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np

from .base import BaseAgent
from ..environment.engine import GameState
from ..environment.observation import ObservationEncoder


class PolicyAgent(BaseAgent):
    name = "policy"

    def __init__(
        self,
        model: Any,
        encoder: ObservationEncoder,
        name: str = "policy",
        deterministic: bool = True,
        action_space: int = 80,
    ) -> None:
        self.model = model
        self.encoder = encoder
        self.name = name
        self.deterministic = deterministic
        self.action_space = action_space
        self._last_obs: Optional[np.ndarray] = None
        self._last_mask: Optional[np.ndarray] = None

    def reset(self, seed: Optional[int] = None) -> None:
        return None

    def set_epsilon(self, epsilon: float) -> None:
        self._epsilon = epsilon

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        obs = self.encoder.encode(state, opponent_state)
        mask = np.asarray(state.action_mask(), dtype=bool)
        if not mask.any():
            return -1
        self._last_obs = obs
        self._last_mask = mask
        out = self.model.act(obs, mask, deterministic=self.deterministic)
        if isinstance(out, tuple):
            return int(out[0])
        return int(out)

    @classmethod
    def from_checkpoint(cls, path: str, name: str = "policy", device: Optional[str] = None) -> "PolicyAgent":
        import torch

        ckpt = torch.load(path, map_location="cpu", weights_only=False)
        algorithm = ckpt.get("algorithm", "ppo")
        obs_cfg = ckpt.get("extra", {}).get("observation", {}) if isinstance(ckpt.get("extra"), dict) else {}
        encoder = ObservationEncoder(
            include_opponent=obs_cfg.get("include_opponent", True),
            preview=obs_cfg.get("preview", 5),
            height=obs_cfg.get("height", 40),
            width=obs_cfg.get("width", 10),
            max_pieces=obs_cfg.get("max_pieces", 1000),
        )
        if algorithm == "dqn":
            from ..rl.dqn.agent import DQNAgent

            model = DQNAgent.load(path, device=device)
        else:
            from ..rl.ppo.agent import PPOAgent

            model = PPOAgent.load(path, device=device)
        return cls(model, encoder, name=name)
