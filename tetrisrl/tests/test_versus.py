"""Versus arena determinism, replay verification, and env integration."""

from __future__ import annotations

import numpy as np
import pytest

from tetrisrl.agents import HeuristicAgent, RandomAgent
from tetrisrl.environment.actions import ACTION_SPACE
from tetrisrl.environment.env import EnvConfig, VersusEnv
from tetrisrl.environment.versus import VersusMatch, replay_actions, verify_replay
from tetrisrl.evaluation.match_replay import load_replay, save_replay, verify_replay_file


def test_versus_is_deterministic():
    def run() -> int:
        m = VersusMatch(RandomAgent(1), RandomAgent(2), seed=99, max_pieces=120, record_frames=False)
        return m.run().final_hashes[0]

    assert run() == run()


def test_replay_verification_roundtrip(tmp_path):
    m = VersusMatch(RandomAgent(3), HeuristicAgent(seed=4), seed=7, max_pieces=80)
    result = m.run()
    assert verify_replay(result.replay)
    path = tmp_path / "replay.json"
    save_replay(result.replay, path)
    assert verify_replay_file(path)
    loaded = load_replay(path)
    assert loaded["seed"] == 7
    assert len(loaded["frames"]) == len(loaded["ticks"])


def test_replay_actions_reproduce_hashes():
    m = VersusMatch(RandomAgent(5), RandomAgent(6), seed=13, max_pieces=60, record_frames=False)
    result = m.run()
    a, b = replay_actions(result.replay["ruleset"], 13, [t["a"]["action"] for t in result.replay["ticks"]], [t["b"]["action"] for t in result.replay["ticks"]], 60)
    assert [a.board.state_hash(), b.board.state_hash()] == list(result.final_hashes)


def test_match_winner_consistent_with_topout():
    m = VersusMatch(HeuristicAgent(seed=1), RandomAgent(2), seed=4, max_pieces=200, record_frames=False)
    result = m.run()
    stats = [s.to_dict() for s in result.stats]
    if result.winner == 0:
        assert stats[1]["top_out_reason"] != ""
    elif result.winner == 1:
        assert stats[0]["top_out_reason"] != ""
    else:
        assert result.reason in ("double_top_out", "max_pieces")


def test_env_reset_step_contract():
    env = VersusEnv("tetrio_s2", opponent=RandomAgent(2), seed=3, config=EnvConfig(max_pieces=20))
    obs, info = env.reset()
    assert obs.shape == (env.observation_size,)
    assert len(info["action_mask"]) == ACTION_SPACE
    assert sum(info["action_mask"]) > 0
    mask = env.action_mask()
    action = next(i for i, ok in enumerate(mask) if ok)
    obs2, reward, terminated, truncated, info2 = env.step(action)
    assert obs2.shape == obs.shape
    assert isinstance(reward, float)
    assert "reward_components" in info2
    comps = info2["reward_components"]
    assert abs(comps["total"] - reward) < 1e-6
    assert sum(1 for v in comps.values() if isinstance(v, float)) > 3


def test_env_solo_mode_terminates_on_topout():
    env = VersusEnv("tetrio_s2", opponent=None, seed=1, config=EnvConfig(max_pieces=2000, solo=True))
    obs, info = env.reset()
    steps = 0
    done = False
    while not done and steps < 3000:
        mask = env.action_mask()
        action = next(i for i, ok in enumerate(mask) if ok)  # always leftmost
        obs, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        steps += 1
    assert done
    assert info["agent_top_out"] is True


def test_dummy_vec_env_autor_resets():
    from tetrisrl.training.vec_env import DummyVecEnv

    def factory():
        return VersusEnv("tetrio_s2", opponent=RandomAgent(9), seed=5, config=EnvConfig(max_pieces=8))

    vec = DummyVecEnv([factory, factory], seeds=[1, 2])
    obs, infos = vec.reset()
    assert obs.shape == (2, vec.observation_size)
    done_steps = 0
    for _ in range(50):
        masks = vec.action_masks()
        assert masks.shape == (2, ACTION_SPACE)
        actions = [int(np.flatnonzero(m)[0]) for m in masks]
        obs, rewards, terms, truncs, infos = vec.step(actions)
        done_steps += int((terms | truncs).sum())
    assert done_steps > 0
    vec.close()


def test_replay_frames_include_piece_colours():
    m = VersusMatch(RandomAgent(3), HeuristicAgent(seed=4), seed=21, max_pieces=50)
    result = m.run()
    frame = result.replay["frames"][-1]["a"]
    assert "colors" in frame
    assert len(frame["colors"]) == 40
    assert all(len(row) == 10 for row in frame["colors"])
    # Painted cells must be consistent with occupancy.
    for y, row in enumerate(frame["colors"]):
        mask = frame["rows"][y]
        for x, ch in enumerate(row):
            occupied = bool(mask >> x & 1)
            assert occupied == (ch != ".")


def test_parallel_round_robin_matches_sequential(tmp_path):
    from tetrisrl.evaluation.tournament import run_round_robin

    participants = [
        {"name": "random", "spec": "random"},
        {"name": "heuristic", "spec": "heuristic"},
    ]
    seq = run_round_robin(participants, n_seeds=2, max_pieces=40, seed=21, replay_dir=tmp_path / "seq", tournament_id="seq", workers=1, record_frames=False)
    par = run_round_robin(participants, n_seeds=2, max_pieces=40, seed=21, replay_dir=tmp_path / "par", tournament_id="par", workers=2, record_frames=False)
    assert [(r["name"], r["wins"], r["losses"]) for r in seq["standings"]] == [
        (r["name"], r["wins"], r["losses"]) for r in par["standings"]
    ]
    assert [m["ticks"] for m in seq["matches"]] == [m["ticks"] for m in par["matches"]]
