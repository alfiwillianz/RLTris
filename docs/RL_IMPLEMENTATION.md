# RL Implementation

Status: implemented and tested (see *Verification*). Scope: neural agents only.
The environment, observation encoder, action encoding, and reward function are
consumed unchanged from `tetrisrl/environment/`; nothing here imports
`tetrisrl.training`, so the dependency direction stays
`environment <- rl <- training`.

## 1. Files

| file | contents |
|---|---|
| `tetrisrl/rl/masked.py` | masked log-softmax / softmax / entropy / categorical / argmax |
| `tetrisrl/rl/networks.py` | `MLP`, `ActorCritic`, `QNetwork`, `resolve_device` |
| `tetrisrl/rl/ppo/agent.py` | `PPOConfig`, `compute_gae`, `PPOAgent` |
| `tetrisrl/rl/dqn/agent.py` | `DQNConfig`, `DQNAgent` |
| `tetrisrl/rl/dqn/replay.py` | preallocated circular `ReplayBuffer` |
| `tetrisrl/tests/test_rl.py` | 22 unit/integration tests |
| `docs/RL_IMPLEMENTATION.md` | this document |

Both learners consume the same flat observation (`ObservationEncoder.size`,
**889** with the default encoder, `OBS_VERSION = 1`), the same 80-action
placement space, and the same `list[bool]` action mask. No algorithm gets a
privileged observation or a different ruleset.

## 2. Masking semantics

* A mask is a bool tensor `[B, A]`; `True` means the placement is legal.
* Illegal logits are replaced with `torch.finfo(dtype).min` (not `-inf`) before
  the softmax. Illegal probabilities are therefore **exactly `0.0`**, and
  `p * log p` / backpropagation never produce `NaN`. Empirically the minimum
  float underflows to zero in the exponential.
* `masked_log_softmax` returns finite log-probabilities for legal actions;
  illegal entries are large finite negatives. Sampling can never select an
  illegal action (`masked_categorical(...).probs[~mask] == 0`).
* `masked_entropy` is computed from the *masked* distribution, not raw logits.
  A row with one legal action has entropy exactly `0`; a single legal action
  produces no `NaN` anywhere.
* `masked_argmax` ignores illegal Q-values, even when an illegal entry has a
  huge value (this is what the Double-DQN target relies on).
* Defensive fallback: a row with **no** legal action is treated as all-legal
  (uniform). The environment contract guarantees at least one legal placement,
  so this only protects synthetic/malformed input from NaNs.

## 3. Networks

`MLP(input_size, hidden_sizes, output_size=None, activation="tanh",
orthogonal_init=False, output_gain=1.0)` — configurable widths/activation and
optional orthogonal initialisation.

`ActorCritic(obs_size, n_actions=80, hidden_sizes=(256, 256))` uses **separate**
actor and critic trunks and returns `(logits, value)`. Both trunks use
orthogonal initialisation; the policy output gain is `0.01` so the initial
policy is close to uniform. `QNetwork` is the same MLP with `n_actions` outputs.

`resolve_device(None)` returns `cuda` when available, otherwise `cpu`. Explicit
`"cuda"`/`"mps"` requests fall back to CPU with a warning when unavailable. No
module calls `.cuda()` directly; all tensors/networks move via `.to(device)`.

## 4. PPO

### Defaults (`PPOConfig`)

| field | value |
|---|---|
| `lr` | `3e-4` |
| `gamma` / `gae_lambda` | `0.99` / `0.95` |
| `clip_ratio` | `0.2` |
| `value_coef` / `entropy_coef` | `0.5` / `0.01` |
| `max_grad_norm` | `0.5` |
| `epochs` / `minibatch_size` | `4` / `256` |
| `hidden_sizes` | `(256, 256)` |
| `normalize_advantage` | `True` |
| `target_kl` | `None` (enabled optionally) |
| `max_episode_steps` | `100000` (informational) |

### Rollout and GAE

