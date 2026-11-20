"""Run entry point used by ``python -m tetrisrl train`` and the dashboard."""

from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Optional

from ..config import TrainConfig
from .experiment_manager import ExperimentManager
from .trainer import RunContext


def run_training(
    config: TrainConfig,
    run_id: str,
    manager: Optional[ExperimentManager] = None,
    resume_checkpoint: Optional[str] = None,
    notes: str = "",
) -> RunContext:
    manager = manager or ExperimentManager()
    ctx = RunContext(config, run_id, manager=manager, resume_checkpoint=resume_checkpoint)
    if notes:
        manager.update_run(run_id, notes=notes)
    ctx.install_signal_handlers()
    try:
        agent = None
        if resume_checkpoint:
            from .checkpoints import load_agent

            if not Path(resume_checkpoint).exists():
                raise FileNotFoundError(f"checkpoint not found: {resume_checkpoint}")
            agent = load_agent(resume_checkpoint, device=None if config.device in ("auto", "") else config.device)
        if getattr(config, "mode", "rl") == "pretrain":
            from .pretrain import train_pretrain

            train_pretrain(config, ctx, agent)
        elif config.algorithm == "ppo":
            from .train_ppo import train_ppo

            train_ppo(config, ctx, agent)
        elif config.algorithm == "dqn":
            from .train_dqn import train_dqn

            train_dqn(config, ctx, agent)
        else:
            raise ValueError(f"unknown algorithm {config.algorithm!r}; expected 'ppo' or 'dqn'")
    except Exception as exc:  # keep the run record useful after a crash
        error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        ctx.fail(error)
        raise
    finally:
        ctx.restore_signal_handlers()
    return ctx


def launch_cli_training(args) -> int:
    """Helper used by the CLI."""
    manager = ExperimentManager(args.db)
    config = TrainConfig.from_dict({})
    if args.config:
        config = TrainConfig.load(args.config)
    if args.algorithm:
        config.algorithm = args.algorithm
    if args.seed is not None:
        config.seed = args.seed
    if args.timesteps is not None:
        config.timesteps = args.timesteps
    if args.n_envs is not None:
        config.n_envs = args.n_envs
    if args.vec_env:
        config.vec_env = args.vec_env
    if args.stage:
        config.stage = args.stage
    if args.include_opponent is not None:
        config.include_opponent = args.include_opponent
    if args.max_pieces is not None:
        config.max_pieces = args.max_pieces
    run_id = args.run_id
    if run_id is None:
        run = manager.create_run(config.algorithm, config.to_dict(), seed=config.seed, notes=args.notes or "")
        run_id = run["id"]
    else:
        if manager.get_run(run_id) is None:
            manager.create_run(
                config.algorithm, config.to_dict(), seed=config.seed, run_id=run_id, notes=args.notes or ""
            )
        else:
            manager.update_run(run_id, config_json=__import__("json").dumps(config.to_dict()), seed=config.seed)
    config.save(Path(f"results/runs/{run_id}") / "config.json")
    run_training(config, run_id, manager=manager, resume_checkpoint=args.resume, notes=args.notes or "")
    return 0
