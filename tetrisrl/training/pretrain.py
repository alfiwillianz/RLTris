"""Behaviour-cloning pretraining from tournament demonstrations.

Mode ``pretrain`` does not train PPO/DQN with environment rewards.  Each epoch:

1. runs a mini round robin between the chosen *opponents* (external engines or
   in-repo baselines), with seeds derived from ``(run seed, epoch, match)`` so
   every epoch collects fresh games;
2. replays each finished match and keeps the **winning side's** (observation,
   action, mask) triples - losses and draws contribute nothing;
3. trains the policy network with masked cross-entropy for a few passes.

Checkpoints are saved per epoch and can be used by a later ``continue`` run.
The dashboard shows epochs instead of timesteps for these runs.
"""

from __future__ import annotations

import itertools
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..agents import make_agent
from ..environment.engine import GameState
from ..environment.ruleset import load_ruleset
from ..environment.versus import VersusMatch, derive_seeds
from ..rl.dqn.agent import DQNAgent
from ..rl.masked import masked_log_softmax
from ..rl.ppo.agent import PPOAgent
from .trainer import RunContext
from .curriculum import Stage


def _pretrain_opts(cfg) -> Dict[str, Any]:
    data = dict(cfg.pretrain or {})
    data.setdefault("epochs", 10)
    if "matches_per_pair" not in data:
        # Backwards compatibility: an explicit matches_per_epoch is spread
        # evenly over the pairings; otherwise default to 2 per pair.
        data["matches_per_pair"] = 0 if data.get("matches_per_epoch") else 2
    data.setdefault("matches_per_epoch", 0)
    data.setdefault("bc_epochs", 2)
    data.setdefault("batch_size", 256)
    data.setdefault("lr", 3e-4)
    data.setdefault("opponents", ["heuristic", "random"])
    data.setdefault("eval_every", 5)
    data.setdefault("max_pieces", cfg.max_pieces)
    return data


def _pair(specs: List[str], index: int) -> Tuple[str, str]:
    if len(specs) == 1:
        return specs[0], specs[0]
    combos = list(itertools.combinations(range(len(specs)), 2))
    ia, ib = combos[index % len(combos)]
    return specs[ia], specs[ib]


def _collect_demos(
    cfg,
    ctx: RunContext,
    encoder,
    epoch: int,
) -> Tuple[List[np.ndarray], List[int], List[np.ndarray], Dict[str, float]]:
    opts = _pretrain_opts(cfg)
    specs = list(opts["opponents"])
    pairs = list(itertools.combinations(specs, 2)) or [(specs[0], specs[0])]
    per_pair = int(opts.get("matches_per_pair") or 0)
    if per_pair <= 0:  # backwards compatibility with matches_per_epoch
        per_pair = max(1, math.ceil(int(opts.get("matches_per_epoch") or len(pairs) * 2) / len(pairs)))
    max_pieces = int(opts["max_pieces"])
    ruleset = load_ruleset(cfg.ruleset)
    observations: List[np.ndarray] = []
    actions: List[int] = []
    masks: List[np.ndarray] = []
    stats = {"matches": 0, "draws": 0, "wins": 0, "pieces": 0}

    match_index = 0
    for pair_index, (spec_a, spec_b) in enumerate(pairs):
        for repeat in range(per_pair):
            i = pair_index * per_pair + repeat
            match_index += 1
            seed = (cfg.seed * 1_000_003 + epoch * 10_007 + i * 97) & 0x7FFFFFFF
            match = VersusMatch(
                make_agent(spec_a, seed=seed),
                make_agent(spec_b, seed=seed + 1),
                ruleset=ruleset,
                seed=seed,
                max_pieces=max_pieces,
                record_frames=False,
                record_events=True,
            )
            result = match.run()
            stats["matches"] += 1
            if result.winner is None:
                stats["draws"] += 1
                continue
            winner = result.winner
            stats["wins"] += 1
            stats["pieces"] += result.ticks
            side = "a" if winner == 0 else "b"
            ticks = result.replay["ticks"]
            sa, sb, ga, gb = derive_seeds(seed)
            state_a = GameState(ruleset, seed=sa, garbage_seed=ga, player_id=0, max_pieces=max_pieces)
            state_b = GameState(ruleset, seed=sb, garbage_seed=gb, player_id=1, max_pieces=max_pieces)
            for tick in ticks:
                own = state_a if side == "a" else state_b
                other = state_b if side == "a" else state_a
                action = int(tick[side].get("action", -1))
                if action >= 0 and not own.finished:
                    observations.append(encoder.encode(own, other))
                    masks.append(np.asarray(own.action_mask(), dtype=bool))
                    actions.append(action)
                res_a = state_a.apply_action(int(tick["a"]["action"]))
                res_b = state_b.apply_action(int(tick["b"]["action"]))
                if res_a.sent > 0:
                    state_b.receive_attack(res_a.sent)
                if res_b.sent > 0:
                    state_a.receive_attack(res_b.sent)
                if state_a.finished or state_b.finished:
                    break
    return observations, actions, masks, stats