`update` takes `obs [T,N,obs]`, `actions [T,N]`, `logprobs [T,N]`,
`values [T,N]`, `rewards [T,N]`, `dones [T,N]`, `masks [T,N,A]`.
`N` is the number of parallel environments (use `N=1` for a single env).

`compute_gae` uses the standard recursion

```
delta_t = r_t + gamma * V(s_{t+1}) * (1 - done_t) - V(s_t)
A_t     = delta_t + gamma * lambda * (1 - done_t) * A_{t+1}
returns = A + V
```

`dones` covers both termination and truncation. For the final rollout step the
bootstrap value is `0` by default; a caller that truncated on a time limit
should pass the optional `last_values [N]` argument (`V(final_obs)`), or pass
`values` with `T+1` rows whose last row is the bootstrap value. A terminal
final step (`done_t = 1`) never bootstraps. A hand-computed three-step example
for both cases is in the test suite.

*Collector contract:* mark a transition `done=True` when the episode ended for
**either** reason. If a collector instead bakes the truncated bootstrap into
the reward (`r += gamma * V(final_obs)`), it must still set `done=True` for
that transition; otherwise GAE reads the next episode's value and double
counts the bootstrap.

### Update

The rollout is flattened and shuffled each epoch. Per minibatch:

```
ratio        = exp(new_logp - old_logp)
policy_loss  = -mean(min(ratio * A, clip(ratio, 1-c, 1+c) * A))
value_loss   = 0.5 * mean((V_new - returns)^2)
loss         = policy_loss + value_coef * value_loss - entropy_coef * H
```

`max_grad_norm` clipping is applied after `backward`. Advantages can be
normalised over the flattened batch. `target_kl` stops further epochs after a
mean approximate KL above `1.5 * target_kl`. Because the first minibatch is
evaluated before any gradient step, its PPO ratio is exactly `1`; this is
exposed as `ratio_first_minibatch` and asserted by the tests.

Reported metrics: `policy_loss`, `value_loss`, `entropy`, `approx_kl`
(`0.5 * mean(log_ratio^2)`), `clip_fraction`, `loss`, `explained_variance`,
`lr`, plus `grad_norm`, `ratio_mean`, `ratio_first_minibatch`, `epochs_run`.
All are finite floats.

### Checkpointing

`save(path, extra=None)` writes `obs_size`, `n_actions`, `config` (dataclass
dict), `model_state`, `optimizer_state`, `update_count`, `obs_version`.
Caller metadata is nested under `"extra"` and non-conflicting keys are also
copied to the top level; required keys (notably `config`) are never
overwritten. The full training config, when supplied by the training loop, is
also available as `train_config`. `PPOAgent.load(path, device=None)` restores
all required fields and warns if the stored `obs_version` differs from the
current encoder version. A legacy checkpoint whose `config` is the full
training config (with a nested `ppo` dict) is still loadable.

## 5. Double DQN

### Defaults (`DQNConfig`)

| field | value |
|---|---|
| `lr` | `1e-4` |
| `gamma` | `0.99` |
| `epsilon_start` / `epsilon_end` | `1.0` / `0.02` |
| `epsilon_decay_steps` | `100000` (linear) |
| `batch_size` / `buffer_size` | `256` / `200000` |
| `target_sync_steps` | `2000` (hard sync) |
| `huber_delta` | `1.0` |
| `max_grad_norm` | `10.0` |
| `hidden_sizes` | `(256, 256)` |
| `double` | `True` |
| `learning_starts` / `train_freq` | `1000` / `1` |
| `n_step` | `1` |

### Target and loss

For a transition `(s, a, r, s', done, mask')`:

```
a* = argmax_{valid a'} Q_online(s', a')          # masked_argmax
y  = r + gamma^n * (1 - done) * Q_target(s', a*)
loss = smooth_l1(Q_online(s, a), y, beta=huber_delta)
```

Illegal next actions can never be selected, even with extreme Q-values; the
tests cover this with hand-controlled network weights. `double=False` falls
back to a masked max of the target network. Gradients are clipped to
`max_grad_norm`. The target network is hard-synced when the environment step
counter crosses each `target_sync_steps` boundary.

