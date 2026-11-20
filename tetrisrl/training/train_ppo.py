"""PPO training loop (shared by the CLI and the dashboard).

The loop materialises the curriculum stage by stage, collects rollouts from
vectorised environments, runs the masked PPO update, evaluates, and persists
metrics/checkpoints after every configured interval.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np

from ..config import TrainConfig, ppo_kwargs
from ..environment.observation import ObservationEncoder
from ..rl.ppo.agent import PPOAgent, PPOConfig
from .curriculum import Stage, stages_from_config
from .trainer import RunContext
from .vec_env import make_vec_env


def _unwrap(value: Any) -> Any:
    return value


def _act_batch(agent: PPOAgent, obs: np.ndarray, masks: np.ndarray):
    """Vectorised policy evaluation for all environments at once."""
    import torch
    from ..rl.masked import masked_categorical, masked_log_softmax

    obs_t = torch.as_tensor(obs, dtype=torch.float32, device=agent.device)
    mask_t = torch.as_tensor(masks, dtype=torch.bool, device=agent.device)
    with torch.no_grad():
        logits, values = agent.model(obs_t)
        actions = masked_categorical(logits, mask_t).sample()
        logp = masked_log_softmax(logits, mask_t).gather(1, actions.unsqueeze(1)).squeeze(1)
    return (
        actions.cpu().numpy().astype(np.int64),
        logp.cpu().numpy().astype(np.float32),
        values.reshape(-1).cpu().numpy().astype(np.float32),
    )


def collect_rollout(envs, agent: PPOAgent, obs: np.ndarray, rollout_steps: int, gamma: float, ctx: RunContext, stats: Dict[str, Any]):
    n_envs = envs.num_envs
    obs_size = envs.observation_size
    obs_buf = np.zeros((rollout_steps, n_envs, obs_size), dtype=np.float32)
    actions_buf = np.zeros((rollout_steps, n_envs), dtype=np.int64)
    logp_buf = np.zeros((rollout_steps, n_envs), dtype=np.float32)
    values_buf = np.zeros((rollout_steps, n_envs), dtype=np.float32)
    rewards_buf = np.zeros((rollout_steps, n_envs), dtype=np.float32)
    dones_buf = np.zeros((rollout_steps, n_envs), dtype=np.float32)
    masks_buf = np.zeros((rollout_steps, n_envs, agent.n_actions), dtype=bool)

    ep_rewards = np.zeros(n_envs, dtype=np.float64)
    ep_lengths = np.zeros(n_envs, dtype=np.int64)

    for t in range(rollout_steps):
        masks = envs.action_masks()
        actions = np.zeros(n_envs, dtype=np.int64)
        logps = np.zeros(n_envs, dtype=np.float32)
        values = np.zeros(n_envs, dtype=np.float32)
        actions, logps, values = _act_batch(agent, obs, masks)
        next_obs, rewards, terminated, truncated, infos = envs.step(actions)

        # Bootstrap truncated episodes (time limit) with V(s_{t+1}).
        if truncated.any():
            for i in range(n_envs):
                if truncated[i] and not terminated[i]:
                    final_obs = infos[i].get("final_observation", next_obs[i])
                    final_mask = infos[i].get("final_action_mask")
                    if final_mask is None:
                        final_mask = envs.action_masks()[i]
                    _, _, v_next = agent.act(final_obs, final_mask, deterministic=True)
                    rewards[i] += gamma * v_next

        obs_buf[t] = obs
        actions_buf[t] = actions
        logp_buf[t] = logps
        values_buf[t] = values
        rewards_buf[t] = rewards
        # The truncation bootstrap is added to the reward above, so the step
        # must also be marked terminal; otherwise GAE would bootstrap twice
        # (once via the reward bump, once via values[t+1] from the reset env).
        dones_buf[t] = (terminated | truncated).astype(np.float32)
        masks_buf[t] = masks

        ep_rewards += rewards
        ep_lengths += 1
        for i in range(n_envs):
            info = infos[i]
            if terminated[i] or truncated[i]:
                ctx.manager  # keep ctx referenced
                stats["episode_rewards"].append(float(ep_rewards[i]))
                stats["episode_lengths"].append(int(ep_lengths[i]))
                stats["lines"].append(float(info.get("total_lines", 0)))
                stats["attack"].append(float(info.get("total_attack", 0)))
                stats["heights"].append(float(info.get("max_height", 0)))
                stats["holes"].append(float(info.get("holes", 0)))
                won = info.get("won")
                if won is not None:
                    stats["wins"].append(1.0 if won else 0.0)
                comp = info.get("reward_components", {})
                for key, val in comp.items():
                    stats.setdefault("components", {}).setdefault(key, []).append(float(val))
                ep_rewards[i] = 0.0
                ep_lengths[i] = 0
        obs = next_obs

    last_values = np.zeros(n_envs, dtype=np.float32)
    masks = envs.action_masks()
    for i in range(n_envs):
        _, _, v = agent.act(obs[i], masks[i], deterministic=True)
        last_values[i] = v

    rollout = {
        "obs": obs_buf,
        "actions": actions_buf,
        "logprobs": logp_buf,
        "values": values_buf,
        "rewards": rewards_buf,
        "dones": dones_buf,
        "masks": masks_buf,
        "last_values": last_values,
    }
    return rollout, obs


def _rollout_metrics(stats: Dict[str, Any]) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    if stats["episode_rewards"]:
        metrics["train/episode_reward"] = float(np.mean(stats["episode_rewards"]))
        metrics["train/episode_reward_last100"] = float(np.mean(stats["episode_rewards"][-100:]))
    if stats["episode_lengths"]:
        metrics["train/episode_length"] = float(np.mean(stats["episode_lengths"]))
    for key, name in (("lines", "train/lines"), ("attack", "train/attack"), ("heights", "train/avg_height"), ("holes", "train/holes")):
        if stats[key]:
            metrics[name] = float(np.mean(stats[key]))
    if stats["wins"]:
        metrics["train/win_rate"] = float(np.mean(stats["wins"]))
    if stats.get("components"):
        for key, values in stats["components"].items():
            if values:
                metrics[f"reward/{key}"] = float(np.mean(values))
    return metrics


def train_ppo(cfg: TrainConfig, ctx: RunContext, agent: Optional[PPOAgent] = None) -> None:
    ctx.start()
    encoder = ctx.make_encoder()
    stages: List[Stage] = stages_from_config(cfg)
    state = ctx.load_training_state() if ctx.resume_checkpoint else {"step": 0, "stage_index": 0, "stage_step": 0}
    if agent is None:
        agent = PPOAgent(
            obs_size=encoder.size,
            n_actions=80,
            config=PPOConfig(**ppo_kwargs(cfg)),
            device=None if cfg.device in ("auto", "") else cfg.device,
            seed=cfg.seed,
        )
    elif encoder.size != agent.obs_size:
        raise ValueError(f"checkpoint obs size {agent.obs_size} != encoder size {encoder.size}")

    print(f"[ppo] obs_size={encoder.size} device={agent.device_used} stages={[s.name for s in stages]}", flush=True)

    step = int(state["step"])
    stage_index = int(state["stage_index"])
    stage_step = int(state["stage_step"])
    remaining_total = max(0, cfg.timesteps - step)
    steps_per_update = cfg.rollout_steps * cfg.n_envs
    last_eval_step = step - (step % max(1, cfg.eval_interval))
    stats: Dict[str, Any] = {
        "episode_rewards": [], "episode_lengths": [], "lines": [], "attack": [],
        "heights": [], "holes": [], "wins": [], "components": {},
    }
    update_count = 0

    while stage_index < len(stages) and remaining_total > 0 and not ctx.stop_requested:
        stage = stages[stage_index]
        stage_steps_budget = int(stage.timesteps) - stage_step
        if stage_steps_budget <= 0:
            stage_index += 1
            stage_step = 0
            continue

        if cfg.vec_env == "batched":
            from .batched_env import BatchedVersusEnv

            envs = BatchedVersusEnv(
                n_envs=cfg.n_envs,
                seed=cfg.seed + step,
                max_pieces=stage.max_pieces,
                reward_config=ctx.reward_config(stage),
                include_opponent=cfg.include_opponent,
            )
            obs, _ = envs.reset()
            print(
                f"[ppo] batched backend: {cfg.n_envs} boards/step (random opponent; "
                "spin/garbage-delay simplifications documented)",
                flush=True,
            )
        else:
            envs = make_vec_env(
                lambda stage=stage: ctx.make_env(stage, seed=cfg.seed + stage_step),
                n_envs=cfg.n_envs,
                seed=cfg.seed + step,
                kind=cfg.vec_env,
            )
            obs, _ = envs.reset(seeds=[cfg.seed + step + i for i in range(cfg.n_envs)])
        t0 = time.time()
        steps_this_stage = 0
        try:
            while steps_this_stage < stage_steps_budget and remaining_total > 0 and not ctx.stop_requested:
                actual_rollout = min(cfg.rollout_steps, max(1, remaining_total // cfg.n_envs))
                rollout, obs = collect_rollout(envs, agent, obs, actual_rollout, cfg.ppo.get("gamma", 0.99), ctx, stats)
                update_metrics = agent.update(rollout)
                steps_done = actual_rollout * cfg.n_envs
                step += steps_done
                steps_this_stage += steps_done
                stage_step += steps_done
                remaining_total = max(0, remaining_total - steps_done)
                update_count += 1

                metrics = {f"train/{k}": v for k, v in update_metrics.items()}
                metrics["train/learning_rate"] = float(agent.optimizer.param_groups[0]["lr"])
                throughput = steps_done / max(1e-9, time.time() - t0)
                metrics["throughput/steps_per_sec"] = throughput
                metrics.update(_rollout_metrics(stats))
                # Keep windows bounded so memory stays flat over long runs.
                for key in ("episode_rewards", "episode_lengths", "lines", "attack", "heights", "holes", "wins"):
                    if len(stats[key]) > 2000:
                        stats[key] = stats[key][-1000:]
                for key in stats["components"]:
                    if len(stats["components"][key]) > 500:
                        stats["components"][key] = stats["components"][key][-250:]

                if step - last_eval_step >= cfg.eval_interval:
                    eval_metrics = ctx.evaluate(agent, step)
                    metrics.update(eval_metrics)
                    last_eval_step = step
                    ctx.save(agent, step, metrics, tag="eval")
                if step % max(1, cfg.checkpoint_interval) < steps_done:
                    ctx.save(agent, step, metrics, tag="step")
                ctx.save_training_state(step, stage_index, stage_step)
                ctx.log(step, metrics)
                if step % max(1, cfg.log_interval) < steps_done:
                    eprint = (
                        f"stage={stage.name} ep_rew={metrics.get('train/episode_reward', float('nan')):.2f} "
                        f"lines={metrics.get('train/lines', 0):.1f} win={metrics.get('train/win_rate', float('nan')):.2f} "
                        f"loss={metrics.get('train/loss', float('nan')):.3f}"
                    )
                    print(f"[{ctx.run_id}] step {step:,} | {eprint} | {throughput:,.0f} steps/s", flush=True)
                t0 = time.time()
        finally:
            if hasattr(envs, "close"):
                envs.close()
        if not ctx.stop_requested and remaining_total > 0:
            stage_index += 1
            stage_step = 0

    # Final checkpoint and evaluation regardless of where we stopped.
    final_metrics = ctx.evaluate(agent, step, matches=max(8, cfg.eval_matches // 2))
    ctx.save(agent, step, final_metrics, tag="final")
    ctx.save_training_state(step, stage_index, stage_step)
    ctx.log(step, final_metrics)
    ctx.finish("stopped" if ctx.stop_requested else "completed")
