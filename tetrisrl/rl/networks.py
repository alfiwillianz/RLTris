"""Neural network building blocks for the RL agents.

All networks are plain PyTorch modules with no environment dependency, so they
can be unit tested (and moved between CPU/GPU) independently of the simulator.
"""

from __future__ import annotations

import math
import warnings
from typing import Iterable, Sequence, Union

import torch
from torch import Tensor, nn

__all__ = ["MLP", "ActorCritic", "QNetwork", "resolve_device", "orthogonal_init_"]

HiddenSizes = Union[Sequence[int], int]

_ACTIVATIONS: dict[str, type[nn.Module]] = {
    "relu": nn.ReLU,
    "tanh": nn.Tanh,
    "gelu": nn.GELU,
    "elu": nn.ELU,
    "silu": nn.SiLU,
    "leaky_relu": nn.LeakyReLU,
}


def _activation_module(name: Union[str, nn.Module]) -> nn.Module:
    if isinstance(name, nn.Module):
        return name
    key = str(name).lower()
    try:
        return _ACTIVATIONS[key]()
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(
            f"unknown activation {name!r}; choose from {sorted(_ACTIVATIONS)}"
        ) from exc


def _as_hidden_sizes(hidden_sizes: HiddenSizes) -> tuple[int, ...]:
    if isinstance(hidden_sizes, int):
        return (int(hidden_sizes),)
    return tuple(int(h) for h in hidden_sizes)


def orthogonal_init_(module: nn.Module, gain: float = math.sqrt(2.0)) -> nn.Module:
    """Apply orthogonal weight init with zero bias to a linear layer."""
    if isinstance(module, nn.Linear):
        nn.init.orthogonal_(module.weight, gain=gain)
        if module.bias is not None:
            nn.init.constant_(module.bias, 0.0)
    return module


class MLP(nn.Module):
    """Fully connected network.

    Parameters
    ----------
    input_size:
        Size of the flat input vector.
    hidden_sizes:
        Hidden layer widths (int or sequence of ints).  ``()`` gives a linear
        model.
    output_size:
        If given, a final linear layer projects to this size; otherwise
        ``forward`` returns the last hidden representation.
    activation:
        Name of the activation (``"tanh"``, ``"relu"``, ``"gelu"``, ...).
    orthogonal_init:
        Orthogonal-initialise every linear layer with the appropriate gain
        (``sqrt(2)`` for hidden layers, ``output_gain`` for the output layer).
    output_gain:
        Gain used for the final layer when ``orthogonal_init=True``.  Small
        values (e.g. ``0.01``) keep the initial policy close to uniform.
    """

    def __init__(
        self,
        input_size: int,
        hidden_sizes: HiddenSizes = (256, 256),
        output_size: int | None = None,
        activation: str = "tanh",
        orthogonal_init: bool = False,
        output_gain: float = 1.0,
    ) -> None:
        super().__init__()
        hidden = _as_hidden_sizes(hidden_sizes)
        layers: list[nn.Module] = []
        last = int(input_size)
        for width in hidden:
            layers.append(nn.Linear(last, width))
            layers.append(_activation_module(activation))
            last = width
        if output_size is not None:
            layers.append(nn.Linear(last, int(output_size)))
            last = int(output_size)
        self.net = nn.Sequential(*layers)
        self.input_size = int(input_size)
        self.output_size = None if output_size is None else int(output_size)
        self.hidden_sizes = hidden

        if orthogonal_init:
            gains = [math.sqrt(2.0)] * len(hidden) + [float(output_gain)]
            linear_layers = [m for m in self.net if isinstance(m, nn.Linear)]
            for layer, gain in zip(linear_layers, gains):
                orthogonal_init_(layer, gain=gain)

    def forward(self, x: Tensor) -> Tensor:
        return self.net(x)


class ActorCritic(nn.Module):
    """Separate actor and critic trunks (no shared features).

    Separate trunks are used deliberately: value gradients cannot distort the
    policy representation, which matters for the small batch sizes typical in
    this project.
    """

    def __init__(
        self,
        obs_size: int,
        n_actions: int = 80,
        hidden_sizes: HiddenSizes = (256, 256),
        activation: str = "tanh",
    ) -> None:
        super().__init__()
        self.obs_size = int(obs_size)
        self.n_actions = int(n_actions)
        self.actor = MLP(
            obs_size,
            hidden_sizes,
            output_size=n_actions,
            activation=activation,
            orthogonal_init=True,
            output_gain=0.01,
        )
        self.critic = MLP(
            obs_size,
            hidden_sizes,
            output_size=1,
            activation=activation,
            orthogonal_init=True,
            output_gain=1.0,
        )

    def forward(self, obs: Tensor) -> tuple[Tensor, Tensor]:
        """Return ``(logits [B, A], value [B])``."""
        logits = self.actor(obs)
        value = self.critic(obs).squeeze(-1)
        return logits, value


class QNetwork(nn.Module):
    """Q-value network ``obs -> q_values [B, A]``."""

    def __init__(
        self,
        obs_size: int,
        n_actions: int = 80,
        hidden_sizes: HiddenSizes = (256, 256),
        activation: str = "tanh",
    ) -> None:
        super().__init__()
        self.obs_size = int(obs_size)
        self.n_actions = int(n_actions)
        self.net = MLP(
            obs_size,
            hidden_sizes,
            output_size=n_actions,
            activation=activation,
            orthogonal_init=True,
            output_gain=1.0,
        )

    def forward(self, obs: Tensor) -> Tensor:
        return self.net(obs)


def resolve_device(device: str | torch.device | None) -> torch.device:
    """Resolve ``None``/``"auto"`` to CUDA when available, else CPU.

    Explicit ``"cuda"``/``"mps"`` requests fall back to CPU with a warning when
    the backend is unavailable, so training scripts stay portable.  Invalid
    device strings raise ``ValueError``.
    """
    if device is None or (isinstance(device, str) and device.lower() in ("auto", "")):
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")

    resolved = device if isinstance(device, torch.device) else torch.device(device)

    if resolved.type == "cuda":
        if not torch.cuda.is_available():
            warnings.warn(
                "CUDA requested but not available; falling back to CPU",
                RuntimeWarning,
                stacklevel=2,
            )
            return torch.device("cpu")
        if resolved.index is not None and resolved.index >= torch.cuda.device_count():
            warnings.warn(
                f"cuda:{resolved.index} requested but only "
                f"{torch.cuda.device_count()} device(s) visible; using cuda:0",
                RuntimeWarning,
                stacklevel=2,
            )
            return torch.device("cuda:0")
    elif resolved.type == "mps":
        if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            warnings.warn(
                "MPS requested but not available; falling back to CPU",
                RuntimeWarning,
                stacklevel=2,
            )
            return torch.device("cpu")
    return resolved


def count_parameters(module: Iterable[nn.Parameter] | nn.Module) -> int:
    """Small convenience for logging model size."""
    params = module.parameters() if isinstance(module, nn.Module) else module
    return sum(p.numel() for p in params)
