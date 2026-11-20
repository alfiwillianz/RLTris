"""Checkpoint helpers.

Checkpoints are self-describing: algorithm, observation schema, configuration,
curriculum position, optimizer state, and evaluation metrics.  The best
checkpoint is never overwritten (each improvement gets its own step-named file).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def checkpoint_path(run_dir: str | Path, step: int, tag: str = "step") -> Path:
    return Path(run_dir) / "checkpoints" / f"{tag}_{int(step):09d}.pt"


def save_checkpoint(
    agent: Any,
    run_dir: str | Path,
    step: int,
    *,
    algorithm: str,
    config: Dict[str, Any],
    observation: Dict[str, Any],
    metrics: Optional[Dict[str, Any]] = None,
    tag: str = "step",
) -> Path:
    path = checkpoint_path(run_dir, step, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = {
        "algorithm": algorithm,
        "step": int(step),
        "config": config,
        "observation": observation,
        "metrics": metrics or {},
    }
    agent.save(str(path), extra=extra)
    return path


def load_checkpoint_metadata(path: str | Path) -> Dict[str, Any]:
    import torch

    ckpt = torch.load(str(path), map_location="cpu", weights_only=False)
    return {
        "algorithm": ckpt.get("algorithm"),
        "step": ckpt.get("step"),
        "config": ckpt.get("config", {}),
        "observation": ckpt.get("observation", {}),
        "metrics": ckpt.get("metrics", {}),
        "extra": ckpt.get("extra", {}),
    }


def load_agent(path: str | Path, device: Optional[str] = None) -> Any:
    import torch

    ckpt = torch.load(str(path), map_location="cpu", weights_only=False)
    algorithm = ckpt.get("algorithm")
    if algorithm == "dqn":
        from ..rl.dqn.agent import DQNAgent

        return DQNAgent.load(str(path), device=device)
    from ..rl.ppo.agent import PPOAgent

    return PPOAgent.load(str(path), device=device)
