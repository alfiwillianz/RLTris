"""Batched versus training environment (agent vs scripted random opponent).

This wires the NumPy placement core into the RL interface.  It is a *fast
training backend*: observations and rewards are vectorised, and the opponent is
a random legal-placement bot.  Spin detection, surge segmentation and garbage
receive delays are simplified (documented in docs/ARCHITECTURE.md §7); the
reference engine remains the validation target and the default for reported
experiments.

API mirrors :class:`tetrisrl.training.vec_env.VecEnv`:

    env = BatchedVersusEnv(n_envs=64, seed=0)
    obs, infos = env.reset()
    obs, rewards, terminated, truncated, infos = env.step(actions)
    env.action_masks() -> [N, 80] bool
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..environment.batched import CELLS_PAD, HEIGHT, LEFT_OFFSET_NP, N_ACTIONS, PIECE_INDEX, WIDTH, BatchedBoard
from ..environment.ruleset import RulesetConfig, load_ruleset
from ..environment.scoring import ClearState, compute_attack, on_no_clear
from ..environment.rewards import RewardConfig

PIECES = "IJLOSTZ"
PREVIEW = 5


def _one_hot(idx: np.ndarray, size: int, offset: int = 0) -> np.ndarray:
    out = np.zeros((idx.shape[0], size), dtype=np.float32)
    valid = (idx >= offset) & (idx < offset + size) if False else (idx >= 0) & (idx < size)
    out[np.arange(idx.shape[0])[valid], idx[valid]] = 1.0
    return out


class BatchedVersusEnv:
    """``N`` simultaneous agent-vs-random matches, fully vectorised."""

    def __init__(
        self,
        n_envs: int = 64,
        ruleset: RulesetConfig | str | dict = "tetrio_s2",
        seed: int = 0,
        max_pieces: int = 400,
        reward_config: Optional[RewardConfig] = None,
        include_opponent: bool = True,
        sequence_length: int = 4096,
    ) -> None:
        self.n = int(n_envs)
        self.ruleset = load_ruleset(ruleset)
        self.seed = int(seed)
        self.max_pieces = int(max_pieces)
        self.reward_cfg = reward_config or RewardConfig()
        self.include_opponent = bool(include_opponent)
        self.sequence_length = int(sequence_length)
        self.observation_size = 400 + (400 if include_opponent else 0) + 10 + (10 if include_opponent else 0) + 8 + PREVIEW * 7 + 7 + 4 + 15

        self.rng = np.random.default_rng(self.seed)
        self.agent = BatchedBoard(self.n, self.ruleset)
        self.opp = BatchedBoard(self.n, self.ruleset)

        self.current_a = np.zeros(self.n, dtype=np.int16)
        self.current_b = np.zeros(self.n, dtype=np.int16)
        self.hold_a = np.full(self.n, -1, dtype=np.int16)
        self.hold_b = np.full(self.n, -1, dtype=np.int16)
        self.can_hold_a = np.ones(self.n, dtype=bool)
        self.can_hold_b = np.ones(self.n, dtype=bool)
        self.pos_a = np.zeros(self.n, dtype=np.int64)
        self.pos_b = np.zeros(self.n, dtype=np.int64)
        self.seq_a = np.zeros((self.n, self.sequence_length), dtype=np.int8)
        self.seq_b = np.zeros((self.n, self.sequence_length), dtype=np.int8)

        self.clear_a = [ClearState() for _ in range(self.n)]
        self.clear_b = [ClearState() for _ in range(self.n)]
        self.pending_a = np.zeros(self.n, dtype=np.int16)   # incoming, not yet active
        self.pending_b = np.zeros(self.n, dtype=np.int16)
        self.ready_a = np.zeros(self.n, dtype=np.int16)     # active garbage
        self.ready_b = np.zeros(self.n, dtype=np.int16)
        self.done = np.zeros(self.n, dtype=bool)
        self.won = np.zeros(self.n, dtype=np.int8)  # 1 win, -1 loss, 0 none
        self.steps = np.zeros(self.n, dtype=np.int64)
        self.episode_lines = np.zeros(self.n, dtype=np.float32)
        self.episode_attack = np.zeros(self.n, dtype=np.float32)
        self.episode_wins = np.zeros(self.n, dtype=np.float32)
        self.episodes = np.zeros(self.n, dtype=np.int64)
        self._masks = np.zeros((self.n, N_ACTIONS), dtype=bool)

    @property
    def num_envs(self) -> int:
        return self.n

    @property
    def action_space_size(self) -> int:
        return N_ACTIONS

    # ------------------------------------------------------------------
    def _fill_sequences(self) -> None:
        bags = self.sequence_length // 7 + 1
        for seq, offset in ((self.seq_a, 0), (self.seq_b, 7919)):
            rng = np.random.default_rng(self.seed + offset + 1)
            perm = np.argsort(rng.random((self.n, bags, 7)), axis=2).reshape(self.n, -1)
            seq[:, :] = perm[:, : self.sequence_length]

    def _next_pieces(self, pos: np.ndarray, seq: np.ndarray, count: int = PREVIEW + 2) -> np.ndarray:
        idx = (pos[:, None] + np.arange(count)[None, :]) % self.sequence_length
        return seq[np.arange(self.n)[:, None], idx].astype(np.int16)

    def reset(self, seeds: Optional[Sequence[int]] = None) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        if seeds is not None and len(seeds):
            self.seed = int(seeds[0])
        self.agent = BatchedBoard(self.n, self.ruleset)
        self.opp = BatchedBoard(self.n, self.ruleset)
        self._fill_sequences()
        self.pos_a[:] = 0
        self.pos_b[:] = 0
        self.current_a = self.seq_a[np.arange(self.n), 0].astype(np.int16)
        self.current_b = self.seq_b[np.arange(self.n), 0].astype(np.int16)
        self.pos_a[:] = 1
        self.pos_b[:] = 1
        self.hold_a[:] = -1
        self.hold_b[:] = -1
        self.can_hold_a[:] = True
        self.can_hold_b[:] = True
        self.clear_a = [ClearState() for _ in range(self.n)]
        self.clear_b = [ClearState() for _ in range(self.n)]
        self.pending_a[:] = 0
        self.pending_b[:] = 0
        self.ready_a[:] = 0
        self.ready_b[:] = 0
        self.done[:] = False
        self.won[:] = 0
        self.steps[:] = 0
        self.episode_lines[:] = 0
        self.episode_attack[:] = 0
        self._refresh_masks()
        obs = self._observe()
        return obs, [{"action_mask": self._masks[i].tolist()} for i in range(self.n)]

    # ------------------------------------------------------------------
    def _refresh_masks(self) -> None:
        cur_valid, _, _ = self.agent.resolve_actions(self.current_a)
        hold_piece = np.where(self.hold_a >= 0, self.hold_a, self.seq_a[np.arange(self.n), self.pos_a % self.sequence_length].astype(np.int16))
        hold_valid, _, _ = self.agent.resolve_actions(hold_piece)
        masks = np.zeros_like(cur_valid)
        masks[:, 0::2] = cur_valid[:, 0::2]
        masks[:, 1::2] = hold_valid[:, 1::2] & self.can_hold_a[:, None]
        self._masks = masks

    def action_masks(self) -> np.ndarray:
        return self._masks

    # ------------------------------------------------------------------
    def _resolve_for(self, board: BatchedBoard, action_ids: np.ndarray, piece_ids: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        valid, ys, cells = board.resolve_actions(piece_ids)
        return valid[np.arange(self.n), action_ids], cells[np.arange(self.n), action_ids]

    def step(self, actions: np.ndarray):
        actions = np.asarray(actions, dtype=np.int64)
        rewards_before_metrics = self._metrics()
        done_before = self.done.copy()

        # ---- agent placement -------------------------------------------
        cur_valid, cur_cells = self._resolve_for(self.agent, actions, self.current_a)
        hold_idx = np.where(self.hold_a >= 0, self.hold_a, self.seq_a[np.arange(self.n), self.pos_a % self.sequence_length].astype(np.int16))
        hold_valid, hold_cells = self._resolve_for(self.agent, actions, hold_idx)
        use_hold = (actions % 2 == 1)
        valid = np.where(use_hold, hold_valid & self.can_hold_a, cur_valid)
        cells = np.where(use_hold[:, None, None], hold_cells, cur_cells)
        piece_used = np.where(use_hold, hold_idx, self.current_a)

        # Garbage received during the previous tick becomes active now
        # (one-piece receive delay, matching the reference engine's
        # garbagespeed approximation).
        self.ready_a += self.pending_a
        self.ready_b += self.pending_b
        self.pending_a[:] = 0
        self.pending_b[:] = 0

        lines_a = np.zeros(self.n, dtype=np.int16)
        sent_a = np.zeros(self.n, dtype=np.int16)
        inserted_a = np.zeros(self.n, dtype=np.int16)
        cancelled_a = np.zeros(self.n, dtype=np.int16)

        self.agent.lock(cells, np.arange(self.n))
        lines_a = self.agent.clear_lines()
        perfect = ~self.agent.rows.any(axis=1)

        # T-spin detection (corner rule) for the chosen placements.
        rotations = (actions // 20).astype(np.int16)
        columns = ((actions // 2) % 10).astype(np.int16)
        origin_x = columns - LEFT_OFFSET_NP[piece_used, rotations]
        tdy_min = CELLS_PAD[piece_used, rotations, 0, 1].astype(np.int16)
        # Pad slots use (-1,-1); the first cell is always real.
        origin_y = cells[:, 0, 1].astype(np.int16) - tdy_min  # first cell is always real

        def corner_mask(x0: np.ndarray, y0: np.ndarray, dx: int, dy: int) -> np.ndarray:
            xx = x0 + dx
            yy = y0 + dy
            outside = (xx < 0) | (xx >= WIDTH) | (yy >= HEIGHT)
            inside = (yy >= 0) & (yy < HEIGHT)
            occ = np.zeros(self.n, dtype=bool)
            valid = inside & ~outside
            if valid.any():
                occ[valid] = ((self.agent.rows[valid, yy[valid]] >> np.clip(xx[valid], 0, WIDTH - 1).astype(np.uint16)) & 1).astype(bool)
            return occ | outside

        corners = np.stack([corner_mask(origin_x, origin_y, 0, 0), corner_mask(origin_x, origin_y, 2, 0),
                            corner_mask(origin_x, origin_y, 0, 2), corner_mask(origin_x, origin_y, 2, 2)], axis=1)
        front_idx = {0: (0, 1), 1: (1, 3), 2: (2, 3), 3: (0, 2)}
        front = np.zeros(self.n, dtype=np.int8)
        total = corners.sum(axis=1)
        for r_idx, idxs in front_idx.items():
            mask_r = rotations == r_idx
            if mask_r.any():
                front[mask_r] = corners[mask_r][:, list(idxs)].sum(axis=1)
        is_t = piece_used == PIECE_INDEX["T"]
        spin_in_used = self.agent.spin_in_used[np.arange(self.n), actions]
        rotated = (rotations != 0) | spin_in_used
        spin = is_t & (total >= 3) & rotated
        mini = spin & (front < 2)

        attack_events: List[List[int]] = []
        for i in range(self.n):
            if lines_a[i] > 0:
                comp = compute_attack(
                    self.ruleset, self.clear_a[i], int(lines_a[i]), bool(spin[i]), bool(mini[i]), bool(perfect[i])
                )
                events = list(comp.attack_events)
            else:
                events = on_no_clear(self.ruleset, self.clear_a[i])
            remaining_queue = int(self.ready_a[i])
            sent = 0
            for event in events:
                if event <= 0:
                    continue
                cancelled = min(remaining_queue, event)
                remaining_queue -= cancelled
                cancelled_a[i] += cancelled
                sent += event - cancelled
            self.ready_a[i] = remaining_queue
            sent_a[i] = sent
            self.pending_b[i] = min(40, int(self.pending_b[i]) + int(sent))
            attack_events.append([sent])
            self.episode_lines[i] += int(lines_a[i])
            self.episode_attack[i] += int(sum(events))

        # ---- opponent placement (uniform random legal placement) -------
        opp_valid, _ys, opp_cells = self.opp.resolve_actions(self.current_b)
        opp_valid[:, 1::2] = False  # opponent does not use hold in this backend
        weights = opp_valid * self.rng.random((self.n, N_ACTIONS))
        opp_actions = np.argmax(weights, axis=1).astype(np.int64)
        chosen_opp_cells = opp_cells[np.arange(self.n), opp_actions]
        self.opp.lock(chosen_opp_cells, np.arange(self.n))
        lines_b = self.opp.clear_lines()
        perfect_b = ~self.opp.rows.any(axis=1)
        sent_b = np.zeros(self.n, dtype=np.int16)
        for i in range(self.n):
            if lines_b[i] > 0:
                comp = compute_attack(self.ruleset, self.clear_b[i], int(lines_b[i]), False, False, bool(perfect_b[i]))
                events = list(comp.attack_events)
            else:
                events = on_no_clear(self.ruleset, self.clear_b[i])
            remaining_queue = int(self.ready_b[i])
            sent = 0
            for event in events:
                if event <= 0:
                    continue
                cancelled = min(remaining_queue, event)
                remaining_queue -= cancelled
                sent += event - cancelled
            self.ready_b[i] = remaining_queue
            sent_b[i] = sent
            self.pending_a[i] = min(40, int(self.pending_a[i]) + int(sent))

        # ---- garbage tank on non-clearing locks ------------------------
        for i in range(self.n):
            if lines_a[i] == 0 and self.ready_a[i] > 0:
                amount = int(min(8, self.ready_a[i]))
                self.ready_a[i] -= amount
                hole = int(self.rng.integers(0, WIDTH))
                overflow = self.agent.insert_garbage_one(i, amount, hole)
                inserted_a[i] = amount
                if overflow:
                    self.done[i] = True
                    self.won[i] = -1
            if lines_b[i] == 0 and self.ready_b[i] > 0:
                amount = int(min(8, self.ready_b[i]))
                self.ready_b[i] -= amount
                hole = int(self.rng.integers(0, WIDTH))
                self.opp.insert_garbage_one(i, amount, hole)

        # ---- spawn / terminate ----------------------------------------
        # Hold bookkeeping: using hold with an empty slot consumes an extra
        # queue entry (the held piece must wait until the next lock).
        hold_empty = use_hold & (self.hold_a < 0)
        pos_advance = np.where(hold_empty, 2, 1).astype(np.int64)
        new_pos = self.pos_a + pos_advance
        next_index = (new_pos - 1) % self.sequence_length
        next_a = self.seq_a[np.arange(self.n), next_index].astype(np.int16)
        hold_after = np.where(use_hold, self.current_a, self.hold_a)
        self.current_a = next_a
        self.hold_a = hold_after
        self.pos_a = new_pos
        next_b = self.seq_b[np.arange(self.n), self.pos_b % self.sequence_length].astype(np.int16)
        self.current_b = next_b
        self.pos_b += 1
        self.can_hold_a[:] = True
        self.can_hold_b[:] = True
        self.steps += 1

        self._refresh_masks()
        no_moves = ~self._masks.any(axis=1)
        newly_done = no_moves & ~self.done
        self.done |= newly_done
        self.won[newly_done] = -1
        self.won[self.won == 0] = 0

        truncated = (~self.done) & (self.steps >= self.max_pieces)
        terminated = self.done
        done_now = terminated | truncated

        metrics_after = self._metrics()
        reward = self._reward(rewards_before_metrics, metrics_after, lines_a, sent_a, cancelled_a, inserted_a, terminated, self.won)
        obs = self._observe()
        terminal_obs = obs.copy()
        terminal_masks = self._masks.copy()

        infos: List[Dict[str, Any]] = []
        for i in range(self.n):
            infos.append(
                {
                    "lines": int(lines_a[i]),
                    "attack": int(sent_a[i]),
                    "total_lines": float(self.episode_lines[i]),
                    "total_attack": float(self.episode_attack[i]),
                    "holes": int(metrics_after["holes"][i]),
                    "max_height": int(metrics_after["max_height"][i]),
                    "won": None if self.won[i] == 0 else bool(self.won[i] > 0),
                    "reward_components": {"total": float(reward[i])},
                    "action_mask": self._masks[i].tolist(),
                    "final_observation": terminal_obs[i],
                    "final_action_mask": terminal_masks[i].tolist(),
                }
            )
        # Auto-reset finished episodes so the rollout loop can continue.
        for i in np.flatnonzero(done_now):
            self._reset_one(int(i))
        self._refresh_masks()
        obs = self._observe()
        return obs, reward.astype(np.float32), terminated, truncated, infos

    def _reset_one(self, i: int) -> None:
        self.agent.rows[i] = 0
        self.opp.rows[i] = 0
        self.clear_a[i] = ClearState()
        self.clear_b[i] = ClearState()
        self.pending_a[i] = 0
        self.pending_b[i] = 0
        self.ready_a[i] = 0
        self.ready_b[i] = 0
        self.done[i] = False
        self.won[i] = 0
        self.steps[i] = 0
        self.episode_lines[i] = 0
        self.episode_attack[i] = 0
        self.episodes[i] += 1
        self.hold_a[i] = -1
        self.hold_b[i] = -1
        self.can_hold_a[i] = True
        self.can_hold_b[i] = True
        # Advance the piece stream per episode so auto-reset does not replay
        # the identical opening every time.
        offset = int(self.episodes[i] * 13) % max(1, self.sequence_length - PREVIEW - 2)
        self.pos_a[i] = offset
        self.pos_b[i] = offset
        self.current_a[i] = self.seq_a[i, offset]
        self.current_b[i] = self.seq_b[i, offset]
        self.pos_a[i] = offset + 1
        self.pos_b[i] = offset + 1

    # ------------------------------------------------------------------
    def _metrics(self) -> Dict[str, np.ndarray]:
        heights = self.agent.heights().astype(np.float32)
        bits = ((self.agent.rows[:, :, None] >> np.arange(WIDTH)) & 1).astype(bool)
        filled_any = bits.any(axis=1)
        top = np.where(filled_any, bits.argmax(axis=1), HEIGHT)
        holes = np.zeros(self.n, dtype=np.float32)
        for i in range(self.n):
            for x in range(WIDTH):
                col_top = int(top[i, x])
                if col_top >= HEIGHT:
                    continue
                holes[i] += int((~bits[i, col_top + 1 :, x]).sum())
        bump = np.abs(np.diff(heights, axis=1)).sum(axis=1) if WIDTH > 1 else np.zeros(self.n)
        return {"heights": heights, "holes": holes, "max_height": heights.max(axis=1), "aggregate": heights.sum(axis=1), "bumpiness": bump}

    def _reward(self, before, after, lines, sent, cancelled, inserted, done, won) -> np.ndarray:
        w = self.reward_cfg
        r = (
            w.per_line * lines
            + np.where(lines >= 4, w.tetris_bonus, 0.0)
            + w.per_attack_line * sent
            + w.per_cancelled_line * cancelled
            + w.per_received_line * inserted
            + w.per_piece
        )
        r += w.height_increase * np.clip(after["aggregate"] - before["aggregate"], 0, None)
        r += w.height_decrease * np.clip(before["aggregate"] - after["aggregate"], 0, None)
        r += w.hole_created * np.clip(after["holes"] - before["holes"], 0, None)
        r += w.hole_removed * np.clip(before["holes"] - after["holes"], 0, None)
        r += w.bumpiness_increase * np.clip(after["bumpiness"] - before["bumpiness"], 0, None)
        r += w.bumpiness_decrease * np.clip(before["bumpiness"] - after["bumpiness"], 0, None)
        r += w.max_height_penalty * np.clip(after["max_height"] - w.max_height_threshold, 0, None)
        r += np.where(done & (won > 0), w.terminal_win, 0.0)
        r += np.where(done & (won < 0), w.terminal_loss, 0.0)
        return r.astype(np.float32)

    # ------------------------------------------------------------------
    def _observe(self) -> np.ndarray:
        n = self.n
        a_bits = ((self.agent.rows[:, :, None] >> np.arange(WIDTH)) & 1).astype(np.float32).reshape(n, -1)
        heights_raw = self.agent.heights().astype(np.float32)
        heights = heights_raw / HEIGHT
        hold = np.zeros((n, 8), dtype=np.float32)
        valid_hold = self.hold_a >= 0
        hold[np.flatnonzero(valid_hold), self.hold_a[valid_hold]] = 1.0
        hold[:, 7] = self.can_hold_a.astype(np.float32)
        pos = self.pos_a % self.sequence_length
        preview = self.seq_a[np.arange(n)[:, None], (pos[:, None] + np.arange(PREVIEW)[None, :]) % self.sequence_length]
        prev = np.zeros((n, PREVIEW * 7), dtype=np.float32)
        for k in range(PREVIEW):
            prev[np.arange(n), k * 7 + preview[:, k]] = 1.0
        cur = np.zeros((n, 7), dtype=np.float32)
        cur[np.arange(n), self.current_a] = 1.0
        rot = np.zeros((n, 4), dtype=np.float32)
        rot[:, 0] = 1.0
        cs = self.clear_a
        combo = np.array([max(0, c.combo + 1) / 20.0 for c in cs], dtype=np.float32)
        b2b = np.array([1.0 if c.b2b > 0 else 0.0 for c in cs], dtype=np.float32)
        surge = np.array([c.surge / 20.0 for c in cs], dtype=np.float32)
        surge_flag = (surge > 0).astype(np.float32)
        lines = np.array([c.total_lines / 100.0 for c in cs], dtype=np.float32)
        attack = np.array([c.total_attack / 100.0 for c in cs], dtype=np.float32)
        metrics = self._metrics()
        scalars = np.stack(
            [
                combo,
                b2b,
                surge,
                surge_flag,
                (self.ready_a + self.pending_a) / 20.0,
                np.zeros(n, dtype=np.float32),
                np.zeros(n, dtype=np.float32),
                lines,
                attack,
                self.steps / max(1, self.max_pieces),
                metrics["max_height"] / HEIGHT,
                metrics["aggregate"] / (WIDTH * HEIGHT),
                metrics["holes"] / (WIDTH * HEIGHT),
                metrics["bumpiness"] / (WIDTH * HEIGHT),
                self.steps / max(1, self.max_pieces),
            ],
            axis=1,
        ).astype(np.float32)
        parts = [a_bits]
        if self.include_opponent:
            b_bits = ((self.opp.rows[:, :, None] >> np.arange(WIDTH)) & 1).astype(np.float32).reshape(n, -1)
            parts.append(b_bits)
        parts.append(heights)
        if self.include_opponent:
            parts.append(self.opp.heights().astype(np.float32) / HEIGHT)
        parts += [hold, prev, cur, rot, scalars]
        return np.concatenate(parts, axis=1)

    def close(self) -> None:
        return None


def make_batched_env(n_envs: int, seed: int, max_pieces: int = 400, include_opponent: bool = True) -> BatchedVersusEnv:
    return BatchedVersusEnv(n_envs=n_envs, seed=seed, max_pieces=max_pieces, include_opponent=include_opponent)
