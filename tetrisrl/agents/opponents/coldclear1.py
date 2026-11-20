"""Cold Clear (the original) as a versus opponent through its C ABI.

Cold Clear is driven through the ``cdylib`` built from its ``c-api`` crate
(``libcold_clear.so``).  Unlike the Tetris Bot Protocol used for Cold Clear 2 in
:mod:`tetrisrl.agents.opponents.tbp`, the C API has a per-move
``incoming`` garbage parameter, so this opponent can plan around garbage that is
already pending against it.

Scope and honesty notes
-----------------------
* Cold Clear is a **placement suggester**, not a simulator.  ``tetrisrl`` owns
  the board, attack table, pending garbage, cancellation, B2B charging, Surge
  and top-out.  The engine only receives a board snapshot, hold, queue,
  B2B/combo flags and a count of incoming garbage lines.
* The C API is a *stateful* async bot.  This adapter deliberately launches one
  bot per decision (``cc_launch_with_board_async`` → ``cc_request_next_move`` →
  ``cc_poll_next_move`` → ``cc_destroy_async``).  ``cc_reset_async`` cannot
  update the hold piece and only resets the board/B2B/combo, so a fresh launch
  is the only way to guarantee that the engine sees exactly our state — and it
  is also what makes the per-call ``incoming`` argument safe.  The cost is that
  its search tree is rebuilt for every piece (as with the TBP adapter).
* Cold Clear implements **guideline SRS**, not TETR.IO SRS+, and has **no 180°
  rotation** (``libtetris`` exposes ``Cw``/``Ccw`` only).  Its attack and B2B
  model is pre-Season-2 (boolean B2B, additive combo) and is not used: our
  arena scores every placement.
* Suggested cells are matched geometrically against
  :meth:`GameState.legal_actions`.  A suggestion our hard-drop action space
  cannot express (e.g. a tuck that needs mid-air movement outside the spin-in
  resolution) falls back to the in-repo heuristic and is counted.
* Importing this module, constructing an agent, and collecting pytest tests
  never load the shared library.  Loading is lazy and, under pytest, refused
  unless ``allow_in_tests=True`` is passed explicitly.

The upstream library is MPL-2.0.  It is used strictly by dynamic linking; no
Cold Clear source is copied into this file or any other ``tetrisrl`` file.  See
``third_party/COLD_CLEAR_NOTICE.md``.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..base import BaseAgent
from ..heuristic_agent import HeuristicAgent
from ...environment.board import Board
from ...environment.engine import GameState

#: Cold Clear's fixed board geometry: 10 columns x 40 rows.
CC_WIDTH = 10
CC_HEIGHT = 40

#: ``CCPiece`` values from ``c-api/coldclear.h``.
CC_PIECE_IDS: Dict[str, int] = {"I": 0, "O": 1, "T": 2, "L": 3, "J": 4, "S": 5, "Z": 6}

#: ``CCMovementMode`` values from ``c-api/coldclear.h``.
CC_MOVEMENT_MODES: Dict[str, int] = {"zero_g": 0, "twenty_g": 1, "hard_drop_only": 2}

#: ``CCSpawnRule`` values from ``c-api/coldclear.h``.
CC_SPAWN_RULES: Dict[str, int] = {"row19_or_20": 0, "row21_and_fall": 1}

#: ``CCBotPollStatus`` values.
CC_MOVE_PROVIDED = 0
CC_WAITING = 1
CC_BOT_DEAD = 2

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIBRARY = _REPO_ROOT / "third_party" / "cold-clear" / "target" / "release" / "libcold_clear.so"


class ColdClear1Error(RuntimeError):
    """Base class for adapter/library failures."""


class ColdClear1Unavailable(ColdClear1Error):
    """The shared library is missing, disabled, or refused by the test guard."""


class ColdClear1Timeout(ColdClear1Error):
    """The engine did not produce a move before the deadline."""


class ColdClear1Dead(ColdClear1Error):
    """The engine reported ``CC_BOT_DEAD`` (no survivable placement)."""


def _pytest_active() -> bool:
    return "pytest" in sys.modules or "_pytest" in sys.modules


def coldclear1_binary_path(library: Optional[str | os.PathLike[str]] = None) -> Path:
    """Resolve the Cold Clear C library path (argument, env override, default)."""
    if library is not None:
        return Path(library).expanduser()
    env = os.environ.get("TETRISRL_COLDCLEAR1_LIB")
    if env:
        return Path(env).expanduser()
    return DEFAULT_LIBRARY


def coldclear1_available(library: Optional[str | os.PathLike[str]] = None) -> bool:
    """Whether the shared library exists (the library is not loaded here)."""
    return coldclear1_binary_path(library).is_file()


# ---------------------------------------------------------------------------
# ctypes mirror of c-api/coldclear.h
# ---------------------------------------------------------------------------
class CCMovement(ctypes.c_int):
    pass


class CCOptions(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("spawn_rule", ctypes.c_int),
        ("pcloop", ctypes.c_int),
        ("min_nodes", ctypes.c_uint32),
        ("max_nodes", ctypes.c_uint32),
        ("threads", ctypes.c_uint32),
        ("use_hold", ctypes.c_bool),
        ("speculate", ctypes.c_bool),
    ]


class CCWeights(ctypes.Structure):
    _fields_ = [
        ("back_to_back", ctypes.c_int32),
        ("bumpiness", ctypes.c_int32),
        ("bumpiness_sq", ctypes.c_int32),
        ("row_transitions", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("top_half", ctypes.c_int32),
        ("top_quarter", ctypes.c_int32),
        ("jeopardy", ctypes.c_int32),
        ("cavity_cells", ctypes.c_int32),
        ("cavity_cells_sq", ctypes.c_int32),
        ("overhang_cells", ctypes.c_int32),
        ("overhang_cells_sq", ctypes.c_int32),
        ("covered_cells", ctypes.c_int32),
        ("covered_cells_sq", ctypes.c_int32),
        ("tslot", ctypes.c_int32 * 4),
        ("well_depth", ctypes.c_int32),
        ("max_well_depth", ctypes.c_int32),
        ("well_column", ctypes.c_int32 * 10),
        ("b2b_clear", ctypes.c_int32),
        ("clear1", ctypes.c_int32),
        ("clear2", ctypes.c_int32),
        ("clear3", ctypes.c_int32),
        ("clear4", ctypes.c_int32),
        ("tspin1", ctypes.c_int32),
        ("tspin2", ctypes.c_int32),
        ("tspin3", ctypes.c_int32),
        ("mini_tspin1", ctypes.c_int32),
        ("mini_tspin2", ctypes.c_int32),
        ("perfect_clear", ctypes.c_int32),
        ("combo_garbage", ctypes.c_int32),
        ("move_time", ctypes.c_int32),
        ("wasted_t", ctypes.c_int32),
        ("use_bag", ctypes.c_bool),
        ("timed_jeopardy", ctypes.c_bool),
        ("stack_pc_damage", ctypes.c_bool),
    ]


class CCMove(ctypes.Structure):
    """``struct CCMove`` from ``c-api/coldclear.h``.

    ``expected_x``/``expected_y`` are absolute cell coordinates with ``(0, 0)``
    at the **bottom-left** of Cold Clear's board.  ``movement_count`` /
    ``movements`` describe a key path that this adapter does not replay; only the
    expected cells and the hold flag are used.
    """

    _fields_ = [
        ("hold", ctypes.c_bool),
        ("expected_x", ctypes.c_uint8 * 4),
        ("expected_y", ctypes.c_uint8 * 4),
        ("movement_count", ctypes.c_uint8),
        ("movements", ctypes.c_int * 32),
        ("nodes", ctypes.c_uint32),
        ("depth", ctypes.c_uint32),
        ("original_rank", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class ColdClear1Move:
    """A validated engine suggestion in *our* top-down board coordinates."""

    hold: bool
    cells: Tuple[Tuple[int, int], ...]
    nodes: int = 0
    depth: int = 0
    original_rank: int = 0
    movement_count: int = 0
    movements: Tuple[int, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hold": self.hold,
            "cells": [list(cell) for cell in self.cells],
            "nodes": self.nodes,
            "depth": self.depth,
            "original_rank": self.original_rank,
            "movement_count": self.movement_count,
            "movements": list(self.movements),
        }


# ---------------------------------------------------------------------------
# Board / move conversion
# ---------------------------------------------------------------------------
def board_to_field(board: Board) -> List[bool]:
    """Encode our top-down board as Cold Clear's 400-bool field.

    Index 0 is the bottom-left cell, row-major
    (``index = y_bottom_up * 10 + x``), exactly as ``cc_launch_with_board_async``
    documents.  Our ``Board.rows[0]`` is the top row, so rows are reversed.
    """
    if board.width != CC_WIDTH or board.height != CC_HEIGHT:
        raise ColdClear1Error(
            f"Cold Clear requires a {CC_WIDTH}x{CC_HEIGHT} board, got {board.width}x{board.height}"
        )
    field = [False] * (CC_WIDTH * CC_HEIGHT)
    for y_ours in range(CC_HEIGHT):
        row = board.rows[y_ours]
        base = (CC_HEIGHT - 1 - y_ours) * CC_WIDTH
        for x in range(CC_WIDTH):
            if (row >> x) & 1:
                field[base + x] = True
    return field


def move_to_cells(move: CCMove) -> Tuple[Tuple[int, int], ...]:
    """Convert ``CCMove.expected_*`` (bottom-left origin) to top-down cells."""
    cells: List[Tuple[int, int]] = []
    for i in range(4):
        x = int(move.expected_x[i])
        y_bottom_up = int(move.expected_y[i])
        if not (0 <= x < CC_WIDTH and 0 <= y_bottom_up < CC_HEIGHT):
            raise ColdClear1Error(f"engine returned out-of-board cell ({x}, {y_bottom_up})")
        cells.append((x, CC_HEIGHT - 1 - y_bottom_up))
    if len(set(cells)) != 4:
        raise ColdClear1Error(f"engine returned a non-tetromino cell set: {cells!r}")
    return tuple(sorted(cells))


def action_for_move(move: ColdClear1Move, state: GameState) -> Optional[int]:
    """Map an engine suggestion to a legal placement action id, or ``None``.

    Matching is purely geometric (the four absolute cells) plus the hold flag.
    Rotation labels are never trusted, which keeps the mapping robust even
    though Cold Clear's rotation-state naming differs from ours.
    """
    if state.current is None:
        return None
    target = set(move.cells)
    fallback: Optional[int] = None
    for action in state.legal_actions():
        placement = state.resolve(action)
        if placement is None or set(placement.cells) != target:
            continue
        if bool(placement.hold) == bool(move.hold):
            return action
        if fallback is None:
            fallback = action
    return fallback


# ---------------------------------------------------------------------------
# Shared-library session
# ---------------------------------------------------------------------------
class ColdClear1Library:
    """Thin, typed wrapper around the Cold Clear C ABI."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        try:
            self.lib = ctypes.CDLL(str(self.path))
        except OSError as exc:
            raise ColdClear1Unavailable(f"cannot load Cold Clear library {self.path}: {exc}") from exc
        self._configure()

    def _configure(self) -> None:
        lib = self.lib
        lib.cc_default_options.argtypes = [ctypes.POINTER(CCOptions)]
        lib.cc_default_options.restype = None
        lib.cc_default_weights.argtypes = [ctypes.POINTER(CCWeights)]
        lib.cc_default_weights.restype = None
        lib.cc_launch_with_board_async.argtypes = [
            ctypes.POINTER(CCOptions),
            ctypes.POINTER(CCWeights),
            ctypes.c_void_p,  # CCBook * (NULL: no opening book)
            ctypes.POINTER(ctypes.c_bool),  # bool field[400]
            ctypes.c_uint32,  # bag_remain bitmask
            ctypes.POINTER(ctypes.c_int),  # CCPiece *hold (NULL: no hold)
            ctypes.c_bool,  # b2b
            ctypes.c_uint32,  # combo
            ctypes.POINTER(ctypes.c_int),  # CCPiece *queue
            ctypes.c_uint32,  # count
        ]
        lib.cc_launch_with_board_async.restype = ctypes.c_void_p
        lib.cc_request_next_move.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.cc_request_next_move.restype = None
        lib.cc_poll_next_move.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(CCMove),
            ctypes.c_void_p,  # CCPlanPlacement *plan (NULL: unused)
            ctypes.c_void_p,  # uint32_t *plan_length (NULL: unused)
        ]
        lib.cc_poll_next_move.restype = ctypes.c_int
        lib.cc_reset_async.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_bool),
            ctypes.c_bool,
            ctypes.c_uint32,
        ]
        lib.cc_reset_async.restype = None
        lib.cc_destroy_async.argtypes = [ctypes.c_void_p]
        lib.cc_destroy_async.restype = None

    # -- helpers --------------------------------------------------------
    def defaults(self) -> Tuple[CCOptions, CCWeights]:
        options = CCOptions()
        weights = CCWeights()
        self.lib.cc_default_options(ctypes.byref(options))
        self.lib.cc_default_weights(ctypes.byref(weights))
        return options, weights

    def search(
        self,
        state: GameState,
        incoming: int,
        *,
        min_nodes: int = 20_000,
        max_nodes: Optional[int] = None,
        threads: int = 1,
        movement_mode: str = "hard_drop_only",
        spawn_rule: str = "row21_and_fall",
        use_hold: bool = True,
        speculate: bool = False,
        timeout: float = 5.0,
        poll_interval: float = 0.0005,
    ) -> ColdClear1Move:
        """Ask the engine for one placement on ``state`` with ``incoming`` lines.

        The bot is launched from a full board snapshot (including hold, B2B and
        combo), so no state from a previous decision leaks in.  The returned
        move is validated for board bounds and a four-cell tetromino shape; it
        is *not* yet checked against :meth:`GameState.legal_actions` (that is
        :func:`action_for_move`'s job, so the adapter can report an
        inexpressible-but-valid engine move separately from a malformed one).
        """
        if state.current is None:
            raise ColdClear1Error("cannot search without a current piece")
        if movement_mode not in CC_MOVEMENT_MODES:
            raise ColdClear1Error(f"unknown movement mode {movement_mode!r}")
        if spawn_rule not in CC_SPAWN_RULES:
            raise ColdClear1Error(f"unknown spawn rule {spawn_rule!r}")
        if threads < 1:
            raise ColdClear1Error("threads must be >= 1")

        options, weights = self.defaults()
        options.mode = CC_MOVEMENT_MODES[movement_mode]
        options.spawn_rule = CC_SPAWN_RULES[spawn_rule]
        options.min_nodes = max(0, int(min_nodes))
        options.max_nodes = int(max_nodes) if max_nodes is not None else max(1, int(min_nodes) * 4)
        options.threads = int(threads)
        options.use_hold = bool(use_hold)
        # We cannot prove our seven-bag state to the engine, so speculation is
        # off by default: the engine reasons only from the queue we send.
        options.speculate = bool(speculate)

        field_values = board_to_field(state.board)
        field = (ctypes.c_bool * (CC_WIDTH * CC_HEIGHT))(*field_values)

        queue_names = [state.current.name, *state.preview(max(1, state.ruleset.board.preview))]
        queue_values = [CC_PIECE_IDS[name] for name in queue_names]
        queue = (ctypes.c_int * len(queue_values))(*queue_values)

        hold_value = ctypes.c_int(CC_PIECE_IDS[state.hold]) if state.hold else None
        hold = ctypes.pointer(hold_value) if hold_value is not None else None

        # bag_remain = 0 makes libtetris start with a full bag; the six explicit
        # queue entries are authoritative for this decision.
        bot = self.lib.cc_launch_with_board_async(
            ctypes.byref(options),
            ctypes.byref(weights),
            None,
            field,
            0,
            hold,
            bool(state.b2b_active),
            max(0, int(state.clear_state.combo) + 1),
            queue,
            len(queue_values),
        )
        if not bot:
            raise ColdClear1Error("cc_launch_with_board_async returned NULL")

        try:
            self.lib.cc_request_next_move(bot, ctypes.c_uint32(max(0, int(incoming))))
            move = CCMove()
            started = time.monotonic()
            while True:
                status = self.lib.cc_poll_next_move(bot, ctypes.byref(move), None, None)
                if status == CC_MOVE_PROVIDED:
                    break
                if status == CC_BOT_DEAD:
                    raise ColdClear1Dead("engine reported CC_BOT_DEAD (no survivable placement)")
                if status != CC_WAITING:
                    raise ColdClear1Error(f"engine returned unknown poll status {status}")
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise ColdClear1Timeout(f"engine produced no move within {timeout:.3f}s")
                time.sleep(min(max(0.0001, poll_interval), remaining))

            cells = move_to_cells(move)
            return ColdClear1Move(
                hold=bool(move.hold),
                cells=cells,
                nodes=int(move.nodes),
                depth=int(move.depth),
                original_rank=int(move.original_rank),
                movement_count=int(move.movement_count),
                movements=tuple(int(m) for m in move.movements[: int(move.movement_count)]),
            )
        finally:
            # cc_destroy_async consumes the pointer and stops the worker thread.
            self.lib.cc_destroy_async(bot)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