def _bc_train(agent, observations: List[np.ndarray], actions: List[int], masks: List[np.ndarray], opts: Dict[str, Any]):
    import torch

    obs = np.asarray(observations, dtype=np.float32)
    act = np.asarray(actions, dtype=np.int64)
    mask = np.asarray(masks, dtype=bool)
    if len(obs) == 0:
        return {}
    batch_size = max(1, int(opts["batch_size"]))
    passes = max(1, int(opts["bc_epochs"]))
    steps = passes * math.ceil(len(obs) / batch_size)
    rng = np.random.default_rng(1234)
    opt = agent.optimizer
    opt.param_groups[0]["lr"] = float(opts["lr"])
    losses = []
    agent.train()
    obs_t = torch.as_tensor(obs, device=agent.device).view(len(obs), -1)
    act_t = torch.as_tensor(act, device=agent.device)
    mask_t = torch.as_tensor(mask, device=agent.device)
    for _ in range(steps):
        idx = rng.integers(0, len(obs), size=min(batch_size, len(obs)))
        b_obs = obs_t[idx]
        b_act = act_t[idx]
        b_mask = mask_t[idx]
        logits = agent.model(b_obs)[0] if isinstance(agent, PPOAgent) else agent.online_net(b_obs)
        logp = masked_log_softmax(logits, b_mask)
        loss = -logp.gather(1, b_act.unsqueeze(1)).squeeze(1).mean()
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(agent.model.parameters() if isinstance(agent, PPOAgent) else agent.online_net.parameters(), 5.0)
        opt.step()
        losses.append(float(loss.item()))
    agent.eval()
    return {"pretrain/loss": float(np.mean(losses)) if losses else 0.0, "pretrain/updates": float(steps)}


def train_pretrain(cfg, ctx: RunContext, agent=None) -> None:
    ctx.start()
    encoder = ctx.make_encoder()
    opts = _pretrain_opts(cfg)
    if agent is None:
        if cfg.algorithm == "dqn":
            from ..config import dqn_kwargs
            from ..rl.dqn.agent import DQNConfig

            agent = DQNAgent(encoder.size, 80, DQNConfig(**dqn_kwargs(cfg)), device=None if cfg.device in ("auto", "") else cfg.device, seed=cfg.seed)
        else:
            from ..config import ppo_kwargs
            from ..rl.ppo.agent import PPOConfig

            agent = PPOAgent(encoder.size, 80, PPOConfig(**ppo_kwargs(cfg)), device=None if cfg.device in ("auto", "") else cfg.device, seed=cfg.seed)
    state = ctx.load_training_state() if ctx.resume_checkpoint else {"step": 0}
    start_epoch = int(state.get("step", 0))
    epochs = int(opts["epochs"])
    print(f"[pretrain] {cfg.algorithm} epochs={epochs} matches/pair/epoch={opts['matches_per_pair']} opponents={opts['opponents']}", flush=True)

    for epoch_index in range(start_epoch, epochs):
        if ctx.stop_requested:
            break
        epoch = epoch_index  # zero-based internally, one-based in the UI/logs
        step = epoch + 1
        t0 = time.time()
        obs, actions, masks, stats = _collect_demos(cfg, ctx, encoder, epoch)
        bc = _bc_train(agent, obs, actions, masks, opts)
        metrics: Dict[str, float] = {
            "pretrain/epoch": float(step),
            "pretrain/dataset": float(len(obs)),
            "pretrain/matches": float(stats["matches"]),
            "pretrain/draws": float(stats["draws"]),
            "pretrain/pieces": float(stats["pieces"]),
            "pretrain/collect_seconds": float(time.time() - t0),
            "train/learning_rate": float(opts["lr"]),
        }
        metrics.update(bc)
        if step % max(1, int(opts["eval_every"])) == 0 or step == epochs:
            metrics.update(ctx.evaluate(agent, step, matches=max(8, cfg.eval_matches // 2)))
        ctx.save(agent, step, metrics, tag="pretrain")
        ctx.save_training_state(step, 0, 0)
        ctx.log(step, metrics, f"epoch={step}/{epochs} dataset={len(obs)}")
    ctx.finish("stopped" if ctx.stop_requested else "completed")
