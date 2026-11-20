"""Pretraining: winner-only demo collection and masked behaviour cloning."""

from __future__ import annotations

import numpy as np

from tetrisrl.config import TrainConfig, ppo_kwargs
from tetrisrl.environment.observation import ObservationEncoder
from tetrisrl.rl.ppo.agent import PPOAgent, PPOConfig
from tetrisrl.training.pretrain import _bc_train, _collect_demos, _pretrain_opts


def _config(**pretrain):
    cfg = TrainConfig(algorithm="ppo", mode="pretrain", seed=2, max_pieces=24, ruleset="tetrio_s2")
    cfg.pretrain = {
        "epochs": 1,
        "matches_per_epoch": 1,
        "bc_epochs": 1,
        "batch_size": 32,
        "opponents": ["random", "heuristic"],
        "max_pieces": 24,
        **pretrain,
    }
    return cfg


def test_pretrain_config_mode_roundtrip(tmp_path):
    cfg = TrainConfig(algorithm="dqn", mode="pretrain", pretrain={"epochs": 3})
    path = tmp_path / "cfg.json"
    cfg.save(path)
    loaded = TrainConfig.load(path)
    assert loaded.mode == "pretrain"
    assert loaded.pretrain["epochs"] == 3


def test_collect_demos_only_winner_and_legal_actions(tmp_path):
    cfg = _config()
    encoder = ObservationEncoder(include_opponent=True, preview=5, max_pieces=24)

    class FakeCtx:
        def make_encoder(self):
            return encoder

    obs, actions, masks, stats = _collect_demos(cfg, FakeCtx(), encoder, epoch=0)
    assert stats["matches"] == 1
    assert len(obs) == len(actions) == len(masks)
    assert len(obs) > 0
    for index, action in enumerate(actions):
        assert masks[index][action], "winner action must be legal in its recorded state"
    assert obs[0].shape == (encoder.size,)


def test_bc_update_is_finite_and_uses_masks():
    encoder = ObservationEncoder(include_opponent=True, preview=5, max_pieces=24)
    agent = PPOAgent(encoder.size, 80, PPOConfig(**ppo_kwargs(TrainConfig())), device="cpu", seed=0)
    rng = np.random.default_rng(0)
    obs = rng.normal(size=(16, encoder.size)).astype(np.float32)
    masks = np.zeros((16, 80), dtype=bool)
    actions = np.zeros(16, dtype=np.int64)
    for i in range(16):
        legal = rng.choice(80, size=4, replace=False)
        masks[i, legal] = True
        actions[i] = int(legal[0])
    metrics = _bc_train(agent, list(obs), list(actions), list(masks), {"bc_epochs": 1, "batch_size": 8, "lr": 1e-3})
    assert np.isfinite(metrics["pretrain/loss"])
    assert metrics["pretrain/updates"] >= 1
