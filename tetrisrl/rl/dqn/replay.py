"""Preallocated circular experience-replay buffer.

Observations are stored as ``float32`` in fixed ``numpy`` arrays so that the
buffer has predictable memory use and no per-transition Python objects.  The
default capacity (200k) costs roughly:

    capacity * (2 * obs_size * 4 + 1 + 8 + n_actions) bytes
    200_000 * (2 * 887 * 4 + 9 + 80) ~= 1.4 GiB

Arrays are created with ``np.empty`` (not ``np.zeros``) so pages are only
committed as transitions are written.  Masks are stored as ``bool``.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import torch

__all__ = ["ReplayBuffer"]


def _as_numpy(value: Any, dtype: Any) -> np.ndarray:
    """Convert numpy / torch (any device) input to a flat numpy array."""
    if torch.is_tensor(value):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=dtype).reshape(-1)


class ReplayBuffer:
    """Fixed-capacity circular replay buffer.

    Parameters
    ----------
    capacity:
        Maximum number of transitions retained.
    obs_size:
        Length of the flat observation vector.
    n_actions:
        Length of the action mask.
    seed:
        Seed for the sampling RNG.
    """

    def __init__(
        self,
        capacity: int,
        obs_size: int,
        n_actions: int = 80,
        seed: int = 0,
    ) -> None:
        capacity = int(capacity)
        obs_size = int(obs_size)
        n_actions = int(n_actions)
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        if obs_size <= 0:
            raise ValueError(f"obs_size must be positive, got {obs_size}")
        if n_actions <= 0:
            raise ValueError(f"n_actions must be positive, got {n_actions}")

        self.capacity = capacity
        self.obs_size = obs_size
        self.n_actions = n_actions
        self.seed = int(seed)
        self._rng = np.random.default_rng(self.seed)

        self.obs = np.empty((capacity, obs_size), dtype=np.float32)
        self.actions = np.empty(capacity, dtype=np.int64)
        self.rewards = np.empty(capacity, dtype=np.float32)
        self.next_obs = np.empty((capacity, obs_size), dtype=np.float32)
        self.dones = np.empty(capacity, dtype=np.bool_)
        self.next_masks = np.empty((capacity, n_actions), dtype=np.bool_)

        self._pos = 0
        self._size = 0

    # ------------------------------------------------------------------
    def add(
        self,
        obs: Any,
        action: int,
        reward: float,
        next_obs: Any,
        done: bool,
        next_mask: Any,
    ) -> None:
        """Insert one transition (overwriting the oldest when full)."""
        obs_arr = _as_numpy(obs, np.float32)
        next_obs_arr = _as_numpy(next_obs, np.float32)
        mask_arr = _as_numpy(next_mask, np.bool_)
        if obs_arr.size != self.obs_size:
            raise ValueError(f"obs must have {self.obs_size} elements, got {obs_arr.size}")
        if next_obs_arr.size != self.obs_size:
            raise ValueError(
                f"next_obs must have {self.obs_size} elements, got {next_obs_arr.size}"
            )
        if mask_arr.size != self.n_actions:
            raise ValueError(f"next_mask must have {self.n_actions} elements, got {mask_arr.size}")
        action = int(action)
        if not 0 <= action < self.n_actions:
            raise ValueError(f"action {action} outside [0, {self.n_actions})")

        i = self._pos
        self.obs[i] = obs_arr
        self.actions[i] = action
        self.rewards[i] = float(reward)
        self.next_obs[i] = next_obs_arr
        self.dones[i] = bool(done)
        self.next_masks[i] = mask_arr

        self._pos = (self._pos + 1) % self.capacity
        self._size = min(self._size + 1, self.capacity)

    # ------------------------------------------------------------------
    def sample(self, batch_size: int, device: str | torch.device | None = None) -> Dict[str, torch.Tensor]:
        """Uniformly sample a batch (without replacement when possible)."""
        if self._size == 0:
            raise ValueError("cannot sample from an empty replay buffer")
        batch_size = int(batch_size)
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        replace = batch_size > self._size
        indices = self._rng.choice(self._size, size=batch_size, replace=replace)

        target_device = torch.device("cpu") if device is None else torch.device(device)
        return {
            "obs": torch.as_tensor(self.obs[indices], dtype=torch.float32, device=target_device),
            "actions": torch.as_tensor(self.actions[indices], dtype=torch.long, device=target_device),
            "rewards": torch.as_tensor(
                self.rewards[indices], dtype=torch.float32, device=target_device
            ),
            "next_obs": torch.as_tensor(
                self.next_obs[indices], dtype=torch.float32, device=target_device
            ),
            "dones": torch.as_tensor(self.dones[indices], dtype=torch.float32, device=target_device),
            "next_masks": torch.as_tensor(
                self.next_masks[indices], dtype=torch.bool, device=target_device
            ),
        }

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return self._size

    @property
    def position(self) -> int:
        """Index of the next slot to be written."""
        return self._pos

    @property
    def nbytes(self) -> int:
        """Approximate memory footprint of the buffer arrays."""
        return int(
            self.obs.nbytes
            + self.actions.nbytes
            + self.rewards.nbytes
            + self.next_obs.nbytes
            + self.dones.nbytes
            + self.next_masks.nbytes
        )
