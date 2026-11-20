"""Baseline agents, rewards, configuration, and experiment persistence."""

from __future__ import annotations

import numpy as np
import pytest

from tetrisrl.agents import BeamSearchAgent, HeuristicAgent, RandomAgent, make_agent
from tetrisrl.agents.heuristic_agent import board_features, simulate
from tetrisrl.config import TrainConfig
from tetrisrl.environment.engine import GameState
from tetrisrl.environment.rewards import RewardConfig, board_metrics, compute_reward
from tetrisrl.environment.ruleset import tetrio_s2_ruleset
from tetrisrl.evaluation.evaluator import evaluate_agent
from tetrisrl.evaluation.statistical_analysis import mean_ci, paired_mean_difference, wilson_interval
from tetrisrl.training.experiment_manager import ExperimentManager


@pytest.mark.parametrize("agent_factory", [lambda: RandomAgent(1), lambda: HeuristicAgent(seed=1), lambda: BeamSearchAgent(depth=2, beam_width=4)])
def test_agents_only_choose_legal_actions(agent_factory):
    agent = agent_factory()
    agent.reset(0)
    state = GameState(seed=2)
    for _ in range(40):
        action = agent.choose_action(state, None)
        assert action in state.legal_actions(), action
        state.apply_action(action)
        if state.finished:
            break


def test_heuristic_beats_random_over_paired_seeds():
    result = evaluate_agent(lambda: HeuristicAgent(seed=11), "random", n_matches=8, seed=100, max_pieces=200)
    summary = result["summary"]
    assert summary["matches"] == 8
    assert summary["win_rate"] >= 0.5, summary
    assert 0.0 <= summary["win_rate_ci_low"] <= summary["win_rate_ci_high"] <= 1.0


def test_search_beats_random():
    result = evaluate_agent(lambda: BeamSearchAgent(depth=1, beam_width=3, seed=2), "random", n_matches=6, seed=7, max_pieces=120)
    assert result["summary"]["win_rate"] >= 0.5


def test_make_agent_factory():
    assert make_agent("random").name == "random"
    assert make_agent("heuristic").name == "heuristic"
    assert make_agent("search").name == "search"
    with pytest.raises(ValueError):
        make_agent("does-not-exist")


def test_reward_components_sum_to_total():
    cfg = RewardConfig()
    state = GameState(seed=1)
    before = board_metrics(state)
    action = next(i for i, ok in enumerate(state.action_mask()) if ok)
    result = state.apply_action(action)
    after = board_metrics(state)
    total, comps = compute_reward(cfg, before, after, result)
    assert abs(sum(v for k, v in comps.items() if k != "total") - total) < 1e-6


def test_reward_terminal_win_and_loss():
    cfg = RewardConfig()
    m = board_metrics(GameState(seed=1))
    _, win = compute_reward(cfg, m, m, None, terminal=True, won=True)
    _, loss = compute_reward(cfg, m, m, None, terminal=True, won=False)
    assert win["terminal"] == cfg.terminal_win
    assert loss["terminal"] == cfg.terminal_loss
    assert win["terminal"] > loss["terminal"]


def test_reward_config_from_dict_ignores_unknown():
    cfg = RewardConfig.from_dict({"per_line": 2.5, "nonsense": 1})
    assert cfg.per_line == 2.5
    assert not hasattr(cfg, "nonsense")


def test_board_features_sane():
    state = GameState(seed=1)
    board, cleared, eroded, perfect = simulate(state.board, ((4, 39),), state.ruleset)
    feats = board_features(board)
    assert feats["holes"] >= 0
    assert feats["max_height"] >= 1


def test_statistics_helpers():
    lo, hi = wilson_interval(5, 10)
    assert 0 <= lo < 0.5 < hi <= 1
    assert wilson_interval(0, 0) == (0.0, 1.0)
    mean, lo, hi = mean_ci([1.0, 2.0, 3.0])
    assert mean == 2.0 and lo < mean < hi
    diff = paired_mean_difference([1, 2, 3], [0, 1, 1])
    assert diff["n"] == 3
    assert diff["mean_diff"] == pytest.approx(4 / 3)


def test_train_config_stage_scaling():
    cfg = TrainConfig(timesteps=1000)
    plan = cfg.scaled_stage_plan()
    assert sum(s["timesteps"] for s in plan) == 1000
    assert len(plan) == len(cfg.curriculum)
    cfg.stage = "stage2_random"
    assert [s["name"] for s in cfg.scaled_stage_plan()] == ["stage2_random"]


def test_train_config_roundtrip(tmp_path):
    cfg = TrainConfig(algorithm="dqn", timesteps=1234, dqn={"lr": 1e-3}, reward={"per_line": 2.0})
    path = tmp_path / "cfg.json"
    cfg.save(path)
    loaded = TrainConfig.load(path)
    assert loaded.algorithm == "dqn"
    assert loaded.timesteps == 1234
    assert loaded.dqn["lr"] == 1e-3


def test_experiment_manager_persistence(tmp_path):
    db = tmp_path / "exp.sqlite3"
    m = ExperimentManager(str(db))
    run = m.create_run("ppo", {"x": 1}, seed=3, name="test run")
    rid = run["id"]
    m.set_status(rid, "running")
    m.log_metrics(rid, 10, {"train/loss": 0.5, "eval/win_rate": 0.25})
    m.log_metrics(rid, 20, {"train/loss": 0.25})
    ckpt = m.add_checkpoint(rid, "results/ckpt.pt", 20, mean_reward=1.0, win_rate=0.25)
    metrics = m.get_metrics(rid)
    assert metrics["train/loss"] == [(10, 0.5), (20, 0.25)]
    assert m.list_metric_names(rid)
    assert [c["id"] for c in m.list_checkpoints(rid)] == [ckpt]
    m.update_run(rid, best_checkpoint="results/ckpt.pt")
    over = m.overview()
    assert over["total_runs"] == 1
    assert over["active_runs"] == 1
    # A new manager instance sees the same data (persistence, not memory).
    m2 = ExperimentManager(str(db))
    assert m2.get_run(rid)["algorithm"] == "ppo"
    assert m2.overview()["total_timesteps"] == 20


def test_variant_opponent_is_legal_and_seeded():
    from tetrisrl.agents.variants import VariantOpponent, sample_variant, build_variant
    import random

    rng = random.Random(4)
    specs = [sample_variant(rng) for _ in range(8)]
    assert len({s.kind for s in specs}) >= 1
    assert len({(s.depth, s.beam_width, round(s.attack_weight, 3)) for s in specs}) > 1

    a = VariantOpponent(seed=9)
    b = VariantOpponent(seed=9)
    a.reset(11)
    b.reset(11)
    assert a.current_spec == b.current_spec

    variant = VariantOpponent(seed=2)
    variant.reset(5)
    state = GameState(seed=6)
    for _ in range(25):
        action = variant.choose_action(state, None)
        assert action in state.legal_actions()
        state.apply_action(action)
        if state.finished:
            break

    spec = sample_variant(random.Random(1))
    built = build_variant(spec, seed=3)
    built.reset(3)
    state = GameState(seed=9)
    assert built.choose_action(state, None) in state.legal_actions()
