"""Tests for the RL agents (masked distributions, PPO, Double DQN, replay).

Run with::

    .venv/bin/python -m pytest tetrisrl/tests/test_rl.py -q

These tests use tiny synthetic rollouts instead of the real environment so the
suite stays fast (< ~60 s) and independent of game-mechanics changes.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import torch

from tetrisrl.environment.observation import ObservationEncoder
from tetrisrl.rl.dqn.agent import DQNAgent, DQNConfig
from tetrisrl.rl.dqn.replay import ReplayBuffer
from tetrisrl.rl.masked import (
    masked_argmax,
    masked_categorical,
    masked_entropy,
    masked_log_softmax,
    masked_softmax,
)
from tetrisrl.rl.networks import ActorCritic, MLP, QNetwork, resolve_device
from tetrisrl.rl.ppo.agent import PPOAgent, PPOConfig, compute_gae

DEVICES = ["cpu"] + (["cuda"] if torch.cuda.is_available() else [])


# ---------------------------------------------------------------------------
# Masked distribution utilities
# ---------------------------------------------------------------------------
def test_masked_probability_mass_and_zero_invalid():
    torch.manual_seed(0)
    logits = torch.randn(5, 7)
    mask = torch.zeros(5, 7, dtype=torch.bool)
    mask[0, 0] = True
    mask[1, 1:3] = True
    mask[2, :] = True
    mask[3, 6] = True
    mask[4, 2:6] = False
    mask[4, 0] = True

    probs = masked_softmax(logits, mask)
    logp = masked_log_softmax(logits, mask)

    assert torch.allclose(probs.sum(dim=-1), torch.ones(5), atol=1e-6)
    assert torch.equal(probs[~mask], torch.zeros(int((~mask).sum())))
    assert torch.all(torch.isfinite(logp[mask]))
    assert torch.allclose(logp.exp(), probs, atol=1e-6)

    # The masked distribution equals a softmax over valid logits only.
    for row in range(5):
        valid = torch.nonzero(mask[row]).squeeze(-1)
        expected = torch.softmax(logits[row, valid], dim=-1)
        assert torch.allclose(probs[row, valid], expected, atol=1e-6)


def test_masked_entropy_matches_distribution():
    torch.manual_seed(1)
    logits = torch.randn(4, 6)
    mask = torch.tensor(
        [
            [True, False, True, False, False, False],
            [True, True, True, True, True, True],
            [False, False, False, False, False, True],
            [False, True, False, True, False, False],
        ]
    )
    probs = masked_softmax(logits, mask)
    logp = masked_log_softmax(logits, mask)
    expected = -(probs * torch.where(mask, logp, torch.zeros_like(logp))).sum(dim=-1)
    entropy = masked_entropy(logits, mask)

    assert entropy.shape == (4,)
    assert torch.allclose(entropy, expected, atol=1e-6)
    assert torch.all(entropy >= 0)
    assert torch.isfinite(entropy).all()
    # Deterministic rows (one legal action) have exactly zero entropy.
    assert entropy[2].item() == 0.0
    # Full-mask rows are bounded by log(A).
    assert entropy[1].item() <= math.log(6) + 1e-6


def test_masked_single_valid_action_no_nan_and_categorical():
    logits = torch.tensor([[1.0, -5.0, 3.0, 0.0]], dtype=torch.float32)
    mask = torch.tensor([[False, False, True, False]])
    probs = masked_softmax(logits, mask)
    dist = masked_categorical(logits, mask)

    assert probs[0, 2].item() == 1.0
    assert torch.equal(probs[0, ~mask[0]], torch.zeros(3))
    assert torch.equal(dist.probs, probs)
    assert masked_entropy(logits, mask).item() == 0.0
    assert torch.isfinite(masked_log_softmax(logits, mask)).all()
    for _ in range(20):
        assert dist.sample().item() == 2

    # Log-probabilities are consistent with the sampled action.
    action = dist.sample()
    gathered = masked_log_softmax(logits, mask)[0, action].item()
    assert gathered == pytest.approx(0.0, abs=1e-6)
    assert dist.log_prob(action).item() == pytest.approx(0.0, abs=1e-6)


def test_masked_categorical_never_samples_invalid():
    torch.manual_seed(3)
    logits = torch.randn(3, 10)
    mask = torch.zeros(3, 10, dtype=torch.bool)
    mask[0, [1, 4]] = True
    mask[1, :] = True
    mask[2, [9]] = True
    dist = masked_categorical(logits, mask)
    samples = dist.sample((500,))
    for row in range(3):
        assert mask[row][samples[:, row]].all()
        assert torch.equal(dist.probs[row, ~mask[row]], torch.zeros(int((~mask[row]).sum())))


def test_masked_argmax_ignores_invalid_actions():
    q = torch.tensor([[1.0, 1e6, 5.0, 2.0], [9.0, 8.0, 7.0, 6.0]])
    mask = torch.tensor(
        [[True, False, True, False], [False, False, False, True]]
    )
    actions = masked_argmax(q, mask)
    assert actions.tolist() == [2, 3]

    # An entirely empty mask row is repaired (uniform distribution) rather
    # than producing NaNs - the environment contract forbids this case.
    empty = torch.zeros(1, 4, dtype=torch.bool)
    assert torch.isfinite(masked_softmax(q[:1], empty)).all()
    assert masked_softmax(q[:1], empty).sum().item() == pytest.approx(1.0)


def test_masked_gradients_are_finite():
    torch.manual_seed(4)
    logits = torch.randn(3, 6, requires_grad=True)
    mask = torch.zeros(3, 6, dtype=torch.bool)
    mask[0, 0] = True
    mask[1, [0, 2, 4]] = True
    mask[2, :] = True
    logp = masked_log_softmax(logits, mask)
    probs = masked_softmax(logits, mask)
    loss = -(logp * probs.detach()).sum()
    loss.backward()
    assert logits.grad is not None
    assert torch.isfinite(logits.grad).all()
    invalid_grad = logits.grad[~mask]
    assert torch.allclose(invalid_grad, torch.zeros_like(invalid_grad), atol=1e-8)


# ---------------------------------------------------------------------------
# Generalized Advantage Estimation
# ---------------------------------------------------------------------------
def test_gae_terminal_hand_computed():
    rewards = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    values = np.array([0.5, 1.0, 1.5], dtype=np.float32)
    dones = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    adv, ret = compute_gae(rewards, values, dones, gamma=0.9, lam=0.8)
    # deltas = [1.4, 1.0, 1.5]; the terminal at t=1 blocks the bootstrap.
    np.testing.assert_allclose(adv, [2.12, 1.0, 1.5], atol=1e-6)
    np.testing.assert_allclose(ret, [2.62, 2.0, 3.0], atol=1e-6)


def test_gae_truncated_hand_computed():
    rewards = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    values = np.array([0.5, 1.0, 1.5], dtype=np.float32)
    dones = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    # Time-limit truncation at the final step bootstraps with V(s_T) = 2.0.
    adv, ret = compute_gae(rewards, values, dones, gamma=0.9, lam=0.8, last_values=2.0)
    np.testing.assert_allclose(adv, [4.80272, 4.726, 3.3], atol=1e-5)
    np.testing.assert_allclose(ret, [5.30272, 5.726, 4.8], atol=1e-5)

    # Without a bootstrap value the final step is a hard boundary.
    adv0, _ = compute_gae(rewards, values, dones, gamma=0.9, lam=0.8)
    assert adv0[2] == pytest.approx(1.5, abs=1e-6)

    # Supplying values with an explicit T+1 bootstrap row is equivalent.
    values_with_bootstrap = np.concatenate(
        [values, np.array([2.0], dtype=np.float32)]
    )
    adv_ext, ret_ext = compute_gae(
        rewards, values_with_bootstrap, dones, gamma=0.9, lam=0.8
    )
    np.testing.assert_allclose(adv_ext, adv, atol=1e-5)
    np.testing.assert_allclose(ret_ext, ret, atol=1e-5)


def test_gae_batched_matches_single_environment():
    rng = np.random.default_rng(0)
    rewards = rng.standard_normal((5, 3)).astype(np.float32)
    values = rng.standard_normal((5, 3)).astype(np.float32)
    dones = (rng.random((5, 3)) < 0.15).astype(np.float32)
    last_values = rng.standard_normal(3).astype(np.float32)

    adv_b, ret_b = compute_gae(rewards, values, dones, 0.97, 0.9, last_values=last_values)
    assert adv_b.shape == rewards.shape
    assert ret_b.shape == rewards.shape
    for column in range(3):
        adv_1, ret_1 = compute_gae(
            rewards[:, column],
            values[:, column],
            dones[:, column],
            0.97,
            0.9,
            last_values=last_values[column],
        )
        np.testing.assert_allclose(adv_b[:, column], adv_1, atol=1e-6)
        np.testing.assert_allclose(ret_b[:, column], ret_1, atol=1e-6)
    np.testing.assert_allclose(ret_b, adv_b + values, atol=1e-6)


# ---------------------------------------------------------------------------
# PPO
# ---------------------------------------------------------------------------
def _collect_rollout(agent: PPOAgent, T: int = 5, N: int = 2, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    obs = rng.standard_normal((T, N, agent.obs_size)).astype(np.float32)
    masks = rng.random((T, N, agent.n_actions)) < 0.5
    masks[..., 0] = True  # always at least one legal action
    actions = np.zeros((T, N), dtype=np.int64)
    logprobs = np.zeros((T, N), dtype=np.float32)
    values = np.zeros((T, N), dtype=np.float32)
    for t in range(T):
        for n in range(N):
            action, logprob, value = agent.act(obs[t, n], masks[t, n])
            assert masks[t, n, action]
            actions[t, n] = action
            logprobs[t, n] = logprob
            values[t, n] = value
    rewards = rng.standard_normal((T, N)).astype(np.float32)
    dones = np.zeros((T, N), dtype=np.float32)
    dones[-1, -1] = 1.0
    return {
        "obs": obs,
        "actions": actions,
        "logprobs": logprobs,
        "values": values,
        "rewards": rewards,
        "dones": dones,
        "masks": masks,
    }


def test_ppo_first_minibatch_ratio_is_one_and_update_is_finite():
    agent = PPOAgent(
        obs_size=11,
        n_actions=5,
        config=PPOConfig(hidden_sizes=(16, 16), minibatch_size=4, epochs=2),
        device="cpu",
        seed=0,
    )
    rollout = _collect_rollout(agent, T=6, N=2, seed=1)
    obs_t = torch.as_tensor(rollout["obs"].reshape(-1, 11))
    actions_t = torch.as_tensor(rollout["actions"].reshape(-1))
    masks_t = torch.as_tensor(rollout["masks"].reshape(-1, 5))
    old_logp = torch.as_tensor(rollout["logprobs"].reshape(-1))

    new_logp, entropy, values = agent.evaluate_actions(obs_t, actions_t, masks_t)
    # Before any gradient step, new and old log-probs must agree, so the PPO
    # ratio is exactly 1 on the first minibatch.
    ratios = (new_logp - old_logp).exp()
    assert torch.allclose(ratios, torch.ones_like(ratios), atol=1e-5)
    assert (entropy >= 0).all() and torch.isfinite(entropy).all()
    assert values.shape == (rollout["actions"].size,)

    before = {name: param.detach().clone() for name, param in agent.model.named_parameters()}
    metrics = agent.update(rollout)

    required = {
        "policy_loss",
        "value_loss",
        "entropy",
        "approx_kl",
        "clip_fraction",
        "loss",
        "explained_variance",
        "lr",
    }
    assert required.issubset(metrics)
    for key in required:
        assert np.isfinite(metrics[key]), key
    assert metrics["entropy"] > 0.0
    assert metrics["lr"] == pytest.approx(3e-4)
    assert metrics["ratio_first_minibatch"] == pytest.approx(1.0, abs=1e-4)
    assert agent.update_count == 1

    changed = any(
        not torch.equal(before[name], param.detach())
        for name, param in agent.model.named_parameters()
    )
    assert changed, "PPO update did not modify any parameters"


@pytest.mark.parametrize("device", DEVICES)
def test_ppo_save_load_roundtrip(device, tmp_path):
    agent = PPOAgent(
        obs_size=9,
        n_actions=5,
        config=PPOConfig(hidden_sizes=(16, 16), minibatch_size=4, epochs=1),
        device=device,
        seed=2,
    )
    rollout = _collect_rollout(agent, T=4, N=1, seed=3)
    agent.update(rollout)
    path = tmp_path / f"ppo_{device.replace(':', '_')}.pt"
    training_meta = {
        "episode": 7,
        "note": "roundtrip",
        # Training code also stores its full config under "config"; it must not
        # clobber the agent config required by the checkpoint contract.
        "config": {"algorithm": "ppo", "timesteps": 1, "ppo": {"lr": 1e-3}},
        "observation": {"preview": 5},
    }
    agent.save(path, extra=training_meta)

    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    for key in ("obs_size", "n_actions", "config", "model_state",
                "optimizer_state", "update_count", "obs_version"):
        assert key in checkpoint
    assert checkpoint["obs_version"] == 1
    assert checkpoint["config"]["hidden_sizes"] == (16, 16)
    assert checkpoint["config"]["lr"] == pytest.approx(agent.config.lr)
    assert checkpoint["extra"]["observation"] == {"preview": 5}
    assert checkpoint["train_config"]["timesteps"] == 1

    loaded = PPOAgent.load(path, device=device)
    agent.eval()
    loaded.eval()
    probe = torch.as_tensor(np.random.default_rng(4).standard_normal((3, 9)), dtype=torch.float32)
    with torch.no_grad():
        logits_a, value_a = agent.model(probe.to(agent.device))
        logits_b, value_b = loaded.model(probe.to(loaded.device))
    assert torch.allclose(logits_a.cpu(), logits_b.cpu(), atol=1e-7)
    assert torch.allclose(value_a.cpu(), value_b.cpu(), atol=1e-7)
    assert loaded.update_count == agent.update_count
    assert loaded.obs_size == agent.obs_size
    assert loaded.n_actions == agent.n_actions
    assert loaded.config == agent.config
    assert loaded.device_used == str(agent.device)


# ---------------------------------------------------------------------------
# Double DQN target masking
# ---------------------------------------------------------------------------
class _FixedQ(torch.nn.Module):
    """Hardware-controlled Q network for target-masking tests."""

    def __init__(self, rows: list[list[float]]) -> None:
        super().__init__()
        self.register_buffer("values", torch.tensor(rows, dtype=torch.float32))

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        return self.values[: obs.shape[0]]


def test_double_dqn_target_uses_valid_argmax_only():
    agent = DQNAgent(
        obs_size=3,
        n_actions=4,
        config=DQNConfig(hidden_sizes=(8,), buffer_size=32, learning_starts=0, batch_size=2),
        device="cpu",
        seed=0,
    )
    # Row 0: legal {0, 2}; online prefers 2, but illegal action 1 has a huge Q.
    # Row 1: legal {1, 3}; online prefers 3; the transition is terminal.
    agent.online = _FixedQ([[5.0, 1000.0, 7.0, -3.0], [0.0, 4.0, 999.0, 6.0]]).to(agent.device)
    agent.target = _FixedQ([[10.0, 9999.0, 2.0, 8888.0], [0.0, 3.0, 777.0, 4.0]]).to(agent.device)

    next_masks = torch.tensor(
        [[True, False, True, False], [False, True, False, True]]
    )
    rewards = torch.tensor([1.0, 5.0])
    dones = torch.tensor([0.0, 1.0])
    targets, next_actions, bootstrap = agent.compute_targets(
        rewards, torch.zeros(2, 3), dones, next_masks
    )

    # a* = argmax over VALID online Q only: [2, 3] (never the illegal 1000/999).
    assert next_actions.tolist() == [2, 3]
    assert bootstrap.tolist() == [2.0, 4.0]
    expected = torch.tensor(
        [1.0 + agent.config.gamma * 2.0, 5.0]  # terminal transition: no bootstrap
    )
    assert torch.allclose(targets, expected, atol=1e-5)

    # Non-Double DQN: max over valid target Q values (row 0 max valid = 10.0),
    # which deliberately differs from Q_target(s', a*) = 2.0 used by Double DQN.
    agent.config.double = False
    targets_single, _, _ = agent.compute_targets(
        rewards, torch.zeros(2, 3), dones, next_masks
    )
    expected_single = torch.tensor([1.0 + agent.config.gamma * 10.0, 5.0])
    assert torch.allclose(targets_single, expected_single, atol=1e-5)
    agent.config.double = True


def test_dqn_update_target_is_finite_and_bounded():
    agent = DQNAgent(
        obs_size=6,
        n_actions=4,
        config=DQNConfig(
            hidden_sizes=(8, 8),
            buffer_size=32,
            learning_starts=0,
            batch_size=4,
            target_sync_steps=2,
            epsilon_decay_steps=10,
        ),
        device="cpu",
        seed=1,
    )
    rng = np.random.default_rng(0)
    mask = np.array([True, False, True, True])
    for i in range(6):
        obs = rng.standard_normal(6).astype(np.float32)
        action = agent.act(obs, mask, step=i)
        assert mask[action]
        agent.observe(obs, action, 1.0, rng.standard_normal(6).astype(np.float32), False, mask)
    metrics = agent.update(step=6)
    assert metrics is not None
    for key, value in metrics.items():
        assert np.isfinite(value), key
    # Step 6 >= target_sync_steps=2 -> the target network was synchronized.
    assert agent._sync_count >= 1
    assert agent.updates == 1


# ---------------------------------------------------------------------------
# Replay buffer
# ---------------------------------------------------------------------------
def test_replay_buffer_wrapping_shapes_and_dtypes():
    capacity = 6
    buffer = ReplayBuffer(capacity=capacity, obs_size=4, n_actions=3, seed=0)
    assert buffer.obs.shape == (capacity, 4)
    assert buffer.next_masks.dtype == np.bool_
    assert len(buffer) == 0

    for i in range(10):
        obs = np.full(4, float(i), dtype=np.float32)
        next_obs = np.full(4, float(i + 100), dtype=np.float32)
        next_mask = np.array([True, False, True]) if i % 2 else np.array([False, True, True])
        buffer.add(obs, i % 3, float(i), next_obs, i % 4 == 0, next_mask)

    assert len(buffer) == capacity
    assert buffer.position == 10 % capacity

    batch = buffer.sample(capacity, device="cpu")
    assert batch["obs"].shape == (capacity, 4)
    assert batch["actions"].shape == (capacity,)
    assert batch["rewards"].shape == (capacity,)
    assert batch["next_obs"].shape == (capacity, 4)
    assert batch["dones"].shape == (capacity,)
    assert batch["next_masks"].shape == (capacity, 3)
    assert batch["next_masks"].dtype == torch.bool
    assert batch["actions"].dtype == torch.long
    assert batch["obs"].dtype == torch.float32
    assert (batch["obs"].device.type == "cpu")
    # Only the six most recent transitions survive the wrap-around.
    assert set(batch["obs"][:, 0].tolist()) == {4.0, 5.0, 6.0, 7.0, 8.0, 9.0}
    assert (batch["next_masks"].sum(dim=1) >= 1).all()

    probe = buffer.sample(2, device=torch.device("cpu"))
    assert probe["obs"].shape == (2, 4)

    # Same seed + same data -> identical samples (fresh buffers, so the RNG
    # streams line up).
    def _fill(buf: ReplayBuffer) -> None:
        for i in range(10):
            buf.add(
                np.full(4, float(i)),
                i % 3,
                float(i),
                np.full(4, float(i + 100)),
                i % 4 == 0,
                np.array([True, False, True]) if i % 2 else np.array([False, True, True]),
            )

    deterministic_a = ReplayBuffer(capacity=capacity, obs_size=4, n_actions=3, seed=0)
    deterministic_b = ReplayBuffer(capacity=capacity, obs_size=4, n_actions=3, seed=0)
    _fill(deterministic_a)
    _fill(deterministic_b)
    assert torch.equal(
        deterministic_a.sample(4)["actions"], deterministic_b.sample(4)["actions"]
    )


def test_replay_buffer_rejects_bad_shapes():
    buffer = ReplayBuffer(4, obs_size=3, n_actions=2)
    with pytest.raises(ValueError):
        buffer.add(np.zeros(4), 0, 0.0, np.zeros(3), False, np.array([True, False]))
    with pytest.raises(ValueError):
        buffer.add(np.zeros(3), 0, 0.0, np.zeros(3), False, np.array([True]))
    with pytest.raises(ValueError):
        buffer.sample(2)  # empty
    buffer.add(np.zeros(3), 0, 0.0, np.zeros(3), False, np.array([True, False]))
    with pytest.raises(ValueError):
        buffer.add(np.zeros(3), 5, 0.0, np.zeros(3), False, np.array([True, False]))


# ---------------------------------------------------------------------------
# DQN schedules, n-step, checkpointing
# ---------------------------------------------------------------------------
def test_dqn_epsilon_schedule_monotonic():
    agent = DQNAgent(
        obs_size=3,
        n_actions=3,
        config=DQNConfig(buffer_size=64, hidden_sizes=(8,)),
        device="cpu",
        seed=0,
    )
    decay = agent.config.epsilon_decay_steps
    steps = [0, 1, decay // 4, decay // 2, decay - 1, decay, decay + 10]
    values = [agent.epsilon_for_step(s) for s in steps]
    assert values[0] == pytest.approx(agent.config.epsilon_start)
    assert values[-1] == pytest.approx(agent.config.epsilon_end)
    assert all(a >= b - 1e-9 for a, b in zip(values, values[1:]))
    assert all(
        agent.config.epsilon_end - 1e-9 <= v <= agent.config.epsilon_start + 1e-9 for v in values
    )
    mid = agent.epsilon_for_step(decay // 2)
    assert agent.config.epsilon_end < mid < agent.config.epsilon_start


def test_dqn_n_step_accumulation():
    agent = DQNAgent(
        obs_size=2,
        n_actions=3,
        config=DQNConfig(
            hidden_sizes=(8,),
            buffer_size=16,
            learning_starts=0,
            batch_size=2,
            gamma=0.5,
            n_step=2,
        ),
        device="cpu",
        seed=0,
    )
    m = np.array([True, False, False])
    agent.observe(np.array([1.0, 0.0]), 0, 1.0, np.array([2.0, 0.0]), False, m)
    assert len(agent.buffer) == 0  # needs a second transition for the window
    agent.observe(np.array([2.0, 0.0]), 1, 2.0, np.array([3.0, 0.0]), False, m)
    assert len(agent.buffer) == 1
    assert agent.buffer.rewards[0] == pytest.approx(1.0 + 0.5 * 2.0)
    assert agent.buffer.next_obs[0].tolist() == [3.0, 0.0]
    assert bool(agent.buffer.dones[0]) is False

    agent.observe(np.array([3.0, 0.0]), 2, 4.0, np.array([4.0, 0.0]), True, m)
    assert len(agent.buffer) == 3
    # Window [t1, t2] terminates: reward 2 + 0.5 * 4, done=True.
    assert agent.buffer.rewards[1] == pytest.approx(2.0 + 0.5 * 4.0)
    assert bool(agent.buffer.dones[1]) is True
    assert agent.buffer.rewards[2] == pytest.approx(4.0)
    assert bool(agent.buffer.dones[2]) is True
    assert agent.steps == 3


@pytest.mark.parametrize("device", DEVICES)
def test_dqn_save_load_roundtrip(device, tmp_path):
    agent = DQNAgent(
        obs_size=7,
        n_actions=4,
        config=DQNConfig(
            hidden_sizes=(16, 16),
            buffer_size=32,
            learning_starts=0,
            batch_size=2,
            epsilon_decay_steps=10,
        ),
        device=device,
        seed=3,
    )
    rng = np.random.default_rng(1)
    mask = np.array([True, True, False, True])
    for i in range(4):
        obs = rng.standard_normal(7).astype(np.float32)
        action = agent.act(obs, mask, step=i)
        agent.observe(obs, action, 0.5, rng.standard_normal(7).astype(np.float32), i == 3, mask)
    assert agent.update(step=4) is not None
    path = tmp_path / f"dqn_{device.replace(':', '_')}.pt"
    training_meta = {
        "episode": 3,
        "note": "roundtrip",
        "config": {"algorithm": "dqn", "timesteps": 1, "dqn": {"lr": 1e-3}},
        "observation": {"preview": 5},
    }
    agent.save(path, extra=training_meta)

    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    for key in ("obs_size", "n_actions", "config", "online_state", "target_state",
                "optimizer_state", "steps", "updates", "obs_version"):
        assert key in checkpoint
    assert checkpoint["obs_version"] == 1
    assert checkpoint["config"]["hidden_sizes"] == (16, 16)
    assert checkpoint["config"]["lr"] == pytest.approx(agent.config.lr)
    assert checkpoint["extra"]["observation"] == {"preview": 5}
    assert checkpoint["train_config"]["algorithm"] == "dqn"

    loaded = DQNAgent.load(path, device=device)
    agent.eval()
    loaded.eval()
    probe = torch.as_tensor(
        rng.standard_normal((5, 7)), dtype=torch.float32, device=agent.device
    )
    with torch.no_grad():
        q_online_a = agent.online(probe)
        q_online_b = loaded.online(probe.to(loaded.device))
        q_target_a = agent.target(probe)
        q_target_b = loaded.target(probe.to(loaded.device))
    assert torch.allclose(q_online_a.cpu(), q_online_b.cpu(), atol=1e-7)
    assert torch.allclose(q_target_a.cpu(), q_target_b.cpu(), atol=1e-7)
    assert loaded.steps == agent.steps
    assert loaded.updates == agent.updates
    assert loaded.config == agent.config
    assert loaded.device_used == str(agent.device)


# ---------------------------------------------------------------------------
# Networks and device resolution
# ---------------------------------------------------------------------------
def test_network_shapes_and_device_resolution():
    mlp = MLP(5, hidden_sizes=(8, 4), output_size=3, activation="relu", orthogonal_init=True)
    out = mlp(torch.randn(2, 5))
    assert out.shape == (2, 3)

    no_output = MLP(5, hidden_sizes=(6,))
    assert no_output(torch.randn(1, 5)).shape == (1, 6)

    ac = ActorCritic(5, 3, hidden_sizes=(8, 8))
    logits, value = ac(torch.randn(4, 5))
    assert logits.shape == (4, 3)
    assert value.shape == (4,)

    q = QNetwork(5, 3, hidden_sizes=(8, 8))
    assert q(torch.randn(4, 5)).shape == (4, 3)

    assert resolve_device("cpu").type == "cpu"
    auto = resolve_device(None)
    assert auto.type == ("cuda" if torch.cuda.is_available() else "cpu")
    if torch.cuda.is_available():
        assert resolve_device("cuda").type == "cuda"
        assert isinstance(resolve_device(None), torch.device)


# ---------------------------------------------------------------------------
# Tiny end-to-end smoke test (fake environment, not the real simulator)
# ---------------------------------------------------------------------------
def test_two_step_end_to_end_smoke():
    obs_size = ObservationEncoder().size
    assert obs_size == 889  # 2*400 board + 20 heights + 8 hold + 35 preview + 11 piece + 15 scalars
    fake_env = {"observation_size": obs_size, "action_space": 80}

    rng = np.random.default_rng(7)
    masks = []
    for _ in range(3):
        mask = np.zeros(fake_env["action_space"], dtype=bool)
        mask[rng.choice(fake_env["action_space"], size=5, replace=False)] = True
        masks.append(mask)
    observations = [
        rng.standard_normal(fake_env["observation_size"]).astype(np.float32) for _ in range(3)
    ]

    # --- PPO: two steps, one update --------------------------------------
    ppo = PPOAgent(
        obs_size=fake_env["observation_size"],
        n_actions=fake_env["action_space"],
        config=PPOConfig(hidden_sizes=(16, 16), minibatch_size=2, epochs=1),
        device="cpu",
        seed=0,
    )
    T = 2
    rollout = {
        "obs": np.zeros((T, 1, obs_size), dtype=np.float32),
        "actions": np.zeros((T, 1), dtype=np.int64),
        "logprobs": np.zeros((T, 1), dtype=np.float32),
        "values": np.zeros((T, 1), dtype=np.float32),
        "rewards": np.array([[0.5], [1.0]], dtype=np.float32),
        "dones": np.array([[0.0], [1.0]], dtype=np.float32),
        "masks": np.zeros((T, 1, 80), dtype=bool),
    }
    for t in range(T):
        action, logprob, value = ppo.act(observations[t], masks[t])
        assert masks[t][action]
        rollout["obs"][t, 0] = observations[t]
        rollout["actions"][t, 0] = action
        rollout["logprobs"][t, 0] = logprob
        rollout["values"][t, 0] = value
        rollout["masks"][t, 0] = masks[t]
    ppo_metrics = ppo.update(rollout)
    assert set(
        ["policy_loss", "value_loss", "entropy", "approx_kl", "clip_fraction", "loss",
         "explained_variance", "lr"]
    ).issubset(ppo_metrics)
    assert all(np.isfinite(value) for value in ppo_metrics.values())

    # --- DQN: two steps, one update --------------------------------------
    dqn = DQNAgent(
        obs_size=fake_env["observation_size"],
        n_actions=fake_env["action_space"],
        config=DQNConfig(
            hidden_sizes=(16, 16),
            buffer_size=8,
            learning_starts=0,
            batch_size=2,
            epsilon_decay_steps=10,
            target_sync_steps=2,
        ),
        device="cpu",
        seed=1,
    )
    for t in range(T):
        action = dqn.act(observations[t], masks[t], step=t)
        assert masks[t][action]
        dqn.observe(
            observations[t], action, 1.0, observations[t + 1], t == T - 1, masks[t + 1]
        )
    dqn_metrics = dqn.update(step=T)
    assert dqn_metrics is not None
    assert all(np.isfinite(value) for value in dqn_metrics.values())
    assert dqn_metrics["buffer_size"] == 2.0
    assert 0.0 < dqn_metrics["epsilon"] <= 1.0
