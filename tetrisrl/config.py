"""Training configuration and YAML/JSON loading.

A single :class:`TrainConfig` is shared by PPO and Double DQN.  Algorithm
hyperparameters live in ``ppo``/``dqn`` sub-dicts that map directly onto the
agent config dataclasses, and curriculum/evaluation settings live at the top
level so experiments are reproducible from one file.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # PyYAML is optional; JSON configs always work.
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


DEFAULT_CURRICULUM: List[Dict[str, Any]] = [
    {
        "name": "stage1_survival",
        "timesteps": 100_000,
        "opponent": "none",
        "max_pieces": 200,
        "pressure_interval": 0,
        "pressure_lines": 0,
    },
    {
        "name": "stage2_random",
        "timesteps": 200_000,
        "opponent": "random",
        "max_pieces": 300,
    },
    {
        "name": "stage3_heuristic",
        "timesteps": 300_000,
        "opponent": "heuristic",
        "max_pieces": 400,
    },
    {
        "name": "stage4_pressure",
        "timesteps": 200_000,
        "opponent": "heuristic",
        "max_pieces": 400,
        "pressure_interval": 40,
        "pressure_lines": 2,
    },
    {
        "name": "stage5_mixed",
        "timesteps": 300_000,
        "opponent": "mixed",
        "opponents": ["random", "heuristic", "search"],
        "max_pieces": 500,
    },
]


@dataclass
class TrainConfig:
    algorithm: str = "ppo"
    seed: int = 0
    timesteps: int = 600_000
    n_envs: int = 8
    vec_env: str = "dummy"  # dummy | subprocess
    max_pieces: int = 300
    preview: int = 5
    include_opponent: bool = True
    ruleset: str = "tetrio_s2"
    notes: str = ""
    device: str = "auto"

    #: Reward weights (see RewardConfig).
    reward: Dict[str, Any] = field(default_factory=dict)

    #: Algorithm hyperparameters (see PPOConfig / DQNConfig).
    ppo: Dict[str, Any] = field(default_factory=dict)
    dqn: Dict[str, Any] = field(default_factory=dict)

    #: Rollout length per environment per PPO update.
    rollout_steps: int = 256
    #: Total environment transitions per DQN training step schedule.
    learning_starts: int = 2_000

    eval_interval: int = 50_000
    eval_matches: int = 24
    eval_opponents: List[str] = field(default_factory=lambda: ["random", "heuristic"])
    checkpoint_interval: int = 50_000
    log_interval: int = 2_000
    curriculum: List[Dict[str, Any]] = field(default_factory=lambda: [dict(s) for s in DEFAULT_CURRICULUM])
    #: Optional override: run a single stage (empty = full curriculum).
    stage: str = ""
    #: Extra per-run metadata copied into the DB.
    tags: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TrainConfig":
        if not data:
            return cls()
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    @classmethod
    def load(cls, path: str | Path) -> "TrainConfig":
        path = Path(path)
        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("PyYAML is required to read YAML configs")
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text)
        return cls.from_dict(data)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        if path.suffix in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("PyYAML is required to write YAML configs")
            path.write_text(yaml.safe_dump(data, sort_keys=False))
        else:
            path.write_text(json.dumps(data, indent=2))

    def stage_plan(self) -> List[Dict[str, Any]]:
        if self.stage:
            matches = [s for s in self.curriculum if s.get("name") == self.stage]
            if not matches:
                raise ValueError(f"stage {self.stage!r} not found in curriculum")
            return matches
        return self.curriculum

    def scaled_stage_plan(self) -> List[Dict[str, Any]]:
        """Scale stage timesteps so they sum to ``timesteps``."""
        plan = [dict(s) for s in self.stage_plan()]
        total = sum(int(s.get("timesteps", 0)) for s in plan)
        if total <= 0:
            per = self.timesteps // max(1, len(plan))
            for s in plan:
                s["timesteps"] = per
            return plan
        factor = self.timesteps / total
        for s in plan:
            s["timesteps"] = max(1, int(int(s.get("timesteps", 0)) * factor))
        # Fix rounding drift on the final stage.
        drift = self.timesteps - sum(int(s["timesteps"]) for s in plan)
        plan[-1]["timesteps"] = int(plan[-1]["timesteps"]) + drift
        return plan


def ppo_kwargs(config: TrainConfig) -> Dict[str, Any]:
    base = {
        "lr": 3e-4,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_ratio": 0.2,
        "value_coef": 0.5,
        "entropy_coef": 0.01,
        "max_grad_norm": 0.5,
        "epochs": 4,
        "minibatch_size": 256,
        "hidden_sizes": (256, 256),
        "normalize_advantage": True,
    }
    base.update(config.ppo)
    if isinstance(base.get("hidden_sizes"), list):
        base["hidden_sizes"] = tuple(base["hidden_sizes"])
    return base


def dqn_kwargs(config: TrainConfig) -> Dict[str, Any]:
    base = {
        "lr": 1e-4,
        "gamma": 0.99,
        "epsilon_start": 1.0,
        "epsilon_end": 0.02,
        "epsilon_decay_steps": 150_000,
        "batch_size": 256,
        "buffer_size": 200_000,
        "target_sync_steps": 2_000,
        "huber_delta": 1.0,
        "max_grad_norm": 10.0,
        "hidden_sizes": (256, 256),
        "double": True,
        "learning_starts": 2_000,
        "train_freq": 1,
    }
    base.update(config.dqn)
    if isinstance(base.get("hidden_sizes"), list):
        base["hidden_sizes"] = tuple(base["hidden_sizes"])
    return base