### Replay buffer

Fixed-capacity preallocated `numpy` arrays (`np.empty`, so unwritten pages are
not committed): `obs`/`next_obs` float32 `[C, obs_size]`, `actions` int64,
`rewards` float32, `dones` bool, `next_masks` bool `[C, A]`. At the default
200k capacity this is roughly **1.4 GiB**; reduce `buffer_size` for small
experiments. `sample(batch_size, device)` returns float32/float32/long/
float32/float32/bool tensors for
`obs, actions, rewards, next_obs, dones, next_masks` using a seeded RNG, without
replacement when possible.

`n_step > 1` accumulates transitions in a per-environment window. When the
window is full the oldest transition is emitted with the discounted reward sum
and the newest `next_obs`; a terminal transition flushes all pending windows
with `done=True`. `observe(..., env_id=0)` identifies the stream; parallel
training code must pass a distinct `env_id` per environment.

`epsilon` decays linearly from `epsilon_start` to `epsilon_end` over
`epsilon_decay_steps` and then stays at `epsilon_end`. Exploration samples
uniformly among valid actions; greedy selection uses `masked_argmax`.

### Checkpointing

`save` writes `obs_size`, `n_actions`, `config`, `online_state`,
`target_state`, `optimizer_state`, `steps`, `updates`, `obs_version`, plus
sync counters. Caller metadata follows the same protected-merge rule as PPO
(nested under `"extra"`, required keys never overwritten). `DQNAgent.load`
restores networks, optimizer, counters, and warns on an `obs_version`
mismatch; a legacy `config` containing a nested `dqn` dict is also accepted.

## 6. Verification

Command (from the repository root):

```
.venv/bin/python -m pytest tetrisrl/tests/test_rl.py -q
```

Result: **22 passed**. Runtime ~3.5 s on the project machine (CPU + RTX 5060
Ti). CUDA was exercised: PPO and Double DQN save/load round-trips run on both
`cpu` and `cuda` (parametrised), and `resolve_device(None)` is asserted to
return CUDA when available.

Coverage highlights:

* masked probability mass, exact-zero invalid probabilities, single-valid-
  action determinism, entropy against a manual masked-distribution calculation,
  finite gradients, sampling never selects invalid actions, masked argmax.
* GAE hand-computed 3-step examples: terminal (`dones`), truncated
  (`last_values`), and batched == independent single-environment results.
* PPO first-minibatch ratio `≈ 1`, finite metrics/parameters change, and
  save/load output equality on CPU and CUDA.
* Double-DQN target masking with hardware-controlled weights (illegal huge
  Q-values are never selected), terminal-no-bootstrap, non-double fallback.
* Replay buffer capacity/wrap-around, shapes, dtypes, bool masks, seeded
  sampling, rejection of malformed input.
* Epsilon schedule monotonicity, n-step accumulation, DQN save/load equality
  on CPU and CUDA.
* Two-step end-to-end smoke with a fake environment dict using the real
  observation size (not the simulator, keeping the suite fast).

The suite never interacts with the real environment; environment mechanics are
covered by the engine tests.

## 7. Known limitations

* Truncation bootstrapping needs the caller to pass `last_values` (or a `T+1`
  `values` array). With only the seven required rollout keys the final step is
  treated as an episode boundary; the training loop should supply bootstrap
  values for time-limit truncations.
* A completely empty mask row is repaired to uniform rather than raising. This
  is defensive only; the environment guarantees a legal placement.
* PPO seeds the global `torch` RNG at construction. Agents created in the same
  process share that stream; create/seed them in a fixed order for fully
  reproducible sampling.
* DQN `n_step > 1` windows are not checkpointed, and `train_freq` is gated by
  `steps % train_freq`; the training loop should call `update` once per step.
* No recurrent/convolutional encoders, no prioritised replay, no
  distributional/QMIX variants. The flat MLP is deliberate for the project's
  observation size and hardware target.
