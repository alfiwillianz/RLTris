"""Double DQN agent for the Tetris versus environment.

Highlights
----------
* Double-Q target: the *online* network selects ``a*`` over **valid** actions
  only; the *target* network evaluates ``Q_target(s', a*)``.
* Invalid next actions can never be selected, even if their Q-values are huge.
* Huber (smooth-L1) TD loss, gradient clipping, hard target sync every
  ``target_sync_steps`` environment steps, linear epsilon decay.
* Optional n-step returns (``n_step``); per-environment accumulator when the
  optional ``env_id`` argument is supplied to :meth:`DQNAgent.observe`.
"""

from __future__ import annotations

import os
import warnings
from collections import deque
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import torch
import torch.nn.functional as F
from torch import Tensor

from ..masked import masked_argmax
from ..networks import QNetwork, resolve_device
from ...environment.observation import OBS_VERSION
from .replay import ReplayBuffer

__all__ = ["DQNConfig", "DQNAgent"]


def _merge_extra(checkpoint: dict[str, Any], extra: dict | None) -> dict[str, Any]:
    """Merge caller metadata without clobbering contract keys.

    Training code passes run metadata (including its own ``config``) via
    ``extra``.  The checkpoint contract requires ``config`` to be the *agent*
    config, so extras are nested under ``"extra"`` and only non-conflicting
    keys are copied to the top level for convenience.
    """
    if not extra:
        return checkpoint
    checkpoint["extra"] = dict(extra)
    for key, value in extra.items():
        if key not in checkpoint:
            checkpoint[key] = value
    if "config" in extra:
        checkpoint.setdefault("train_config", extra["config"])
    return checkpoint


def _as_tensor(value: Any, dtype: torch.dtype, device: torch.device) -> Tensor:
    """Convert numpy/list/torch input to a tensor on ``device``."""
    if torch.is_tensor(value):
        return value.detach().to(device=device, dtype=dtype)
    return torch.as_tensor(np.asarray(value), dtype=dtype, device=device)


@dataclass
class DQNConfig:
    lr: float = 1e-4
    gamma: float = 0.99
    epsilon_start: float = 1.0
    epsilon_end: float = 0.02
    epsilon_decay_steps: int = 100_000
    batch_size: int = 256
    buffer_size: int = 200_000
    target_sync_steps: int = 2_000
    huber_delta: float = 1.0
    max_grad_norm: float = 10.0
    hidden_sizes: tuple[int, int] = (256, 256)
    double: bool = True
    learning_starts: int = 1_000
    train_freq: int = 1
    n_step: int = 1


