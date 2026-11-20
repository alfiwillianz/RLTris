"""Proximal Policy Optimization for the Tetris versus environment.

Design notes
------------
* The policy is a *masked* categorical distribution: illegal placements have
  probability exactly zero and are never sampled.
* Advantages use Generalized Advantage Estimation with correct terminal
  handling.  The rollout format contains ``dones`` for both terminations and
  time-limit truncations; the optional ``last_values`` key lets the collector
  pass ``V(final_obs)`` for *truncated* environments so the final step
  bootstraps.  Without it the last step is treated as a hard boundary.
* The update reports the standard PPO diagnostics: approximate KL, clip
  fraction, entropy, explained variance and gradient norm.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from torch import Tensor

from ..masked import masked_argmax, masked_categorical, masked_entropy, masked_log_softmax
from ..networks import ActorCritic, resolve_device
from ...environment.observation import OBS_VERSION

__all__ = ["PPOConfig", "PPOAgent", "compute_gae"]


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




# ---------------------------------------------------------------------------
# Generalized Advantage Estimation
# ---------------------------------------------------------------------------
def _as_numpy(value: Any, dtype: Any) -> np.ndarray:
    """Convert numpy / torch (any device) input to a numpy array."""
    if torch.is_tensor(value):
        return value.detach().cpu().numpy().astype(dtype, copy=False)
    return np.asarray(value, dtype=dtype)


def compute_gae(
    rewards: np.ndarray,
    values: np.ndarray,
    dones: np.ndarray,
    gamma: float,
    lam: float,
    last_values: np.ndarray | float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute GAE advantages and value targets.

    Parameters
    ----------
    rewards, values, dones:
        Arrays with identical shape, either ``[T]`` for one environment or
        ``[T, N]`` for ``N`` parallel environments.  ``dones[t]`` is ``1`` when
        the transition ``t`` ended the episode (termination *or* truncation).
    gamma, lam:
        Discount and GAE lambda.
    last_values:
        Bootstrap value ``V(s_T)`` used only for the final step whose ``done``
        flag is ``False`` (the usual time-limit truncation case).  Scalar or
        shape ``[N]``.  Defaults to ``0`` (episode boundary).

    Returns
    -------
    advantages, returns:
        Same shape as ``rewards``; ``returns = advantages + values``.

    The recursion is vectorised over trailing dimensions so a batched rollout
    is handled exactly like independent single-environment rollouts.
    """
    rewards = np.asarray(rewards, dtype=np.float32)
    values = np.asarray(values, dtype=np.float32)
    dones = np.asarray(dones, dtype=np.float32)
    if rewards.ndim == 0:
        raise ValueError("rewards must have at least one dimension [T] or [T, N]")
    if values.ndim != rewards.ndim or values.shape[1:] != rewards.shape[1:]:
        raise ValueError(f"values shape {values.shape} incompatible with rewards {rewards.shape}")
    if values.shape[0] not in (rewards.shape[0], rewards.shape[0] + 1):
        raise ValueError(
            "values must have T rows, or T+1 rows where the extra row is "
            f"V(s_T); got {values.shape[0]} rows for T={rewards.shape[0]}"
        )
    if dones.shape != rewards.shape:
        raise ValueError(f"dones shape {dones.shape} != rewards shape {rewards.shape}")

    advantage = np.zeros_like(rewards, dtype=np.float32)
    if rewards.shape[0] == 0:
        return advantage, advantage.copy()

    if values.shape[0] == rewards.shape[0] + 1:
        # Explicit bootstrap row: correct for time-limit truncation.
        next_values = np.array(values[1:], dtype=np.float32)
    else:
        if last_values is None:
            bootstrap = np.zeros(rewards.shape[1:], dtype=np.float32)
        else:
            bootstrap = np.asarray(last_values, dtype=np.float32)
            if rewards.ndim == 1 and bootstrap.ndim == 1 and bootstrap.size == 1:
                bootstrap = bootstrap.reshape(())
            try:
                bootstrap = np.broadcast_to(bootstrap, rewards.shape[1:]).astype(
                    np.float32, copy=True
                )
            except ValueError as exc:
                raise ValueError(
                    f"last_values shape {np.shape(last_values)} cannot broadcast to "
                    f"{rewards.shape[1:]}"
                ) from exc
        next_values = np.empty_like(values)
        if rewards.shape[0] > 1:
            next_values[:-1] = values[1:]
        next_values[-1] = bootstrap

    deltas = rewards + float(gamma) * next_values * (1.0 - dones) - values[: rewards.shape[0]]
    gae = np.zeros(rewards.shape[1:], dtype=np.float32)
    for t in range(rewards.shape[0] - 1, -1, -1):
        gae = deltas[t] + float(gamma) * float(lam) * (1.0 - dones[t]) * gae
        advantage[t] = gae
    return advantage, advantage + values[: rewards.shape[0]]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class PPOConfig:
    lr: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_ratio: float = 0.2
    value_coef: float = 0.5
    entropy_coef: float = 0.01
    max_grad_norm: float = 0.5
    epochs: int = 4
    minibatch_size: int = 256
    hidden_sizes: tuple[int, int] = (256, 256)
    normalize_advantage: bool = True
    target_kl: float | None = None
    max_episode_steps: int = 100000  # informational


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class PPOAgent:
    """Actor-critic PPO agent (not an ``nn.Module``; owns one)."""

    def __init__(
        self,
        obs_size: int,
        n_actions: int = 80,
        config: PPOConfig | None = None,
        device: str | None = None,
        seed: int = 0,
    ) -> None:
        if isinstance(config, Mapping):
            config = PPOConfig(**dict(config))
        self.config = config or PPOConfig()
        self.obs_size = int(obs_size)
        self.n_actions = int(n_actions)
        self.seed = int(seed)
        self.device = resolve_device(device)
        self.obs_version = OBS_VERSION
        self.update_count = 0

        torch.manual_seed(self.seed)
        np.random.seed(self.seed % (2**32))

        self.model = ActorCritic(
            self.obs_size,
            self.n_actions,
            hidden_sizes=tuple(self.config.hidden_sizes),
        ).to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=float(self.config.lr))

    # -- conveniences ------------------------------------------------------
    @property
    def device_used(self) -> str:
        return str(self.device)

    @property
    def network(self) -> ActorCritic:
        return self.model

    def train(self) -> "PPOAgent":
        self.model.train()
        return self

    def eval(self) -> "PPOAgent":
        self.model.eval()
        return self

    # -- inference ---------------------------------------------------------
    def _obs_tensor(self, obs: Any) -> Tensor:
        if torch.is_tensor(obs):
            tensor = obs.detach().to(device=self.device, dtype=torch.float32)
        else:
            tensor = torch.as_tensor(np.asarray(obs), dtype=torch.float32, device=self.device)
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)
        if tensor.dim() != 2 or tensor.shape[-1] != self.obs_size:
            raise ValueError(
                f"expected obs shape [B, {self.obs_size}], got {tuple(tensor.shape)}"
            )
        return tensor

    def _mask_tensor(self, mask: Any) -> Tensor:
        tensor = mask if torch.is_tensor(mask) else torch.as_tensor(mask)
        tensor = tensor.to(device=self.device, dtype=torch.bool)
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)
        if tensor.dim() != 2 or tensor.shape[-1] != self.n_actions:
            raise ValueError(
                f"expected mask shape [B, {self.n_actions}], got {tuple(tensor.shape)}"
            )
        return tensor

    @torch.no_grad()
    def act(
        self,
        obs: np.ndarray,
        mask: Any,
        deterministic: bool = False,
    ) -> tuple[int, float, float]:
        """Select an action, returning ``(action, log_prob, value)``."""
        obs_t = self._obs_tensor(obs)
        mask_t = self._mask_tensor(mask)
        if obs_t.shape[0] != mask_t.shape[0]:
            raise ValueError("obs and mask batch sizes differ")

        logits, values = self.model(obs_t)
        if deterministic:
            action_t = masked_argmax(logits, mask_t)
        else:
            action_t = masked_categorical(logits, mask_t).sample()
        logp = masked_log_softmax(logits, mask_t).gather(1, action_t.unsqueeze(1)).squeeze(1)
        return int(action_t.item()), float(logp.item()), float(values.item())

    def evaluate_actions(
        self,
        obs: Tensor,
        actions: Tensor,
        masks: Tensor,
    ) -> tuple[Tensor, Tensor, Tensor]:
        """Return ``(log_probs, entropy, values)`` for a batch of actions."""
        obs_t = self._obs_tensor(obs)
        mask_t = self._mask_tensor(masks)
        if not torch.is_tensor(actions):
            actions = torch.as_tensor(actions)
        actions_t = actions.to(device=self.device, dtype=torch.long).reshape(-1)
        if obs_t.shape[0] != actions_t.shape[0]:
            raise ValueError("obs and actions batch sizes differ")
        logits, values = self.model(obs_t)
        logp = masked_log_softmax(logits, mask_t).gather(1, actions_t.unsqueeze(1)).squeeze(1)
        entropy = masked_entropy(logits, mask_t)
        return logp, entropy, values

    # -- learning ----------------------------------------------------------
    def update(self, rollout: dict[str, np.ndarray]) -> dict[str, float]:
        """Run PPO epochs over a rollout.

        Required keys (numpy arrays or tensors): ``obs [T,N,obs_size]``,
        ``actions [T,N]``, ``logprobs [T,N]``, ``values [T,N]``,
        ``rewards [T,N]``, ``dones [T,N]``, ``masks [T,N,A]``.  Optional:
        ``last_values [N]`` bootstrap values for truncated final states.
        """
        required = ("obs", "actions", "logprobs", "values", "rewards", "dones", "masks")
        missing = [k for k in required if k not in rollout]
        if missing:
            raise KeyError(f"rollout missing keys: {missing}")

        rewards = _as_numpy(rollout["rewards"], np.float32)
        if rewards.ndim != 2:
            raise ValueError(f"rollout rewards must be [T, N], got {rewards.shape}")
        T, N = rewards.shape
        if T == 0:
            raise ValueError("cannot update from an empty rollout")

        obs = self._rollout_tensor(rollout["obs"], torch.float32).reshape(T * N, self.obs_size)
        actions = self._rollout_tensor(rollout["actions"], torch.long).reshape(T * N)
        old_logp = self._rollout_tensor(rollout["logprobs"], torch.float32).reshape(T * N)
        old_values_np = _as_numpy(rollout["values"], np.float32).reshape(T, N)
        dones = _as_numpy(rollout["dones"], np.float32).reshape(T, N)
        masks = self._rollout_tensor(rollout["masks"], torch.bool).reshape(T, N, self.n_actions)
        masks = masks.reshape(T * N, self.n_actions)
        if obs.shape[0] != T * N:
            raise ValueError("rollout obs shape does not match [T, N, obs_size]")

        last_values = rollout.get("last_values", rollout.get("bootstrap_values"))
        if last_values is not None:
            last_values = _as_numpy(last_values, np.float32).reshape(-1)
            if last_values.size != N:
                raise ValueError(f"last_values must have {N} entries, got {last_values.size}")

        adv_np, ret_np = compute_gae(
            rewards.reshape(T, N),
            old_values_np,
            dones,
            self.config.gamma,
            self.config.gae_lambda,
            last_values=last_values,
        )
        advantages = torch.as_tensor(adv_np.reshape(T * N), dtype=torch.float32, device=self.device)
        returns = torch.as_tensor(ret_np.reshape(T * N), dtype=torch.float32, device=self.device)

        if self.config.normalize_advantage and advantages.numel() > 1:
            advantages = (advantages - advantages.mean()) / (advantages.std(unbiased=False) + 1e-8)

        batch_size = T * N
        minibatch = max(1, min(int(self.config.minibatch_size), batch_size))
        total_updates = max(1, int(self.config.epochs))

        stats: dict[str, float] = {
            "policy_loss": 0.0,
            "value_loss": 0.0,
            "entropy": 0.0,
            "approx_kl": 0.0,
            "clip_fraction": 0.0,
            "loss": 0.0,
            "explained_variance": 0.0,
            "lr": float(self.optimizer.param_groups[0]["lr"]),
            "grad_norm": 0.0,
            "ratio_mean": 0.0,
            "ratio_first_minibatch": 0.0,
            "epochs_run": 0.0,
        }

        var_returns = float(np.var(ret_np))
        if var_returns > 1e-8:
            stats["explained_variance"] = float(
                1.0 - np.var(ret_np - old_values_np) / var_returns
            )
        else:
            stats["explained_variance"] = 0.0

        seen = 0
        first_minibatch_ratio: float | None = None
        kl_accum = 0.0
        clip_accum = 0.0
        entropy_accum = 0.0
        policy_accum = 0.0
        value_accum = 0.0
        loss_accum = 0.0
        grad_accum = 0.0
        ratio_accum = 0.0
        epoch_count = 0
        stop_early = False

        for _epoch in range(total_updates):
            epoch_count += 1
            order = torch.randperm(batch_size, device=self.device)
            epoch_kl = 0.0
            epoch_seen = 0
            for start in range(0, batch_size, minibatch):
                idx = order[start : start + minibatch]
                mb_obs = obs[idx]
                mb_actions = actions[idx]
                mb_masks = masks[idx]
                mb_old_logp = old_logp[idx]
                mb_adv = advantages[idx]
                mb_returns = returns[idx]

                new_logp, entropy, values = self.evaluate_actions(mb_obs, mb_actions, mb_masks)
                log_ratio = new_logp - mb_old_logp
                ratio = log_ratio.exp()
                if first_minibatch_ratio is None:
                    first_minibatch_ratio = float(ratio.detach().mean().item())

                surr1 = ratio * mb_adv
                surr2 = torch.clamp(
                    ratio, 1.0 - self.config.clip_ratio, 1.0 + self.config.clip_ratio
                ) * mb_adv
                policy_loss = -torch.min(surr1, surr2).mean()
                value_loss = 0.5 * ((values - mb_returns) ** 2).mean()
                entropy_mean = entropy.mean()
                loss = (
                    policy_loss
                    + self.config.value_coef * value_loss
                    - self.config.entropy_coef * entropy_mean
                )

                self.optimizer.zero_grad(set_to_none=True)
                loss.backward()
                grad_norm = torch.nn.utils.clip_grad_norm_(
                    self.model.parameters(), float(self.config.max_grad_norm)
                )
                self.optimizer.step()

                weight = float(mb_adv.numel())
                approx_kl = float((0.5 * (log_ratio.detach() ** 2)).mean().item())
                clip_fraction = float(
                    ((ratio.detach() - 1.0).abs() > self.config.clip_ratio).float().mean().item()
                )
                seen += int(weight)
                epoch_seen += int(weight)
                policy_accum += float(policy_loss.detach().item()) * weight
                value_accum += float(value_loss.detach().item()) * weight
                entropy_accum += float(entropy_mean.detach().item()) * weight
                loss_accum += float(loss.detach().item()) * weight
                kl_accum += approx_kl * weight
                clip_accum += clip_fraction * weight
                grad_accum += float(grad_norm) * weight
                ratio_accum += float(ratio.detach().mean().item()) * weight
                epoch_kl += approx_kl * weight

            if epoch_seen > 0:
                stats["epochs_run"] = float(epoch_count)
                if self.config.target_kl is not None and (epoch_kl / epoch_seen) > 1.5 * float(
                    self.config.target_kl
                ):
                    stop_early = True
            if stop_early:
                break

        denom = float(max(1, seen))
        stats["policy_loss"] = policy_accum / denom
        stats["value_loss"] = value_accum / denom
        stats["entropy"] = entropy_accum / denom
        stats["loss"] = loss_accum / denom
        stats["approx_kl"] = kl_accum / denom
        stats["clip_fraction"] = clip_accum / denom
        stats["grad_norm"] = grad_accum / denom
        stats["ratio_mean"] = ratio_accum / denom
        if first_minibatch_ratio is not None:
            stats["ratio_first_minibatch"] = first_minibatch_ratio
        # The first minibatch is evaluated before any gradient step, so it is a
        # direct check that the rollout log-probs match the current policy.
        for key in ("policy_loss", "value_loss", "entropy", "approx_kl", "clip_fraction",
                    "loss", "explained_variance", "lr", "grad_norm", "ratio_mean",
                    "ratio_first_minibatch"):
            value = float(stats[key])
            if not np.isfinite(value):
                stats[key] = 0.0

        self.update_count += 1
        return stats

    def _rollout_tensor(self, value: Any, dtype: torch.dtype) -> Tensor:
        if torch.is_tensor(value):
            return value.detach().to(device=self.device, dtype=dtype)
        return torch.as_tensor(np.asarray(value), dtype=dtype, device=self.device)

    # -- persistence -------------------------------------------------------
    def save(self, path: str | os.PathLike, extra: dict | None = None) -> None:
        path = Path(path)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint: dict[str, Any] = {
            "algorithm": "ppo",
            "obs_size": self.obs_size,
            "n_actions": self.n_actions,
            "config": asdict(self.config),
            "model_state": self.model.state_dict(),
            "optimizer_state": self.optimizer.state_dict(),
            "update_count": self.update_count,
            "obs_version": OBS_VERSION,
            "seed": self.seed,
            "device": str(self.device),
        }
        _merge_extra(checkpoint, extra)
        torch.save(checkpoint, path)

    @classmethod
    def load(cls, path: str | os.PathLike, device: str | None = None) -> "PPOAgent":
        resolved = resolve_device(device)
        try:
            checkpoint = torch.load(path, map_location=resolved, weights_only=False)
        except TypeError:  # pragma: no cover - older torch
            checkpoint = torch.load(path, map_location=resolved)
        raw_config = dict(checkpoint.get("config", {}))
        if "hidden_sizes" not in raw_config and isinstance(raw_config.get("ppo"), dict):
            # Older artifacts saved the full training config under "config".
            raw_config = {**raw_config, **raw_config["ppo"]}
        cfg_values = {
            key: value
            for key, value in raw_config.items()
            if key in {f.name for f in fields(PPOConfig)}
        }
        if "hidden_sizes" in cfg_values:
            cfg_values["hidden_sizes"] = tuple(cfg_values["hidden_sizes"])
        config = PPOConfig(**cfg_values)
        agent = cls(
            int(checkpoint["obs_size"]),
            int(checkpoint.get("n_actions", 80)),
            config=config,
            device=str(resolved),
            seed=int(checkpoint.get("seed", 0)),
        )
        agent.model.load_state_dict(checkpoint["model_state"])
        optimizer_state = checkpoint.get("optimizer_state")
        if optimizer_state:
            agent.optimizer.load_state_dict(optimizer_state)
        agent.update_count = int(checkpoint.get("update_count", 0))
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