@dataclass
class ColdClear1Stats:
    """Counters exposed for experiments and honest reporting."""

    searches: int = 0
    accepted: int = 0
    invalid_moves: int = 0
    fallbacks: int = 0
    timeouts: int = 0
    errors: int = 0
    engine_dead: int = 0
    nodes_total: int = 0
    answer_latency_ms: float = 0.0
    incoming_searches: int = 0
    garbage_probes: int = 0
    garbage_probe_differences: int = 0
    garbage_probe_errors: int = 0
    probe_searches: int = 0
    last_incoming: int = 0
    last_move: Dict[str, Any] = field(default_factory=dict)
    last_error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        out = dict(self.__dict__)
        if self.searches:
            out["mean_answer_latency_ms"] = round(self.answer_latency_ms / self.searches, 3)
            out["nodes_per_search"] = round(self.nodes_total / self.searches, 1)
        return out


class ColdClear1Agent(BaseAgent):
    """Cold Clear (original, C ABI) as a versus opponent.

    Parameters
    ----------
    library:
        Path to ``libcold_clear.so``.  Defaults to the clone under
        ``third_party/cold-clear`` (or ``$TETRISRL_COLDCLEAR1_LIB``).
    think_nodes:
        Minimum number of search nodes before the engine may answer
        (``CCOptions.min_nodes``).  Roughly 20k nodes ≈ 20–35 ms on the
        reference machine; this is the only think-time control the C ABI has.
    max_nodes:
        ``CCOptions.max_nodes``; defaults to ``4 * think_nodes``.  The bot is
        destroyed as soon as a move is returned, so this is only a safety cap.
    movement_mode:
        ``"hard_drop_only"`` (default) restricts move generation to hard drops,
        matching our placement action space and avoiding tucks the action space
        cannot encode.  ``"zero_g"`` / ``"twenty_g"`` are available for probing.
    spawn_rule:
        ``"row21_and_fall"`` (default, closest to our spawn geometry) or
        ``"row19_or_20"``.
    timeout:
        Deadline for one engine decision, in seconds.
    fallback:
        Agent used whenever the engine is unavailable, times out, reports a dead
        search, or suggests a placement our action space cannot express.
    allow_in_tests:
        Required for loading the library under pytest.  Without it, non-skipped
        tests can never touch the engine.
    garbage_probe:
        When true, every decision made with pending garbage triggers a second
        search with ``incoming=0`` and records whether the suggestion changed.
        This doubles engine work for those decisions and exists to *measure*
        garbage-awareness, not to influence play.
    """

    name = "coldclear1"

    def __init__(
        self,
        library: Optional[str | os.PathLike[str]] = None,
        *,
        think_nodes: int = 20_000,
        max_nodes: Optional[int] = None,
        threads: int = 1,
        movement_mode: str = "hard_drop_only",
        spawn_rule: str = "row21_and_fall",
        use_hold: bool = True,
        speculate: bool = False,
        timeout: float = 5.0,
        fallback: Optional[BaseAgent] = None,
        allow_in_tests: bool = False,
        garbage_probe: bool = False,
        name: Optional[str] = None,
    ) -> None:
        self.library_path = coldclear1_binary_path(library)
        self.think_nodes = max(0, int(think_nodes))
        self.max_nodes = None if max_nodes is None else max(1, int(max_nodes))
        self.threads = max(1, int(threads))
        self.movement_mode = str(movement_mode)
        self.spawn_rule = str(spawn_rule)
        self.use_hold = bool(use_hold)
        self.speculate = bool(speculate)
        self.timeout = max(0.001, float(timeout))
        self.allow_in_tests = bool(allow_in_tests)
        self.garbage_probe = bool(garbage_probe)
        if name:
            self.name = name
        self.stats = ColdClear1Stats()
        self.seed = 0
        self._fallback: BaseAgent = fallback if fallback is not None else HeuristicAgent(seed=0)
        self._library: Optional[ColdClear1Library] = None
        self._closed = False

    # -- convenience ----------------------------------------------------
    @property
    def fallback_count(self) -> int:
        return self.stats.fallbacks

    @property
    def invalid_count(self) -> int:
        return self.stats.invalid_moves

    @property
    def library_loaded(self) -> bool:
        return self._library is not None

    # -- BaseAgent API --------------------------------------------------
    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        self._fallback.reset(self.seed)
        self.stats = ColdClear1Stats()
        self._closed = False

    def observe(self, state: GameState, opponent_state: Optional[GameState] = None) -> Dict[str, Any]:
        return {}

    def receive_result(self, result: Any) -> None:
        return None

    def terminate(self) -> None:
        # The library is loaded in-process and stateless from our side: every
        # decision destroys its bot before returning, so there is no worker
        # thread to stop here.  Dropping the handle releases our reference.
        self._closed = True
        self._library = None

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        if state.current is None or state.finished or not state.legal_actions():
            return -1
        incoming = max(0, int(state.pending_garbage))
        self.stats.last_incoming = incoming
        if incoming > 0:
            self.stats.incoming_searches += 1
        try:
            if self._closed:
                raise ColdClear1Unavailable("agent was terminated; call reset() first")
            move = self._search(state, incoming)
        except ColdClear1Timeout as exc:
            self.stats.timeouts += 1
            self.stats.last_error = str(exc)
            return self._fallback_action(state, opponent_state)
        except ColdClear1Dead as exc:
            self.stats.engine_dead += 1
            self.stats.last_error = str(exc)
            return self._fallback_action(state, opponent_state)
        except Exception as exc:  # never let a broken engine crash a match
            self.stats.errors += 1
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
            return self._fallback_action(state, opponent_state)

        action = action_for_move(move, state)
        if action is None:
            self.stats.invalid_moves += 1
            self.stats.last_error = (
                "engine placement is not expressible in our hard-drop action space: "
                f"{move.to_dict()!r}"
            )
            return self._fallback_action(state, opponent_state)

        self.stats.accepted += 1
        if self.garbage_probe and incoming > 0:
            self._probe_garbage_effect(state, move, incoming)
        return action

    # -- internals ------------------------------------------------------
    def _fallback_action(self, state: GameState, opponent_state: Optional[GameState]) -> int:
        self.stats.fallbacks += 1
        action = self._fallback.choose_action(state, opponent_state)
        if not isinstance(action, int) or action < 0:
            legal = state.legal_actions()
            return legal[0] if legal else -1
        return action

    def _ensure_library(self) -> ColdClear1Library:
        if self._library is not None:
            return self._library
        if os.environ.get("TETRISRL_COLDCLEAR1_DISABLE") == "1":
            raise ColdClear1Unavailable("library loading disabled by TETRISRL_COLDCLEAR1_DISABLE=1")
        if _pytest_active() and not self.allow_in_tests:
            raise ColdClear1Unavailable(
                "ColdClear1Agent refuses to load the engine under pytest "
                "(test-collection guard); pass allow_in_tests=True explicitly"
            )
        if not self.library_path.is_file():
            raise ColdClear1Unavailable(
                f"Cold Clear library not found at {self.library_path}; build it with "
                "`cargo build --release -p c-api` in third_party/cold-clear"
            )
        self._library = ColdClear1Library(self.library_path)
        return self._library

    def _search(self, state: GameState, incoming: int) -> ColdClear1Move:
        library = self._ensure_library()
        started = time.monotonic()
        move = library.search(
            state,
            incoming,
            min_nodes=self.think_nodes,
            max_nodes=self.max_nodes,
            threads=self.threads,
            movement_mode=self.movement_mode,
            spawn_rule=self.spawn_rule,
            use_hold=self.use_hold,
            speculate=self.speculate,
            timeout=self.timeout,
        )
        self.stats.searches += 1
        self.stats.nodes_total += move.nodes
        self.stats.answer_latency_ms += (time.monotonic() - started) * 1000.0
        self.stats.last_move = move.to_dict()
        return move

    def _probe_garbage_effect(self, state: GameState, move: ColdClear1Move, incoming: int) -> None:
        """Measure whether the pending-garbage count changes the suggestion."""
        self.stats.garbage_probes += 1
        self.stats.probe_searches += 1
        try:
            baseline = self._search(state, 0)
        except Exception as exc:
            self.stats.garbage_probe_errors += 1
            self.stats.last_error = f"garbage probe failed: {type(exc).__name__}: {exc}"
            return
        if set(baseline.cells) != set(move.cells) or bool(baseline.hold) != bool(move.hold):
            self.stats.garbage_probe_differences += 1
        # The probe is a measurement; ``last_move`` must describe the move we
        # actually returned, not the counterfactual search.
        self.stats.last_move = move.to_dict()


__all__ = [
    "CC_HEIGHT",
    "CC_MOVE_PROVIDED",
    "CC_MOVEMENT_MODES",
    "CC_PIECE_IDS",
    "CC_SPAWN_RULES",
    "CC_WIDTH",
    "CCMove",
    "CCOptions",
    "CCWeights",
    "ColdClear1Agent",
    "ColdClear1Dead",
    "ColdClear1Error",
    "ColdClear1Library",
    "ColdClear1Move",
    "ColdClear1Stats",
    "ColdClear1Timeout",
    "ColdClear1Unavailable",
    "action_for_move",
    "board_to_field",
    "coldclear1_available",
    "coldclear1_binary_path",
    "DEFAULT_LIBRARY",
    "move_to_cells",
]
