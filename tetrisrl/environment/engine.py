"""Deterministic single-player game engine.

The engine is the single source of truth for mechanics.  It exposes:

* placement-based actions (:mod:`tetrisrl.environment.actions`),
* lock/clear/spin/b2b/surge/garbage resolution,
* a fully serialisable state for checkpoints and replay verification.

It knows nothing about RL, rewards, or rendering.  Opponent interactions live
in :mod:`tetrisrl.environment.versus`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .actions import ACTION_SPACE, Placement, decode_action
from .board import Board
from .garbage import AttackExchange, GarbageQueue
from .pieces import CELLS, LEFT_OFFSET, PIECE_NAMES, ActivePiece
from .placement import resolve_placement, spawn_x
from .randomizer import SevenBag
from .rotation import build_kick_tables, kick_tests
from .ruleset import RulesetConfig, load_ruleset
from .scoring import ClearComponents, ClearState, compute_clear, on_no_clear
from .spin_detection import SpinResult, detect_t_spin, rotation_legal_at_rest, spin_from_placement

VISIBLE_ROWS = 20


@dataclass
class StepResult:
    action: int = -1
    valid: bool = False
    piece: str = ""
    rotation: int = 0
    column: int = 0
    x: int = 0
    y: int = 0
    cells: Tuple[Tuple[int, int], ...] = ()
    hold_used: bool = False
    spin: bool = False
    mini: bool = False
    lines: int = 0
    cleared_rows: Tuple[int, ...] = ()
    perfect_clear: bool = False
    clear: Optional[ClearComponents] = None
    attack: int = 0
    attack_events: List[int] = field(default_factory=list)
    attack_breakdown: List[dict] = field(default_factory=list)
    cancelled: int = 0
    sent: int = 0
    garbage_inserted: int = 0
    garbage_events: List[dict] = field(default_factory=list)
    top_out: bool = False
    topped_out_reason: str = ""
    game_over: bool = False

    def to_event(self) -> dict:
        event = {
            "type": "place",
            "action": self.action,
            "piece": self.piece,
            "rotation": self.rotation,
            "column": self.column,
            "x": self.x,
            "y": self.y,
            "cells": [list(c) for c in self.cells],
            "hold": self.hold_used,
            "lines": self.lines,
            "cleared_rows": list(self.cleared_rows),
            "spin": self.spin,
            "mini": self.mini,
            "perfect_clear": self.perfect_clear,
            "attack": self.attack,
            "attack_events": self.attack_events,
            "cancelled": self.cancelled,
            "sent": self.sent,
            "garbage_inserted": self.garbage_inserted,
            "garbage_events": self.garbage_events,
            "top_out": self.top_out,
            "top_out_reason": self.topped_out_reason,
        }
        if self.clear is not None:
            event["clear"] = self.clear.as_dict()
        return event


class GameState:
    """A single player's complete game state."""

    def __init__(
        self,
        ruleset: RulesetConfig | str | dict = "tetrio_s2",
        seed: int = 0,
        garbage_seed: Optional[int] = None,
        piece_source: Any = None,
        player_id: int = 0,
        max_pieces: int = 100_000,
    ) -> None:
        self.ruleset = load_ruleset(ruleset)
        self.ruleset.validate()
        self.seed = int(seed)
        self.player_id = player_id
        self.max_pieces = max_pieces
        bc = self.ruleset.board
        self.board = Board(width=bc.width, height=bc.height, visible_height=bc.visible_height)
        self.piece_source = piece_source if piece_source is not None else SevenBag(seed, preview=bc.preview)
        self.kick_tables = build_kick_tables(self.ruleset.rotation.preset)
        self.garbage = GarbageQueue(
            self.ruleset.garbage,
            width=bc.width,
            seed=garbage_seed if garbage_seed is not None else (seed ^ 0x9E3779B97F4A7C15) & 0xFFFFFFFF,
        )
        self.clear_state = ClearState()
        self.current: Optional[ActivePiece] = None
        self.hold: Optional[str] = None
        self.can_hold = True
        self.spawn_count = 0
        self.pieces_placed = 0
        self.hold_count = 0
        self.top_out = False
        self.topped_out_reason = ""
        self.finished = False
        self.garbage_sent = 0
        self.garbage_received = 0
        self.garbage_inserted = 0
        self.incoming_history: List[int] = []
        self.outgoing_history: List[int] = []
        self.events: List[dict] = []
        self._placement_cache: Optional[Dict[int, Placement]] = None
        self._hold_piece_cache: Optional[str] = None
        self.spawn()

    # ------------------------------------------------------------------
    # Piece lifecycle
    # ------------------------------------------------------------------
    def next_piece_name(self) -> str:
        return self.piece_source.next()

    def preview(self, n: int) -> List[str]:
        return list(self.piece_source.peek(n))

    def spawn(self) -> bool:
        name = self.next_piece_name()
        bc = self.ruleset.board
        sx = self._spawn_x(name)
        sy = bc.spawn_y
        piece = ActivePiece(name, 0, sx, sy)
        self.current = piece
        self.spawn_count += 1
        self.can_hold = True
        self.invalidate()
        if not self.board.fits(piece.cells()):
            self._top_out("block_out")
            return False
        return True

    def _spawn_x(self, name: str) -> int:
        return spawn_x(name)

    def hold_swap(self) -> bool:
        if not self.can_hold or self.current is None:
            return False
        current_name = self.current.name
        if self.hold is None:
            self.hold = current_name
            # The held piece takes the current piece's slot; the next piece
            # comes from the bag.
            name = self.next_piece_name()
            piece = ActivePiece(name, 0, self._spawn_x(name), self.ruleset.board.spawn_y)
        else:
            name = self.hold
            self.hold = current_name
            piece = ActivePiece(name, 0, self._spawn_x(name), self.ruleset.board.spawn_y)
        self.current = piece
        self.can_hold = False
        self.hold_count += 1
        self.invalidate()
        if not self.board.fits(piece.cells()):
            self._top_out("block_out")
            return False
        return True

    # ------------------------------------------------------------------
    # Placement resolution
    # ------------------------------------------------------------------
    def _drop(self, name: str, rotation: int, column: int) -> Optional[Tuple[int, int, Tuple[Tuple[int, int], ...]]]:
        """Resolve rotation+column to a hard-dropped position, or ``None``."""
        if not (0 <= rotation <= 3) or not (0 <= column < self.ruleset.board.width):
            return None
        bc = self.ruleset.board
        return resolve_placement(
            self.board,
            self.kick_tables[name],
            name,
            rotation,
            column,
            bc.spawn_y,
            bc.width,
        )

    def resolve(self, action: int) -> Optional[Placement]:
        return self._placements().get(action)

    def _build_placement_cache(self) -> Dict[int, Placement]:
        cache: Dict[int, Placement] = {}
        if self.finished or self.top_out or self.current is None:
            return cache
        width = self.ruleset.board.width
        current_name = self.current.name
        hold_name = None if self.hold is None else self.hold
        if self.can_hold and self.hold is None:
            preview = self.preview(1)
            hold_name = preview[0] if preview else None

        def resolve_named(name: str, rotation: int, column: int, action: int, use_hold: bool) -> Optional[Placement]:
            res = self._drop(name, rotation, column)
            if res is None:
                return None
            x, y, cells = res
            return Placement(action, name, rotation, column, x, y, cells, use_hold)

        for rotation in range(4):
            for column in range(width):
                base = rotation * 20 + column * 2
                placement = resolve_named(current_name, rotation, column, base, False)
                if placement is not None:
                    cache[base] = placement
                if self.can_hold and hold_name is not None:
                    held = resolve_named(hold_name, rotation, column, base + 1, True)
                    if held is not None:
                        cache[base + 1] = held
        return cache

    def _placements(self) -> Dict[int, Placement]:
        if self._placement_cache is None:
            self._placement_cache = self._build_placement_cache()
        return self._placement_cache

    def legal_actions(self) -> List[int]:
        return sorted(self._placements())

    def invalidate(self) -> None:
        self._placement_cache = None

    def action_mask(self) -> List[bool]:
        mask = [False] * ACTION_SPACE
        for a in self.legal_actions():
            mask[a] = True
        return mask

    # ------------------------------------------------------------------
    # Stepping
    # ------------------------------------------------------------------
    def apply_action(self, action: int) -> StepResult:
        result = StepResult(action=action)
        if self.finished or self.top_out:
            result.top_out = self.top_out
            result.game_over = True
            return result
        rotation, column, hold = decode_action(action)
        if hold and not self.can_hold:
            return result

        if hold:
            if not self.hold_swap():
                result.valid = True
                result.top_out = True
                result.topped_out_reason = self.topped_out_reason
                result.game_over = True
                return result
            result.hold_used = True
            # The hold swap already happened; resolve the *new* current piece
            # using the same rotation/column (ignore the hold bit).
            action_for_placement = action & ~1
        else:
            action_for_placement = action

        placement = self.resolve(action_for_placement)
        if placement is None:
            return result
        result.valid = True
        result.piece = placement.piece
        result.rotation = placement.rotation
        result.column = placement.column
        result.x = placement.x
        result.y = placement.y
        result.cells = placement.cells

        spin_res: SpinResult = spin_from_placement(
            self.board,
            placement.piece,
            placement.rotation,
            placement.x,
            placement.y,
            detection=self.ruleset.spin.detection,
            all_mini=self.ruleset.spin.all_mini,
            kick_table=self.kick_tables[placement.piece],
            rotation_used=placement.rotation != 0,
        )
        if not spin_res.spin and self.ruleset.spin.non_t_spins and placement.piece != "T":
            spin_res = SpinResult(False, False, "none")

        # Lock.
        self.board.lock(placement.cells)
        result.spin = spin_res.spin
        result.mini = spin_res.mini

        cleared = self.board.clear_lines()
        result.lines = len(cleared)
        result.cleared_rows = tuple(cleared)
        perfect = result.lines > 0 and self.board.is_empty()
        result.perfect_clear = perfect

        attack_events: List[int] = []
        if result.lines > 0:
            comp = compute_clear(
                self.ruleset,
                self.clear_state,
                result.lines,
                result.spin,
                result.mini,
                perfect,
            )
            result.clear = comp
            attack_events = list(comp.attack_events)
        else:
            attack_events = on_no_clear(self.ruleset, self.clear_state)

        # Each attack event cancels pending garbage independently and, whichever
        # part is not absorbed, is sent to the opponent (FIFO, partial).
        cancelled_total = 0
        sent_total = 0
        breakdown: List[dict] = []
        for event_amount in attack_events:
            if event_amount <= 0:
                continue
            if self.ruleset.garbage.cancel_incoming:
                cancelled, sent = self.garbage.cancel(event_amount)
            else:
                cancelled, sent = 0, event_amount
            cancelled_total += cancelled
            sent_total += sent
            breakdown.append({"amount": event_amount, "cancelled": cancelled, "sent": sent})
        result.attack = sum(max(0, a) for a in attack_events)
        result.attack_events = list(attack_events)
        result.attack_breakdown = breakdown
        result.cancelled = cancelled_total
        result.sent = sent_total
        self.garbage_sent += sent_total
        self.outgoing_history.append(sent_total)
        if len(self.outgoing_history) > 32:
            self.outgoing_history = self.outgoing_history[-32:]

        # Incoming garbage becomes active over time and enters on a lock that
        # clears no lines (TETR.IO tank behaviour).
        self.garbage.tick(1)
        if result.lines == 0 and not self.garbage.is_empty():
            combo_blocked = self.ruleset.garbage.combo_blocking and self.clear_state.combo > -1
            if not combo_blocked:
                inserted, garbage_events = self.garbage.tank(
                    self.board, self.ruleset.garbage.tank_cap
                )
                result.garbage_inserted = inserted
                result.garbage_events = garbage_events
                self.garbage_inserted += inserted
                if inserted:
                    self.garbage_received += inserted
                    self.incoming_history.append(inserted)
                    if len(self.incoming_history) > 32:
                        self.incoming_history = self.incoming_history[-32:]

        self.pieces_placed += 1
        self.invalidate()

        # Lock out: the whole piece locked in the hidden buffer.
        if self.ruleset.lock_out and placement.cells:
            visible_top = self.ruleset.board.height - self.ruleset.board.visible_height
            if all(y < visible_top for _, y in placement.cells):
                self._top_out("lock_out")
                result.top_out = True
                result.topped_out_reason = self.topped_out_reason
                result.game_over = True
                return result

        if self.ruleset.garbage_top_out and any(ev.get("overflow") for ev in result.garbage_events):
            self._top_out("garbage_overflow")
            result.top_out = True
            result.topped_out_reason = self.topped_out_reason
            result.game_over = True
            return result

        # Spawn the next piece; failure is a block-out.
        if not self.spawn():
            result.top_out = True
            result.topped_out_reason = self.topped_out_reason
            result.game_over = True
        elif self.pieces_placed >= self.max_pieces:
            self.finished = True
            result.game_over = True
        return result

    def _top_out(self, reason: str) -> None:
        self.top_out = True
        self.finished = True
        self.topped_out_reason = reason

    # ------------------------------------------------------------------
    # Competitive exchange helpers
    # ------------------------------------------------------------------
    def receive_attack(self, amount: int) -> int:
        if amount <= 0:
            return 0
        return self.garbage.add(amount)

    def exchange_attack(self, attack: int) -> AttackExchange:
        """Cancel incoming garbage with ``attack`` and return the exchange.

        The caller is responsible for sending ``exchange.sent`` to the opponent.
        """
        before = self.garbage.total()
        if attack <= 0:
            return AttackExchange(attack=0, cancelled=0, sent=0, incoming_before=before, incoming_after=before)
        cancelled, remaining = self.garbage.cancel(attack)
        return AttackExchange(
            attack=attack,
            cancelled=cancelled,
            sent=remaining,
            incoming_before=before,
            incoming_after=self.garbage.total(),
        )

    # ------------------------------------------------------------------
    # Observation-facing properties (never leak hidden randomizer state)
    # ------------------------------------------------------------------
    @property
    def pending_garbage(self) -> int:
        return self.garbage.total()

    @property
    def combo(self) -> int:
        return self.clear_state.combo

    @property
    def b2b_active(self) -> bool:
        return self.clear_state.b2b > 0

    @property
    def b2b_count(self) -> int:
        return self.clear_state.b2b

    @property
    def b2b_charge(self) -> float:
        return float(self.clear_state.b2b)

    @property
    def surge_pending(self) -> bool:
        return self.clear_state.surge > 0

    @property
    def surge_value(self) -> int:
        return self.clear_state.surge

    def visible_rows(self) -> List[int]:
        top = self.ruleset.board.height - self.ruleset.board.visible_height
        return self.board.rows[top:]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def state_dict(self) -> Dict[str, Any]:
        return {
            "ruleset": self.ruleset.to_dict(),
            "seed": self.seed,
            "player_id": self.player_id,
            "board_rows": list(self.board.rows),
            "current": None
            if self.current is None
            else {"name": self.current.name, "rotation": self.current.rotation, "x": self.current.x, "y": self.current.y},
            "hold": self.hold,
            "can_hold": self.can_hold,
            "piece_source": self.piece_source.state_dict() if hasattr(self.piece_source, "state_dict") else None,
            "garbage": self.garbage.state_dict(),
            "clear_state": {
                "combo": self.clear_state.combo,
                "b2b": self.clear_state.b2b,
                "surge": self.clear_state.surge,
                "total_attack": self.clear_state.total_attack,
                "total_lines": self.clear_state.total_lines,
                "b2b_breaks": self.clear_state.b2b_breaks,
                "surges_released": self.clear_state.surges_released,
                "tspins": self.clear_state.tspins,
                "mini_tspins": self.clear_state.mini_tspins,
                "tetrises": self.clear_state.tetrises,
                "perfect_clears": self.clear_state.perfect_clears,
                "max_combo": self.clear_state.max_combo,
                "difficult_clears": self.clear_state.difficult_clears,
                "max_b2b": self.clear_state.max_b2b,
            },
            "pieces_placed": self.pieces_placed,
            "spawn_count": self.spawn_count,
            "hold_count": self.hold_count,
            "top_out": self.top_out,
            "topped_out_reason": self.topped_out_reason,
            "finished": self.finished,
            "garbage_sent": self.garbage_sent,
            "garbage_received": self.garbage_received,
            "garbage_inserted": self.garbage_inserted,
            "incoming_history": list(self.incoming_history),
            "outgoing_history": list(self.outgoing_history),
        }

    def load_state_dict(self, state: Dict[str, Any]) -> None:
        from .randomizer import SevenBag

        self.seed = int(state["seed"])
        self.player_id = int(state.get("player_id", 0))
        self.board.rows = list(state["board_rows"])
        cur = state.get("current")
        self.current = None if cur is None else ActivePiece(cur["name"], cur["rotation"], cur["x"], cur["y"])
        self.hold = state.get("hold")
        self.can_hold = bool(state["can_hold"])
        if state.get("piece_source") is not None:
            if not isinstance(self.piece_source, SevenBag):
                self.piece_source = SevenBag(self.seed, preview=self.ruleset.board.preview)
            self.piece_source.load_state_dict(state["piece_source"])
        self.garbage.load_state_dict(state["garbage"])
        cs = state["clear_state"]
        self.clear_state = ClearState(**{k: v for k, v in cs.items() if hasattr(ClearState, k)})
        self.pieces_placed = int(state["pieces_placed"])
        self.spawn_count = int(state.get("spawn_count", 0))
        self.hold_count = int(state.get("hold_count", 0))
        self.top_out = bool(state["top_out"])
        self.topped_out_reason = state.get("topped_out_reason", "")
        self.finished = bool(state["finished"])
        self.garbage_sent = int(state.get("garbage_sent", 0))
        self.garbage_received = int(state.get("garbage_received", 0))
        self.garbage_inserted = int(state.get("garbage_inserted", 0))
        self.incoming_history = list(state.get("incoming_history", []))
        self.outgoing_history = list(state.get("outgoing_history", []))

    def snapshot(self, max_events: int = 0) -> Dict[str, Any]:
        """Compact state useful for replay frames."""
        return {
            "rows": list(self.board.rows),
            "current": None
            if self.current is None
            else {"name": self.current.name, "rotation": self.current.rotation, "x": self.current.x, "y": self.current.y},
            "hold": self.hold,
            "next": self.preview(5),
            "combo": self.combo,
            "b2b": self.clear_state.b2b,
            "b2b_charge": self.surge_value,
            "surge": self.surge_pending,
            "pending_garbage": self.pending_garbage,
            "lines": self.clear_state.total_lines,
            "attack": self.clear_state.total_attack,
            "pieces": self.pieces_placed,
            "top_out": self.top_out,
        }
