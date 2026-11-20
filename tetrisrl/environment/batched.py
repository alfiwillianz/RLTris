"""Batched (NumPy) Tetris engine core.

Motivation
----------
The reference engine (:mod:`tetrisrl.environment.engine`) is a scalar Python
implementation: correct, auditable, and deliberately the single source of truth
for the ruleset.  It runs at a few hundred placements per second, which caps
experiment throughput.  This module is a *vectorised* placement/board core that
processes ``N`` independent boards at once with NumPy.

What is vectorised
------------------
* hard-drop placement resolution for all 80 actions and all boards (exact, using
  per-column first-block rows - no height-table approximation),
* locking, line clearing (stable compaction), garbage insertion,
* action masks.

What is deliberately **not** vectorised yet
------------------------------------------
* SRS rotation kicks in the spawn area and spin-in (rotation-at-rest) resolution,
* spin detection, B2B charging/surge accounting, versus attack exchange,
  observation/reward assembly.

Consequences: the batched engine is a *placement and board* backend.  It is
validated against the reference engine by differential tests and is intended for
high-throughput pretraining or mask computation.  Headline experiments continue
to use the reference engine until the remaining logic is ported and re-verified.
See ``docs/ARCHITECTURE.md`` ("Batched backend") for the integration plan.

Coordinate conventions match the reference engine: rows are 10-bit masks, row 0
is the top of the 40-row board.
"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from .pieces import CELLS, LEFT_OFFSET, PIECE_NAMES
from .rotation import build_kick_tables, kick_tests
from .placement import rotation_direction
from .ruleset import RulesetConfig, load_ruleset

N_ACTIONS = 80
WIDTH = 10
HEIGHT = 40

#: Padded cell table: ``CELLS_PAD[piece_id, rotation, cell] = (dx, dy)`` with
#: unused slots set to ``(-1, -1)``.
CELLS_PAD = np.full((7, 4, 4, 2), -1, dtype=np.int16)
for _pi, _name in enumerate(PIECE_NAMES):
    for _rot in range(4):
        for _ci, (_dx, _dy) in enumerate(CELLS[_name][_rot]):
            CELLS_PAD[_pi, _rot, _ci] = (_dx, _dy)

LEFT_OFFSET_NP = np.array([[LEFT_OFFSET[name][r] for r in range(4)] for name in PIECE_NAMES], dtype=np.int16)
PIECE_INDEX = {name: i for i, name in enumerate(PIECE_NAMES)}

#: Rotation-at-rest (spin-in) sources, identical to the reference resolver.
SPIN_SOURCES = {1: (2, 0), 2: (1, 3), 3: (0, 2)}
SPIN_IN_PIECE_IDS = (PIECE_INDEX["T"],)


class BatchedBoard:
    """``N`` independent 10x40 boards with vectorised placement resolution."""

    def __init__(self, n: int, ruleset: RulesetConfig | str | dict = "tetrio_s2", spawn_y: int = 18) -> None:
        self.n = int(n)
        self.ruleset = load_ruleset(ruleset)
        self.rows = np.zeros((self.n, HEIGHT), dtype=np.uint16)
        self.pieces = np.zeros(self.n, dtype=np.int16)
        self.spawn_y = int(spawn_y)
        self.kick_tables = build_kick_tables(self.ruleset.rotation.preset)
        self.spin_in_used = np.zeros((self.n, N_ACTIONS), dtype=bool)
        self.full_row = (1 << WIDTH) - 1

    # ------------------------------------------------------------------
    # Placement resolution
    # ------------------------------------------------------------------
    def _column_obstacles(self) -> np.ndarray:
        """First filled row (>= spawn_y) per board/column, or HEIGHT if none.

        Exact for vertical drops: a piece cell descending in column ``c`` stops
        at the first filled row below the spawn line.
        """
        bits = ((self.rows[:, :, None] >> np.arange(WIDTH, dtype=np.uint16)) & 1).astype(bool)
        bits[:, : self.spawn_y, :] = False
        any_block = bits.any(axis=1)
        first = bits.argmax(axis=1).astype(np.int16)  # first True from the top
        first = np.where(any_block, first, HEIGHT)
        return first  # [N, 10]

    def resolve_actions(self, piece_ids: np.ndarray | None = None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Resolve every action for every board (vectorised over actions too).

        Returns ``(valid [N,80], ys [N,80], cells [N,80,4,2])``.
        """
        n = self.n
        pieces = self.pieces if piece_ids is None else np.asarray(piece_ids, dtype=np.int16)
        obstacles = self._column_obstacles()  # [N, 10]
        self.spin_in_used[:] = False

        actions = np.arange(N_ACTIONS, dtype=np.int16)
        rot = (actions // 20).astype(np.int16)          # [80]
        col = ((actions // 2) % 10).astype(np.int16)    # [80]

        x = col[None, :] - LEFT_OFFSET_NP[pieces[:, None], rot[None, :]]  # [N,80]
        dx = CELLS_PAD[pieces[:, None], rot[None, :], :, 0].astype(np.int16)  # [N,80,4]
        dy = CELLS_PAD[pieces[:, None], rot[None, :], :, 1].astype(np.int16)
        real = dx >= 0
        cols = x[:, :, None] + dx                      # [N,80,4]
        inside = real & (cols >= 0) & (cols < WIDTH)
        safe = np.clip(cols, 0, WIDTH - 1)

        block = obstacles[np.arange(n)[:, None, None], safe]  # [N,80,4]
        land = block - dy - 1
        land = np.where(inside, land, HEIGHT)
        y = land.min(axis=2)                           # [N,80]

        spawn_r = self.spawn_y + dy
        spawn_occ = (self.rows[np.arange(n)[:, None, None], np.clip(spawn_r, 0, HEIGHT - 1)] >> safe.astype(np.uint16)) & 1
        spawn_ok = (
            inside
            & (spawn_r >= 0)
            & (spawn_r < HEIGHT)
            & (spawn_occ == 0)
        ).all(axis=2)
        ok = spawn_ok & (y >= self.spawn_y) & (y + dy.max(axis=2) < HEIGHT)
        y = np.where(ok, y, -1).astype(np.int16)

        cells = np.stack([x[:, :, None] + dx, y[:, :, None] + dy], axis=3)
        cells = np.where(ok[:, :, None, None], cells, -1).astype(np.int16)
        self._apply_spin_in(pieces, obstacles, ok, y, cells)
        return ok, y, cells

    # ------------------------------------------------------------------
    # Spin-in (rotation-at-rest) resolution, ported from the reference engine
    # ------------------------------------------------------------------
    @staticmethod
    def _fits_cells(rows_sub: np.ndarray, cells: np.ndarray) -> np.ndarray:
        """Collision test for ``[M,K,4,2]`` candidate cells."""
        x = cells[..., 0]
        y = cells[..., 1]
        inside = (x >= 0) & (x < WIDTH) & (y >= 0) & (y < HEIGHT)
        occ = (
            rows_sub[np.arange(rows_sub.shape[0])[:, None, None], np.clip(y, 0, HEIGHT - 1)]
            >> np.clip(x, 0, WIDTH - 1).astype(np.uint16)
        ) & 1
        return inside.all(axis=-1) & (occ == 0).all(axis=-1)

    def _apply_spin_in(self, pieces, obstacles, valid, ys, cells) -> None:
        """Apply T spin-in candidates to both action parities (vectorised over columns)."""
        t_row = np.flatnonzero(pieces == PIECE_INDEX["T"])
        if t_row.size == 0:
            return
        piece = PIECE_INDEX["T"]
        rows_sub = self.rows[t_row]
        obstacles_sub = obstacles[t_row]
        table = self.kick_tables["T"]
        m = t_row.size
        cols = np.arange(WIDTH, dtype=np.int16)

        for rotation in (1, 2, 3):
            actions = rotation * 20 + cols * 2
            origin_x = (cols - LEFT_OFFSET_NP[piece, rotation]).astype(np.int16)  # [10]
            tdx = CELLS_PAD[piece, rotation, :, 0].astype(np.int16)
            tdy = CELLS_PAD[piece, rotation, :, 1].astype(np.int16)
            base_y = ys[t_row][:, actions]                      # [M,10]
            base_cells = cells[t_row][:, actions]               # [M,10,4,2]
            best_y = base_y.copy()
            best_cells = base_cells.copy()
            best_bottom = np.where(base_y >= 0, base_y + int(tdy.max()), -1)

            for source in SPIN_SOURCES[rotation]:
                sdx = CELLS_PAD[piece, source, :, 0].astype(np.int16)
                sdy = CELLS_PAD[piece, source, :, 1].astype(np.int16)
                s_cols = origin_x[:, None] + sdx[None, :]        # [10,4]
                s_inside = (sdx >= 0)[None, :] & (s_cols >= 0) & (s_cols < WIDTH)
                s_safe = np.clip(s_cols, 0, WIDTH - 1)
                block = obstacles_sub[:, s_safe]                  # [M,10,4]
                s_land = np.where(s_inside[None, :, :], block - sdy[None, None, :] - 1, HEIGHT)
                s_y = s_land.min(axis=-1)                         # [M,10]
                spawn_r = self.spawn_y + sdy
                spawn_occ = (
                    rows_sub[np.arange(m)[:, None, None], np.clip(spawn_r, 0, HEIGHT - 1)[None, None, :]]
                    >> s_safe.astype(np.uint16)[None, :, :]
                ) & 1
                spawn_ok = (
                    s_inside[None, :, :]
                    & (spawn_r[None, None, :] >= 0)
                    & (spawn_r[None, None, :] < HEIGHT)
                    & (spawn_occ == 0)
                ).all(axis=-1)
                s_ok = spawn_ok & (s_y >= self.spawn_y)

                direction = rotation_direction((rotation - source) % 4)
                for dx, dy_up in kick_tests(table, source, direction):
                    cand_x = origin_x[:, None] + dx + tdx[None, :]      # [10,4]
                    cand_y = (s_y - dy_up)[:, :, None] + tdy[None, None, :]  # [M,10,4]
                    cand = np.stack(
                        [np.broadcast_to(cand_x[None, :, :], cand_y.shape), cand_y], axis=3
                    )
                    fits = self._fits_cells(rows_sub, cand)
                    resting = ~self._fits_cells(rows_sub, cand + np.array([0, 1], dtype=np.int16))
                    leftmost_ok = cand_x.min(axis=1) == cols
                    ok = s_ok & fits & resting & leftmost_ok[None, :]
                    bottom = np.where(ok, cand_y.max(axis=-1), -1)
                    improve = bottom > best_bottom
                    if not improve.any():
                        continue
                    best_bottom = np.where(improve, bottom, best_bottom)
                    best_y = np.where(improve, s_y - dy_up, best_y)
                    best_cells = np.where(improve[:, :, None, None], cand, best_cells)
                    self.spin_in_used[t_row[:, None], (actions + 0)[None, :]] |= improve
                    self.spin_in_used[t_row[:, None], (actions + 1)[None, :]] |= improve

            for parity in (0, 1):
                action_ids = actions + parity
                ys[t_row[:, None], action_ids[None, :]] = best_y
                cells[t_row[:, None], action_ids[None, :]] = best_cells
                valid[t_row[:, None], action_ids[None, :]] = best_y >= 0

    def _piece_for_action(self, action: int) -> np.ndarray:
        """Piece id per board for an action (hold is resolved by the caller)."""
        return self.pieces

    # ------------------------------------------------------------------
    # Board mutation
    # ------------------------------------------------------------------
    def lock(self, cells: np.ndarray, board_index: np.ndarray | None = None) -> None:
        """Lock one placement per board. ``cells`` shape ``[B,4,2]``."""
        idx = np.arange(self.n) if board_index is None else board_index
        for k in range(4):
            x = cells[:, k, 0]
            y = cells[:, k, 1]
            ok = (x >= 0) & (y >= 0)
            if not ok.any():
                continue
            rows = np.clip(y, 0, HEIGHT - 1)
            self.rows[idx[ok], rows[ok]] |= (np.uint16(1) << x[ok].astype(np.uint16))

    def clear_lines(self) -> np.ndarray:
        """Clear full rows, returning the number of cleared lines per board."""
        full = self.rows == self.full_row
        counts = full.sum(axis=1).astype(np.int16)
        order = np.argsort(full, axis=1, kind="stable")
        kept = np.take_along_axis(self.rows, order, axis=1)
        src = np.arange(HEIGHT)[None, :] - counts[:, None]
        valid = src >= 0
        gathered = kept[np.arange(self.n)[:, None], np.clip(src, 0, HEIGHT - 1)]
        self.rows = np.where(valid, gathered, 0).astype(np.uint16)
        return counts

    def insert_garbage(self, amounts: np.ndarray, holes: np.ndarray) -> np.ndarray:
        """Insert ``amounts[i]`` garbage rows with ``holes[i]``; returns overflow."""
        out = np.zeros_like(self.rows)
        overflow = np.zeros(self.n, dtype=bool)
        for i in range(self.n):
            k = int(amounts[i])
            if k <= 0:
                out[i] = self.rows[i]
                continue
            k = min(k, HEIGHT)
            overflow[i] = bool(self.rows[i, :k].any())
            out[i, : HEIGHT - k] = self.rows[i, k:]
            mask = np.uint16(self.full_row & ~(1 << int(holes[i])))
            out[i, HEIGHT - k :] = mask
        self.rows = out
        return overflow

    def insert_garbage_one(self, board_index: int, amount: int, hole: int) -> bool:
        """Insert garbage into a single board; returns True on overflow."""
        k = min(int(amount), HEIGHT)
        if k <= 0:
            return False
        row = self.rows[board_index]
        overflow = bool(row[:k].any())
        self.rows[board_index, : HEIGHT - k] = row[k:]
        self.rows[board_index, HEIGHT - k :] = np.uint16(self.full_row & ~(1 << int(hole)))
        return overflow

    def state_hash(self) -> np.ndarray:
        """64-bit FNV-1a hash per board (matches the reference board hash)."""
        h = np.full(self.n, 1469598103934665603, dtype=np.uint64)
        for y in range(HEIGHT):
            h ^= self.rows[:, y].astype(np.uint64)
            h *= np.uint64(1099511628211)
        return h

    def heights(self) -> np.ndarray:
        """Column heights measured from the floor (0 = empty column)."""
        bits = ((self.rows[:, :, None] >> np.arange(WIDTH)) & 1).astype(bool)
        any_block = bits.any(axis=1)
        first = np.where(any_block, bits.argmax(axis=1), HEIGHT)
        return (HEIGHT - first).astype(np.int16)