class DQNAgent:
    """Double DQN learner (owns online/target networks and a replay buffer)."""

    def __init__(
        self,
        obs_size: int,
        n_actions: int = 80,
        config: DQNConfig | None = None,
        device: str | None = None,
        seed: int = 0,
    ) -> None:
        if isinstance(config, Mapping):
            config = DQNConfig(**dict(config))
        self.config = config or DQNConfig()
        self.obs_size = int(obs_size)
        self.n_actions = int(n_actions)
        self.seed = int(seed)
        self.device = resolve_device(device)
        self.obs_version = OBS_VERSION

        self.steps = 0
        self.updates = 0
        self._last_sync_step = 0
        self._sync_count = 0
        self._pending: dict[int, deque] = {}

        torch.manual_seed(self.seed)
        self._rng = np.random.default_rng(self.seed)

        self.online = QNetwork(
            self.obs_size,
            self.n_actions,
            hidden_sizes=tuple(self.config.hidden_sizes),
        ).to(self.device)
        self.target = QNetwork(
            self.obs_size,
            self.n_actions,
            hidden_sizes=tuple(self.config.hidden_sizes),
        ).to(self.device)
        self.target.load_state_dict(self.online.state_dict())
        self.target.eval()
        for param in self.target.parameters():
            param.requires_grad_(False)

        self.optimizer = torch.optim.Adam(self.online.parameters(), lr=float(self.config.lr))
        self.buffer = ReplayBuffer(
            capacity=self.config.buffer_size,
            obs_size=self.obs_size,
            n_actions=self.n_actions,
            seed=self.seed,
        )

    # -- conveniences ------------------------------------------------------
    @property
    def device_used(self) -> str:
        return str(self.device)

    @property
    def online_net(self) -> QNetwork:
        return self.online

    @property
    def target_net(self) -> QNetwork:
        return self.target

    @property
    def q_network(self) -> QNetwork:
        return self.online

    @property
    def network(self) -> QNetwork:
        return self.online

    @property
    def replay_buffer(self) -> ReplayBuffer:
        return self.buffer

    def train(self) -> "DQNAgent":
        self.online.train()
        self.target.eval()
        return self

    def eval(self) -> "DQNAgent":
        self.online.eval()
        self.target.eval()
        return self

    # -- exploration -------------------------------------------------------
    def epsilon_for_step(self, step: int) -> float:
        """Linear epsilon decay from ``epsilon_start`` to ``epsilon_end``."""
        step = max(0, int(step))
        decay = int(self.config.epsilon_decay_steps)
        if decay <= 0:
            return float(self.config.epsilon_end)
        fraction = min(1.0, step / float(decay))
        return float(
            self.config.epsilon_start
            + (self.config.epsilon_end - self.config.epsilon_start) * fraction
        )

    # -- acting ------------------------------------------------------------
    @torch.no_grad()
    def act(
        self,
        obs: Any,
        mask: Any,
        step: int | None = None,
        epsilon: float | None = None,
        deterministic: bool = False,
    ) -> int:
        """Epsilon-greedy action over the valid action mask."""
        mask_np = self._mask_numpy(mask)
        valid = np.flatnonzero(mask_np)
        if valid.size == 0:
            raise ValueError("action mask has no valid actions")

        if not deterministic and epsilon is None:
            epsilon = self.epsilon_for_step(self.steps if step is None else int(step))
        if not deterministic and epsilon is not None and epsilon > 0.0:
            if float(self._rng.random()) < float(epsilon):
                return int(self._rng.choice(valid))

        obs_t = self._obs_tensor(obs)
        q_values = self.online(obs_t)
        mask_t = torch.as_tensor(mask_np, dtype=torch.bool, device=self.device).unsqueeze(0)
        return int(masked_argmax(q_values, mask_t).item())

    # -- data collection ---------------------------------------------------
    def observe(
        self,
        obs: Any,
        action: int,
        reward: float,
        next_obs: Any,
        done: bool,
        next_mask: Any,
        env_id: int = 0,
    ) -> None:
        """Store one transition, applying n-step accumulation when configured."""
        n_step = max(1, int(self.config.n_step))
        if n_step == 1:
            self.buffer.add(obs, action, reward, next_obs, done, next_mask)
        else:
            pending = self._pending.setdefault(int(env_id), deque())
            pending.append((obs, action, float(reward), next_obs, bool(done), next_mask))
            if done:
                self._flush_pending(int(env_id), terminal=True)
            elif len(pending) >= n_step:
                self._flush_pending(int(env_id), terminal=False)
        self.steps += 1

    def _flush_pending(self, env_id: int, terminal: bool) -> None:
        """Emit n-step transitions.

        When the chain ends in a terminal transition every flushed window sees
        ``done=True`` (no bootstrap); otherwise only the oldest window is
        emitted and the accumulator keeps sliding.
        """
        pending = self._pending.get(env_id)
        if not pending:
            return
        gamma = float(self.config.gamma)
        n_step = max(1, int(self.config.n_step))
        while pending:
            window = list(pending)
            if not terminal:
                window = window[:n_step]
            discounted = 0.0
            for j, (_o, _a, r, _no, _d, _m) in enumerate(window):
                discounted += (gamma**j) * float(r)
            first = window[0]
            last = window[-1]
            self.buffer.add(
                first[0],
                first[1],
                discounted,
                last[3],
                bool(terminal and last[4]),
                last[5],
            )
            pending.popleft()
            if not terminal:
                break

    # -- learning ----------------------------------------------------------
    def _mask_numpy(self, mask: Any) -> np.ndarray:
        if torch.is_tensor(mask):
            mask_np = mask.detach().cpu().numpy()
        else:
            mask_np = np.asarray(mask)
        mask_np = mask_np.reshape(-1)
        if mask_np.size != self.n_actions:
            raise ValueError(
                f"mask must have {self.n_actions} elements, got {mask_np.size}"
            )
        return mask_np.astype(bool)

    def _obs_tensor(self, obs: Any) -> Tensor:
        if torch.is_tensor(obs):
            tensor = obs.detach().to(device=self.device, dtype=torch.float32)
        else:
            tensor = torch.as_tensor(
                np.asarray(obs, dtype=np.float32), dtype=torch.float32, device=self.device
            )
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)
        if tensor.dim() != 2 or tensor.shape[-1] != self.obs_size:
            raise ValueError(
                f"expected obs shape [B, {self.obs_size}], got {tuple(tensor.shape)}"
            )
        return tensor

    def compute_targets(
        self,
        rewards: Tensor,
        next_obs: Tensor,
        dones: Tensor,
        next_masks: Tensor,
    ) -> tuple[Tensor, Tensor, Tensor]:
        """Compute Double-DQN targets with masked next-action selection.

        Returns ``(targets, next_actions, bootstrap_q)``.  ``next_actions`` is
        the online network's argmax restricted to valid next actions.
        """
        next_obs = _as_tensor(next_obs, torch.float32, self.device)
        rewards = _as_tensor(rewards, torch.float32, self.device).reshape(-1)
        dones = _as_tensor(dones, torch.float32, self.device).reshape(-1)
        next_masks = _as_tensor(next_masks, torch.bool, self.device)
        if next_masks.dim() != 2 or next_masks.shape[1] != self.n_actions:
            raise ValueError(
                f"next_masks must be [B, {self.n_actions}], got {tuple(next_masks.shape)}"
            )

        with torch.no_grad():
            next_online = self.online(next_obs)
            next_target = self.target(next_obs)
            if self.config.double:
                next_actions = masked_argmax(next_online, next_masks)
                bootstrap = next_target.gather(1, next_actions.unsqueeze(1)).squeeze(1)
            else:
                next_actions = masked_argmax(next_target, next_masks)
                neg = torch.finfo(next_target.dtype).min
                bootstrap = next_target.masked_fill(~next_masks, neg).max(dim=1).values
            discount = float(self.config.gamma) ** max(1, int(self.config.n_step))
            targets = rewards + discount * (1.0 - dones) * bootstrap
        return targets, next_actions, bootstrap

    def update(self, step: int | None = None) -> Optional[dict[str, float]]:
        """Sample a batch and apply one gradient step, or return ``None``."""
        step_value = self.steps if step is None else int(step)
        if step_value < int(self.config.learning_starts):
            return None
        if self.config.train_freq > 1 and step_value % int(self.config.train_freq) != 0:
            return None
        if len(self.buffer) < int(self.config.batch_size):
            return None
        if (
            int(self.config.target_sync_steps) > 0
            and step_value - self._last_sync_step >= int(self.config.target_sync_steps)
        ):
            self.sync_target()
            self._last_sync_step = step_value

        batch = self.buffer.sample(int(self.config.batch_size), device=self.device)
        obs = batch["obs"]
        actions = batch["actions"]
        rewards = batch["rewards"]
        next_obs = batch["next_obs"]
        dones = batch["dones"]
        next_masks = batch["next_masks"]

        q_values = self.online(obs)
        q_selected = q_values.gather(1, actions.unsqueeze(1)).squeeze(1)
        targets, _next_actions, _bootstrap = self.compute_targets(
            rewards, next_obs, dones, next_masks
        )
        loss = F.smooth_l1_loss(q_selected, targets, beta=float(self.config.huber_delta))

        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(
            self.online.parameters(), float(self.config.max_grad_norm)
        )
        self.optimizer.step()
        self.updates += 1

        with torch.no_grad():
            td_error = (q_selected - targets).abs().mean()
            metrics = {
                "loss": float(loss.detach().item()),
                "q_mean": float(q_selected.mean().item()),
                "target_mean": float(targets.mean().item()),
                "td_error": float(td_error.item()),
                "epsilon": float(self.epsilon_for_step(self.steps)),
                "buffer_size": float(len(self.buffer)),
                "lr": float(self.optimizer.param_groups[0]["lr"]),
                "grad_norm": float(grad_norm),
                "updates": float(self.updates),
                "steps": float(self.steps),
                "sync_count": float(self._sync_count),
            }
        for key, value in list(metrics.items()):
            if not np.isfinite(value):
                metrics[key] = 0.0
        return metrics

    def sync_target(self) -> None:
        """Hard-copy online parameters into the target network."""
        self.target.load_state_dict(self.online.state_dict())
        self.target.eval()
        for param in self.target.parameters():
            param.requires_grad_(False)
        self._sync_count += 1

    # -- persistence -------------------------------------------------------
    def save(self, path: str | os.PathLike, extra: dict | None = None) -> None:
        path = Path(path)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint: dict[str, Any] = {
            "algorithm": "dqn",
            "obs_size": self.obs_size,
            "n_actions": self.n_actions,
            "config": asdict(self.config),
            "online_state": self.online.state_dict(),
            "target_state": self.target.state_dict(),
            "optimizer_state": self.optimizer.state_dict(),
            "steps": int(self.steps),
            "updates": int(self.updates),
            "obs_version": OBS_VERSION,
            "last_sync_step": int(self._last_sync_step),
            "sync_count": int(self._sync_count),
            "seed": self.seed,
            "device": str(self.device),
        }
        _merge_extra(checkpoint, extra)
        torch.save(checkpoint, path)

    @classmethod
    def load(cls, path: str | os.PathLike, device: str | None = None) -> "DQNAgent":
        resolved = resolve_device(device)
        try:
            checkpoint = torch.load(path, map_location=resolved, weights_only=False)
        except TypeError:  # pragma: no cover - older torch
            checkpoint = torch.load(path, map_location=resolved)
        raw_config = dict(checkpoint.get("config", {}))
        if "hidden_sizes" not in raw_config and isinstance(raw_config.get("dqn"), dict):
            # Older artifacts saved the full training config under "config".
            raw_config = {**raw_config, **raw_config["dqn"]}
        cfg_values = {
            key: value
            for key, value in raw_config.items()
            if key in {f.name for f in fields(DQNConfig)}
        }
        if "hidden_sizes" in cfg_values:
            cfg_values["hidden_sizes"] = tuple(cfg_values["hidden_sizes"])
        config = DQNConfig(**cfg_values)
        agent = cls(
            int(checkpoint["obs_size"]),
            int(checkpoint.get("n_actions", 80)),
            config=config,
            device=str(resolved),
            seed=int(checkpoint.get("seed", 0)),
        )
        agent.online.load_state_dict(checkpoint["online_state"])
        agent.target.load_state_dict(checkpoint["target_state"])
        optimizer_state = checkpoint.get("optimizer_state")
        if optimizer_state:
            agent.optimizer.load_state_dict(optimizer_state)
        agent.steps = int(checkpoint.get("steps", 0))
        agent.updates = int(checkpoint.get("updates", 0))
        agent._last_sync_step = int(checkpoint.get("last_sync_step", agent.steps))
        agent._sync_count = int(checkpoint.get("sync_count", 0))
        saved_version = int(checkpoint.get("obs_version", OBS_VERSION))
        agent.obs_version = saved_version
        if saved_version != OBS_VERSION:
            warnings.warn(
                f"checkpoint obs_version={saved_version} but current OBS_VERSION={OBS_VERSION}; "
                "observations may have changed",
                RuntimeWarning,
                stacklevel=2,
            )
        return agent

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"DQNAgent(obs_size={self.obs_size}, n_actions={self.n_actions}, "
            f"device={self.device}, steps={self.steps}, updates={self.updates}, "
            f"buffer={len(self.buffer)}/{self.buffer.capacity})"
        )
