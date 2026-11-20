"""Vectorised environments for PPO training.

Two implementations share the same interface:

``DummyVecEnv``
    Steps ``n`` environments sequentially in-process (simple, deterministic,
    easy to debug).
``SubprocVecEnv``
    One worker process per environment, communicating over pipes.  Real
    parallelism for CPU-bound simulation; used for long runs.

Both expose::

    obs, infos = env.reset(seeds=None)
    obs, rewards, terminated, truncated, infos = env.step(actions)
    env.action_masks() -> np.ndarray [n_envs, 80] bool
"""

from __future__ import annotations

import multiprocessing as mp
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np


class VecEnv:
    num_envs: int
    observation_size: int
    action_space_size: int = 80

    def reset(self, seeds: Optional[Sequence[int]] = None):  # pragma: no cover - interface
        raise NotImplementedError

    def step(self, actions: Sequence[int]):  # pragma: no cover - interface
        raise NotImplementedError

    def action_masks(self) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        return None


class DummyVecEnv(VecEnv):
    def __init__(self, env_fns: List[Callable[[], Any]], seeds: Optional[Sequence[int]] = None) -> None:
        self.envs = [fn() for fn in env_fns]
        self.num_envs = len(self.envs)
        self.observation_size = self.envs[0].observation_size
        self._masks = np.zeros((self.num_envs, self.action_space_size), dtype=bool)
        self._seeds = list(seeds) if seeds is not None else [i for i in range(self.num_envs)]

    def reset(self, seeds: Optional[Sequence[int]] = None):
        if seeds is not None:
            self._seeds = list(seeds)
        obs_list, infos = [], []
        for env, seed in zip(self.envs, self._seeds):
            obs, info = env.reset(seed=seed)
            obs_list.append(obs)
            infos.append(info)
        self._update_masks()
        return np.stack(obs_list), infos

    def _update_masks(self) -> None:
        for i, env in enumerate(self.envs):
            self._masks[i] = np.asarray(env.action_mask(), dtype=bool)

    def action_masks(self) -> np.ndarray:
        self._update_masks()
        return self._masks

    def step(self, actions: Sequence[int]):
        obs_list, rewards, terms, truncs, infos = [], [], [], [], []
        for i, (env, action) in enumerate(zip(self.envs, actions)):
            obs, reward, terminated, truncated, info = env.step(int(action))
            if terminated or truncated:
                # Gym-style auto-reset: keep the terminal observation for
                # bootstrapping, then start a new episode.
                info["final_observation"] = obs
                info["final_action_mask"] = env.action_mask()
                self._seeds[i] = (self._seeds[i] + 7919) & 0x7FFFFFFF
                obs, _ = env.reset(seed=self._seeds[i])
            obs_list.append(obs)
            rewards.append(reward)
            terms.append(terminated)
            truncs.append(truncated)
            infos.append(info)
        self._update_masks()
        return np.stack(obs_list), np.asarray(rewards, dtype=np.float32), np.asarray(terms, dtype=bool), np.asarray(truncs, dtype=bool), infos

    def close(self) -> None:
        for env in self.envs:
            env.close()


def _worker(conn, env_fn, seed: int) -> None:  # pragma: no cover - exercised indirectly
    try:
        env = env_fn()
        obs, info = env.reset(seed=seed)
        conn.send(("reset_ok", obs, info))
        while True:
            msg = conn.recv()
            if msg[0] == "step":
                obs, reward, terminated, truncated, info = env.step(int(msg[1]))
                if terminated or truncated:
                    info["final_observation"] = obs
                    info["final_action_mask"] = env.action_mask()
                    obs, _ = env.reset()
                conn.send(("step_ok", obs, reward, terminated, truncated, info))
            elif msg[0] == "mask":
                conn.send(("mask_ok", env.action_mask()))
            elif msg[0] == "reset":
                obs, info = env.reset(seed=msg[1])
                conn.send(("reset_ok", obs, info))
            elif msg[0] == "close":
                env.close()
                conn.send(("closed",))
                break
    except Exception as exc:  # pragma: no cover
        try:
            conn.send(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            conn.close()


class SubprocVecEnv(VecEnv):
    def __init__(self, env_fns: List[Callable[[], Any]], seeds: Optional[Sequence[int]] = None) -> None:
        self.ctx = mp.get_context("fork")
        self.num_envs = len(env_fns)
        self._seeds = list(seeds) if seeds is not None else [i for i in range(self.num_envs)]
        self.parents: List[Any] = []
        self.workers: List[Any] = []
        self._masks = np.zeros((self.num_envs, self.action_space_size), dtype=bool)
        # Instantiate one env locally to learn the observation size, then close it.
        probe = env_fns[0]()
        self.observation_size = probe.observation_size
        probe.close()
        for i, fn in enumerate(env_fns):
            parent, child = self.ctx.Pipe()
            proc = self.ctx.Process(target=_worker, args=(child, fn, self._seeds[i]), daemon=True)
            proc.start()
            self.parents.append(parent)
            self.workers.append(proc)
            kind, obs, info = parent.recv()
            if kind != "reset_ok":
                raise RuntimeError(f"worker failed to start: {obs}")

    def reset(self, seeds: Optional[Sequence[int]] = None):
        if seeds is not None:
            self._seeds = list(seeds)
        obs_list, infos = [], []
        for i, parent in enumerate(self.parents):
            parent.send(("reset", self._seeds[i]))
            kind, obs, info = parent.recv()
            if kind != "reset_ok":
                raise RuntimeError(f"worker reset failed: {obs}")
            obs_list.append(obs)
            infos.append(info)
        self._update_masks()
        return np.stack(obs_list), infos

    def _update_masks(self) -> None:
        for i, parent in enumerate(self.parents):
            parent.send(("mask",))
            kind, mask = parent.recv()
            if kind != "mask_ok":
                raise RuntimeError(f"worker mask failed: {mask}")
            self._masks[i] = np.asarray(mask, dtype=bool)

    def action_masks(self) -> np.ndarray:
        self._update_masks()
        return self._masks

    def step(self, actions: Sequence[int]):
        for parent, action in zip(self.parents, actions):
            parent.send(("step", int(action)))
        obs_list, rewards, terms, truncs, infos = [], [], [], [], []
        for parent in self.parents:
            kind, obs, reward, terminated, truncated, info = parent.recv()
            if kind != "step_ok":
                raise RuntimeError(f"worker step failed: {obs}")
            obs_list.append(obs)
            rewards.append(reward)
            terms.append(terminated)
            truncs.append(truncated)
            infos.append(info)
        self._update_masks()
        return np.stack(obs_list), np.asarray(rewards, dtype=np.float32), np.asarray(terms, dtype=bool), np.asarray(truncs, dtype=bool), infos

    def close(self) -> None:
        for parent, proc in zip(self.parents, self.workers):
            try:
                parent.send(("close",))
                proc.join(timeout=2.0)
            except Exception:
                pass
            if proc.is_alive():
                proc.terminate()


def make_vec_env(
    env_fn: Callable[[], Any],
    n_envs: int,
    seed: int,
    kind: str = "dummy",
    seeds: Optional[Sequence[int]] = None,
) -> VecEnv:
    if seeds is None:
        seeds = [seed + 7919 * i for i in range(n_envs)]
    fns = [env_fn for _ in range(n_envs)]
    if kind == "subprocess":
        return SubprocVecEnv(fns, seeds=seeds)
    return DummyVecEnv(fns, seeds=seeds)
