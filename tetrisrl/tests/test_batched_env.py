"""Batched versus environment: shapes, masks, determinism, auto-reset."""

from __future__ import annotations

import numpy as np

from tetrisrl.environment.observation import ObservationEncoder
from tetrisrl.training.batched_env import BatchedVersusEnv


def test_batched_env_shapes_and_masks():
    env = BatchedVersusEnv(n_envs=16, seed=3, max_pieces=40)
    obs, infos = env.reset()
    assert obs.shape == (16, env.observation_size)
    assert env.observation_size == ObservationEncoder(include_opponent=True).size
    masks = env.action_masks()
    assert masks.shape == (16, 80)
    assert masks.any(axis=1).all()
    actions = np.argmax(masks, axis=1)
    obs2, rewards, terminated, truncated, infos = env.step(actions)
    assert obs2.shape == obs.shape
    assert rewards.shape == (16,)
    assert np.isfinite(rewards).all()
    assert terminated.dtype == bool and truncated.dtype == bool
    assert all("final_observation" in info for info in infos)


def test_batched_env_deterministic():
    def rollout(seed: int):
        env = BatchedVersusEnv(n_envs=8, seed=seed, max_pieces=30)
        obs, _ = env.reset()
        out = [obs.copy()]
        for _ in range(30):
            actions = np.argmax(env.action_masks(), axis=1)
            obs, rewards, term, trunc, infos = env.step(actions)
            out.append(obs.copy())
        return np.stack(out)

    assert np.array_equal(rollout(5), rollout(5))


def test_batched_env_auto_reset():
    env = BatchedVersusEnv(n_envs=8, seed=4, max_pieces=5)
    env.reset()
    done = False
    for _ in range(20):
        actions = np.argmax(env.action_masks(), axis=1)
        obs, rewards, term, trunc, infos = env.step(actions)
        if term.any() or trunc.any():
            done = True
    assert done
    # After auto-reset, every board has legal actions again.
    assert env.action_masks().any(axis=1).all()
