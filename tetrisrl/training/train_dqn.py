"""Double DQN training loop (shared by the CLI and the dashboard)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np

from ..config import TrainConfig, dqn_kwargs
from ..rl.dqn.agent import DQNAgent, DQNConfig
from .curriculum import Stage, stages_from_config
from .trainer import RunContext
from .vec_env import make_vec_env


def train_dqn(cfg: TrainConfig, ctx: RunContext, agent: Optional[DQNAgent] = None) -> None:
    ctx.start()
    encoder = ctx.make_encoder()
    stages: List[Stage] = stages_from_config(cfg)
    state = ctx.load_training_state() if ctx.resume_checkpoint else {"step": 0, "stage_index": 0, "stage_step": 0}
    if agent is None:
        agent = DQNAgent(
            obs_size=encoder.size,
            n_actions=80,
            config=DQNConfig(**dqn_kwargs(cfg)),
            device=None if cfg.device in ("auto", "") else cfg.device,
            seed=cfg.seed,
        )
    elif encoder.size != agent.obs_size:
        raise ValueError(f"checkpoint obs size {agent.obs_size} != encoder size {encoder.size}")

    print(f"[dqn] obs_size={encoder.size} device={agent.device_used} stages={[s.name for s in stages]}", flush=True)

    step = int(state["step"])
    stage_index = int(state["stage_index"])
    stage_step = int(state["stage_step"])
    remaining_total = max(0, cfg.timesteps - step)
    last_eval_step = step - (step % max(1, cfg.eval_interval))
    stats: Dict[str, Any] = {
        "episode_rewards": [], "episode_lengths": [], "lines": [], "attack": [],
        "heights": [], "holes": [], "wins": [], "components": {},
    }
    ep_rewards = np.zeros(cfg.n_envs)
    ep_lengths = np.zeros(cfg.n_envs, dtype=np.int64)
    update_metrics: Dict[str, float] = {}

    while stage_index < len(stages) and remaining_total > 0 and not ctx.stop_requested:
        stage = stages[stage_index]
        stage_steps_budget = int(stage.timesteps) - stage_step
        if stage_steps_budget <= 0:
            stage_index += 1
            stage_step = 0
            continue
        envs = make_vec_env(
            lambda stage=stage: ctx.make_env(stage, seed=cfg.seed + stage_step),
            n_envs=cfg.n_envs,
            seed=cfg.seed + step,
            kind=cfg.vec_env,
        )
        obs, _ = envs.reset(seeds=[cfg.seed + step + i for i in range(cfg.n_envs)])
        steps_this_stage = 0
        t0 = time.time()
        try:
            while steps_this_stage < stage_steps_budget and remaining_total > 0 and not ctx.stop_requested:
                masks = envs.action_masks()
                actions = [agent.act(obs[i], masks[i], step=step) for i in range(cfg.n_envs)]
                next_obs, rewards, terminated, truncated, infos = envs.step(actions)
                next_masks = envs.action_masks()
                for i in range(cfg.n_envs):
                    done = bool(terminated[i] or truncated[i])
                    agent.observe(obs[i], actions[i], float(rewards[i]), next_obs[i], done, next_masks[i], env_id=i)
                    ep_rewards[i] += rewards[i]
                    ep_lengths[i] += 1
                    if done:
                        info = infos[i]
                        stats["episode_rewards"].append(float(ep_rewards[i]))
                        stats["episode_lengths"].append(int(ep_lengths[i]))
                        stats["lines"].append(float(info.get("total_lines", 0)))
                        stats["attack"].append(float(info.get("total_attack", 0)))
                        stats["heights"].append(float(info.get("max_height", 0)))
                        stats["holes"].append(float(info.get("holes", 0)))
                        won = info.get("won")
                        if won is not None:
                            stats["wins"].append(1.0 if won else 0.0)
                        for k, v in info.get("reward_components", {}).items():
                            stats.setdefault("components", {}).setdefault(k, []).append(float(v))
                        ep_rewards[i] = 0.0
                        ep_lengths[i] = 0
                obs = next_obs
                step += cfg.n_envs
                steps_this_stage += cfg.n_envs
                stage_step += cfg.n_envs
                remaining_total = max(0, remaining_total - cfg.n_envs)

                if step >= max(cfg.learning_starts, agent.config.learning_starts) and step % max(1, agent.config.train_freq) < cfg.n_envs:
                    result = agent.update(step)
                    if result:
                        update_metrics = {f"train/{k}": v for k, v in result.items()}

                metrics: Dict[str, float] = dict(update_metrics)
                metrics["train/epsilon"] = agent.epsilon_for_step(step)
                metrics["train/learning_rate"] = float(agent.optimizer.param_groups[0]["lr"])
                metrics["train/buffer_size"] = float(len(agent.buffer))
                metrics["throughput/steps_per_sec"] = (cfg.n_envs) / max(1e-9, time.time() - t0)
                metrics.update(_episode_metrics(stats))
                for key in ("episode_rewards", "episode_lengths", "lines", "attack", "heights", "holes", "wins"):
                    if len(stats[key]) > 2000:
                        stats[key] = stats[key][-1000:]
                for key in stats["components"]:
                    if len(stats["components"][key]) > 500:
                        stats["components"][key] = stats["components"][key][-250:]

                if step - last_eval_step >= cfg.eval_interval:
                    metrics.update(ctx.evaluate(agent, step))
                    last_eval_step = step
                    ctx.save(agent, step, metrics, tag="eval")
                if step % max(1, cfg.checkpoint_interval) < cfg.n_envs:
                    ctx.save(agent, step, metrics, tag="step")
                ctx.save_training_state(step, stage_index, stage_step)
                ctx.log(step, metrics)
                if step % max(1, cfg.log_interval) < cfg.n_envs:
                    print(
                        f"[{ctx.run_id}] step {step:,} | stage={stage.name} "
                        f"rew={metrics.get('train/episode_reward', float('nan')):.2f} "
                        f"eps={metrics['train/epsilon']:.3f} lines={metrics.get('train/lines', 0):.1f}",
                        flush=True,
                    )
                t0 = time.time()
        finally:
            envs.close()
        if not ctx.stop_requested and remaining_total > 0:
            stage_index += 1
            stage_step = 0

    final_metrics = ctx.evaluate(agent, step, matches=max(8, cfg.eval_matches // 2))
    ctx.save(agent, step, final_metrics, tag="final")
    ctx.save_training_state(step, stage_index, stage_step)
    ctx.log(step, final_metrics)
    ctx.finish("stopped" if ctx.stop_requested else "completed")


def _episode_metrics(stats: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if stats["episode_rewards"]:
        out["train/episode_reward"] = float(np.mean(stats["episode_rewards"]))
        out["train/episode_reward_last100"] = float(np.mean(stats["episode_rewards"][-100:]))
    if stats["episode_lengths"]:
        out["train/episode_length"] = float(np.mean(stats["episode_lengths"]))
    for key, name in (("lines", "train/lines"), ("attack", "train/attack"), ("heights", "train/avg_height"), ("holes", "train/holes")):
        if stats[key]:
            out[name] = float(np.mean(stats[key]))
    if stats["wins"]:
        out["train/win_rate"] = float(np.mean(stats["wins"]))
    for key, values in stats.get("components", {}).items():
        if values:
            out[f"reward/{key}"] = float(np.mean(values))
    return out
