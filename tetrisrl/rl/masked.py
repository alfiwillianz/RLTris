"""Masked categorical utilities shared by PPO and Double DQN.

The action space contains 80 placements but only a small subset is legal in any
given state.  Every distribution used by the learners is therefore built from a
:class:`torch.Tensor` of logits and a boolean ``mask`` of shape ``[B, A]`` where
``True`` means *legal*.

Semantics
---------
* Illegal actions receive probability **exactly** ``0.0``.
* Log-probabilities of illegal actions are set to ``torch.finfo(dtype).min``
  (a large finite negative number) rather than ``-inf`` so that downstream
  arithmetic such as ``p * log p`` and backpropagation cannot produce NaNs.
* A row with a single legal action yields a deterministic distribution with
  entropy ``0`` and log-probability ``0`` for that action.
* A completely empty row (no legal action) is a contract violation from the
  environment, but it is handled gracefully by treating every action as legal
  for that row (uniform distribution).  Callers still see a well-defined,
  finite distribution instead of NaNs.
"""

from __future__ import annotations

from typing import Tuple

import torch
from torch import Tensor
from torch.distributions import Categorical

__all__ = [
    "masked_log_softmax",
    "masked_softmax",
    "masked_entropy",
    "masked_categorical",
    "masked_argmax",
]


def _prepare(logits: Tensor, mask: Tensor) -> Tuple[Tensor, Tensor]:
    """Validate inputs, align devices/dtypes, and repair empty mask rows."""
    if not torch.is_tensor(logits):
        logits = torch.as_tensor(logits)
    if not torch.is_tensor(mask):
        mask = torch.as_tensor(mask)
    if logits.dim() != 2:
        raise ValueError(f"logits must be 2-D [B, A], got shape {tuple(logits.shape)}")
    if mask.shape != logits.shape:
        raise ValueError(
            f"mask shape {tuple(mask.shape)} does not match logits shape {tuple(logits.shape)}"
        )
    if not logits.is_floating_point():
        logits = logits.float()
    mask = mask.to(device=logits.device, dtype=torch.bool)

    empty = ~mask.any(dim=-1)
    if bool(empty.any()):
        # Never emit NaN rows.  The environment guarantees at least one legal
        # placement, so this only triggers for malformed / synthetic input.
        mask = mask.clone()
        mask[empty] = True
    return logits, mask


def masked_log_softmax(logits: Tensor, mask: Tensor) -> Tensor:
    """Log-softmax restricted to legal actions (``mask`` bool ``[B, A]``)."""
    logits, mask = _prepare(logits, mask)
    neg = torch.finfo(logits.dtype).min
    return torch.log_softmax(logits.masked_fill(~mask, neg), dim=-1)


def masked_softmax(logits: Tensor, mask: Tensor) -> Tensor:
    """Categorical probabilities with exactly ``0`` on illegal actions."""
    return masked_log_softmax(logits, mask).exp()


def masked_entropy(logits: Tensor, mask: Tensor) -> Tensor:
    """Entropy ``H[p]`` of the *masked* distribution, shape ``[B]``.

    Illegal actions contribute exactly zero because their probability is zero.
    """
    logp = masked_log_softmax(logits, mask)
    probs = logp.exp()
    entropy = -(probs * logp).sum(dim=-1)
    # Numerical round-off can leave a ~ -1e-8 value (or -0.0) for a
    # deterministic distribution; force a clean non-negative value so a single
    # legal action reports exactly 0.
    return torch.where(entropy <= 0.0, torch.zeros_like(entropy), entropy)


def masked_categorical(logits: Tensor, mask: Tensor) -> Categorical:
    """Masked :class:`~torch.distributions.Categorical`.

    ``dist.probs`` is exactly zero for illegal actions, so sampling can never
    select one.
    """
    probs = masked_softmax(logits, mask)
    return Categorical(probs=probs)


def masked_argmax(q_values: Tensor, mask: Tensor) -> Tensor:
    """Greedy action over legal actions only, shape ``[B]`` (int64)."""
    q_values, mask = _prepare(q_values, mask)
    neg = torch.finfo(q_values.dtype).min
    return q_values.masked_fill(~mask, neg).argmax(dim=-1)
