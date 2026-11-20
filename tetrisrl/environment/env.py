"""Gymnasium-style RL environment wrapper around the versus arena.

``VersusEnv`` exposes a single agent's perspective:

* ``reset()`` -> ``(observation, info)``
* ``step(action)`` -> ``(observation, reward, terminated, truncated, info)``
* ``action_mask()`` -> ``list[bool]`` of length 80

The opponent is any object implementing :class:`~tetrisrl.environment.versus.MatchAgent`
(random, heuristic, beam-search, or a frozen neural policy).  ``solo=True`` runs
without an opponent for survival-only curriculum stages; optional scripted
garbage pressure can be layered on top.

Both PPO and Double DQN use *this* environment, the same observation encoder,
the same action mask, and the same reward function - no privileged learner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .actions import ACTION_SPACE
from .engine import GameState
from .observation import ObservationEncoder
from .rewards import BoardMetrics, RewardConfig, board_metrics, compute_reward
from .ruleset import RulesetConfig, load_ruleset
from .versus import MatchAgent, derive_seeds


@dataclass
class EnvConfig:
    max_pieces: int = 500
    solo: bool = False
    #: Every ``pressure_interval`` agent pieces, add ``pressure_lines`` garbage.
    pressure_interval: int = 0
    pressure_lines: int = 0
    #: Number of preview pieces visible to the agent.
    preview: int = 5
    include_opponent_observation: bool = True
    #: If the opponent tops out, terminate immediately (standard) or continue.
    end_on_opponent_topout: bool = True


class VersusEnv:
    metadata = {"render_modes": []}

    def __init__(
        self,
        ruleset: RulesetConfig | str | Dict[str, Any] = "tetrio_s2",
        opponent: Optional[MatchAgent] = None,
        seed: int = 0,
        reward_config: Optional[RewardConfig] = None,
        encoder: Optional[ObservationEncoder] = None,
        config: Optional[EnvConfig] = None,
        match_seed: Optional[int] = None,
    ) -> None:
        self.ruleset = load_ruleset(ruleset)
        self.opponent = opponent
        self.base_seed = int(seed)
        self.reward_config = reward_config or RewardConfig()
        self.config = config or EnvConfig()
        self.encoder = encoder or ObservationEncoder(
            include_opponent=self.config.include_opponent_observation,
            preview=self.config.preview,
            height=self.ruleset.board.height,
            width=self.ruleset.board.width,
            max_pieces=self.config.max_pieces,
        )
        self.match_seed = int(match_seed if match_seed is not None else seed)
        self.state: Optional[GameState] = None
        self.opponent_state: Optional[GameState] = None
        self.episode = 0
        self._done = True
        self._last_before: BoardMetrics = BoardMetrics()
        self.reset_counts = 0

    # ------------------------------------------------------------------
    @property
    def observation_size(self) -> int:
        return self.encoder.size

    @property
    def action_space_size(self) -> int:
        return ACTION_SPACE

    def _make_states(self, seed: int) -> None:
        sa, sb, ga, gb = derive_seeds(seed)
        self.state = GameState(
            self.ruleset, seed=sa, garbage_seed=ga, player_id=0, max_pieces=self.config.max_pieces
        )
        self.opponent_state = None
        if not self.config.solo:
            opp = self.opponent if self.opponent is not None else _default_opponent()
            self.opponent = opp
            self.opponent_state = GameState(
                self.ruleset, seed=sb, garbage_seed=gb, player_id=1, max_pieces=self.config.max_pieces
            )

    # ------------------------------------------------------------------
    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        if seed is not None:
            self.base_seed = int(seed)
        self.reset_counts += 1
        # Each episode derives a fresh match seed, but deterministically.
        self.match_seed = (self.base_seed + self.reset_counts * 7919) & 0x7FFFFFFF
        self._make_states(self.match_seed)
        assert self.state is not None
        if self.opponent is not None:
            self.opponent.reset(self.match_seed)
        self._done = False
        self._last_before = board_metrics(self.state)
        obs = self.encoder.encode(self.state, self.opponent_state)
        info = {
            "episode": self.reset_counts,
            "seed": self.match_seed,
            "action_mask": self.action_mask(),
        }
        return obs, info

    def action_mask(self) -> List[bool]:
        assert self.state is not None
        return self.state.action_mask()

    def _opponent_action(self) -> Optional[int]:
        if self.config.solo or self.opponent is None or self.opponent_state is None:
            return None
        if self.opponent_state.finished:
            return None
        mask = self.opponent_state.action_mask()
        action = self.opponent.choose_action(self.opponent_state, self.state)
        if not isinstance(action, int) or not (0 <= action < ACTION_SPACE) or not mask[action]:
            action = next((i for i, ok in enumerate(mask) if ok), -1)
        return action if action >= 0 else None

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        assert self.state is not None and not self._done, "call reset() before step()"
        before = self._last_before
        result = self.state.apply_action(int(action))
        info: Dict[str, Any] = {
            "valid": result.valid,
            "lines": result.lines,
            "attack": result.sent,
            "cancelled": result.cancelled,
            "spin": result.spin,
            "mini": result.mini,
            "garbage_inserted": result.garbage_inserted,
        }
        if not result.valid:
            info["invalid_action"] = True

        # Scripted garbage pressure for survival curriculum stages.
        if self.config.pressure_interval > 0 and self.state.pieces_placed > 0:
            if self.state.pieces_placed % self.config.pressure_interval == 0:
                self.state.receive_attack(self.config.pressure_lines)

        opponent_top_out = False
        opponent_result = None
        if not self.config.solo and self.opponent_state is not None and not self.opponent_state.finished:
            opp_action = self._opponent_action()
            if opp_action is None:
                opponent_top_out = True
            else:
                opponent_result = self.opponent_state.apply_action(opp_action)
                if opponent_result.sent > 0 and not self.state.finished:
                    self.state.receive_attack(opponent_result.sent)
                opponent_top_out = opponent_result.top_out
                info["opponent_lines"] = opponent_result.lines
                info["opponent_attack"] = opponent_result.sent

        agent_out = result.top_out or self.state.top_out
        terminated = agent_out or (opponent_top_out and self.config.end_on_opponent_topout)
        truncated = (not terminated) and self.state.pieces_placed >= self.config.max_pieces

        won: Optional[bool]
        if agent_out and opponent_top_out:
            won = None
        elif agent_out:
            won = False
        elif opponent_top_out:
            won = True
        else:
            won = None
        if not terminated and truncated:
            won = None

        after = board_metrics(self.state)
        reward, components = compute_reward(
            self.reward_config, before, after, result, terminal=terminated, won=won
        )
        self._last_before = after
        self._done = terminated or truncated
        obs = self.encoder.encode(self.state, self.opponent_state)
        info.update(
            {
                "reward_components": components,
                "won": won,
                "agent_top_out": agent_out,
                "opponent_top_out": opponent_top_out,
                "pieces": self.state.pieces_placed,
                "total_lines": self.state.clear_state.total_lines,
                "total_attack": self.state.clear_state.total_attack,
                "garbage_pending": self.state.pending_garbage,
                "max_height": after.max_height,
                "holes": after.holes,
                "bumpiness": after.bumpiness,
                "aggregate_height": after.aggregate_height,
                "metrics": after.__dict__,
                "action_mask": self.action_mask() if not self._done else [False] * ACTION_SPACE,
            }
        )
        return obs, float(reward), terminated, truncated, info

    # Convenience for evaluation.
    def run_episode(self, policy, max_steps: Optional[int] = None) -> Dict[str, Any]:
        obs, info = self.reset()
        total_reward = 0.0
        steps = 0
        while True:
            mask = np.asarray(self.action_mask(), dtype=bool)
            action = policy(obs, mask)
            obs, reward, terminated, truncated, info = self.step(action)
            total_reward += reward
            steps += 1
            if terminated or truncated:
                break
            if max_steps is not None and steps >= max_steps:
                break
        return {
            "reward": total_reward,
            "steps": steps,
            "won": info.get("won"),
            "pieces": info.get("pieces"),
            "lines": info.get("total_lines"),
            "attack": info.get("total_attack"),
            "final_height": info.get("max_height"),
            "holes": info.get("holes"),
        }

    def close(self) -> None:
        return None


def _default_opponent() -> MatchAgent:
    from ..agents.random_agent import RandomAgent

    return RandomAgent(seed=12345)
