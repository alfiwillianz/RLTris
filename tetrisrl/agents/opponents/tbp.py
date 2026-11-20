"""Cold Clear 2 opponent adapter over the Tetris Bot Protocol (TBP).

This module implements a *real* external-engine adapter: it launches the
compiled Cold Clear 2 binary as a subprocess, speaks the Tetris Bot Protocol
(JSON, one message per line) over stdin/stdout, and converts the engine's
suggested placement into this project's placement action id.

Scope and honesty notes
-----------------------
* Cold Clear 2 is only used as a **placement suggester**.  The engine receives
  the board, hold, queue, combo and back-to-back flag, and answers "where should
  this piece go?".  It never sees or generates attack, garbage, surge, or
  TETR.IO Season 2 charging state; :mod:`tetrisrl.environment.versus` remains
  the single authority for all competitive rules.
* TBP has no message for pending/incoming garbage, so the engine cannot plan
  around garbage that has not landed yet.  Garbage that *has* landed is in the
  board we send.
* Cold Clear 2 has no 180-degree rotation, so placements requiring a 180 spin
  are unreachable for it (a documented handicap, not a correctness bug).
* The engine's suggested placement may use tucks/spins that our hard-drop
  action space cannot express.  In that case the adapter falls back to the
  in-repo heuristic and increments a counter; this is measured and reported.
* Cold Clear 2's TBP `start` handling treats the first queue entry as the
  "reserve" (hold slot) when `hold` is null.  We therefore send a queue whose
  second entry is the current piece in that case (verified empirically against
  the built binary; see docs/BENCHMARKS_INTEGRATION.md).

The adapter never launches a process at import time or during pytest
collection: the subprocess is created lazily on the first ``reset``/``choose``
call, and refuses to launch under pytest unless ``allow_in_tests=True`` (the
test-suite analogue of a ``--`` separator guard).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..base import BaseAgent
from ..heuristic_agent import HeuristicAgent
from ...environment.board import Board
from ...environment.engine import GameState

#: Cold Clear 2 works on a fixed 10x40 board with y=0 at the *bottom*.
TBP_WIDTH = 10
TBP_HEIGHT = 40

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BINARY = _REPO_ROOT / "third_party" / "cold-clear-2" / "target" / "release" / "cold-clear-2"

#: Cold Clear 2's own piece geometry, north orientation, relative to the SRS
#: rotation centre (``src/data.rs`` in the engine).
CC_NORTH_CELLS: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "I": ((-1, 0), (0, 0), (1, 0), (2, 0)),
    "O": ((0, 0), (1, 0), (0, 1), (1, 1)),
    "T": ((-1, 0), (0, 0), (1, 0), (0, 1)),
    "L": ((-1, 0), (0, 0), (1, 0), (1, 1)),
    "J": ((-1, 0), (0, 0), (1, 0), (-1, 1)),
    "S": ((-1, 0), (0, 0), (0, 1), (1, 1)),
    "Z": ((-1, 1), (0, 1), (0, 0), (1, 0)),
}

CC_ORIENTATIONS = {"north": 0, "east": 1, "south": 2, "west": 3}


class TBPError(RuntimeError):
    """Base class for protocol/process failures."""


class TBPTimeout(TBPError):
    """The engine did not answer within the configured timeout."""


class TBPProcessError(TBPError):
    """The engine process exited or a pipe broke."""


def _pytest_active() -> bool:
    return "pytest" in sys.modules or "_pytest" in sys.modules


def coldclear_binary_path(binary: Optional[str | os.PathLike[str]] = None) -> Path:
    """Resolve the Cold Clear 2 binary path (env override, argument, default)."""
    if binary is not None:
        return Path(binary).expanduser()
    env = os.environ.get("TETRISRL_COLDCLEAR_BIN")
    if env:
        return Path(env).expanduser()
    return DEFAULT_BINARY


def coldclear_available(binary: Optional[str | os.PathLike[str]] = None) -> bool:
    path = coldclear_binary_path(binary)
    return path.is_file() and os.access(path, os.X_OK)


# ---------------------------------------------------------------------------
# Wire encoding / decoding
# ---------------------------------------------------------------------------
def board_to_tbp_rows(
    board: Board,
    garbage_rows: Iterable[int] = (),
) -> List[List[Optional[str]]]:
    """Encode a board as TBP rows (bottom row first).

    TBP board cells are ``null`` for empty or a string for occupied.  Cold
    Clear 2 treats *any* non-null value as occupied, so ``"#"`` is used for
    normal blocks and ``"G"`` can be used for garbage rows when the caller
    knows their provenance.  Our :class:`Board` only stores occupancy, so the
    adapter itself passes ``garbage_rows=()`` and therefore sends ``"#"``.

    ``garbage_rows`` are indices into *our* top-down board (row 0 = top).
    """
    if board.height != TBP_HEIGHT:
        raise TBPError(
            f"Cold Clear 2 requires a {TBP_HEIGHT}-row board, got {board.height}; "
            "the adapter refuses to silently pad/truncate"
        )
    garbage = set(int(y) for y in garbage_rows)
    rows: List[List[Optional[str]]] = []
    for y in range(board.height - 1, -1, -1):  # bottom-up on the wire
        row = board.rows[y]
        cell = "G" if y in garbage else "#"
        rows.append([cell if (row >> x) & 1 else None for x in range(board.width)])
    return rows


def tbp_rows_to_board_rows(rows: Sequence[Sequence[Any]]) -> List[int]:
    """Decode TBP rows (bottom-up) back to our top-down row bitmasks."""
    if len(rows) != TBP_HEIGHT:
        raise TBPError(f"expected {TBP_HEIGHT} TBP rows, got {len(rows)}")
    out: List[int] = []
    for wire_row in reversed(rows):  # wire is bottom-up -> top-down
        if len(wire_row) != TBP_WIDTH:
            raise TBPError(f"expected {TBP_WIDTH} columns, got {len(wire_row)}")
        mask = 0
        for x, value in enumerate(wire_row):
            if value not in (None, 0, False, ".", ""):
                mask |= 1 << x
        out.append(mask)
    return out


def board_to_text_rows(board: Board) -> List[str]:
    """Top-down ``'.'``/``'#'`` rows (debug/repr helper, not wire format)."""
    return ["".join("#" if (row >> x) & 1 else "." for x in range(board.width)) for row in board.rows]


def _cc_rotate_cell(orientation: int, cell: Tuple[int, int]) -> Tuple[int, int]:
    """Cold Clear 2's rotation maths (``src/data.rs``, y grows upward)."""
    x, y = cell
    if orientation == 0:  # north
        return x, y
    if orientation == 1:  # east
        return y, -x
    if orientation == 2:  # south
        return -x, -y
    if orientation == 3:  # west
        return -y, x
    raise TBPError(f"invalid orientation {orientation}")


def tbp_move_cells(move: Dict[str, Any], board_height: int = TBP_HEIGHT) -> Tuple[str, Set[Tuple[int, int]]]:
    """Convert a TBP move into ``(piece, cells)`` in *our* top-down coordinates.

    The TBP move format is::

        {"location": {"type": "T", "orientation": "north", "x": 4, "y": 19},
         "spin": "none"}

    ``x``/``y`` are the SRS rotation centre in a bottom-up coordinate system.
    """
    location = move.get("location", move)
    piece = str(location["type"])
    if piece not in CC_NORTH_CELLS:
        raise TBPError(f"unknown piece type {piece!r}")
    try:
        orientation = CC_ORIENTATIONS[str(location.get("orientation", "north"))]
    except KeyError as exc:
        raise TBPError(f"unknown orientation {location.get('orientation')!r}") from exc
    x = int(location["x"])
    y = int(location["y"])
    cells: Set[Tuple[int, int]] = set()
    for cell in CC_NORTH_CELLS[piece]:
        dx, dy = _cc_rotate_cell(orientation, cell)
        cc_x, cc_y = x + dx, y + dy
        if not (0 <= cc_x < TBP_WIDTH and 0 <= cc_y < board_height):
            raise TBPError(f"move cell ({cc_x}, {cc_y}) is outside the board")
        cells.add((cc_x, board_height - 1 - cc_y))  # bottom-up -> top-down
    if len(cells) != 4:
        raise TBPError(f"move does not contain 4 distinct cells: {move!r}")
    return piece, cells


def action_for_tbp_move(move: Dict[str, Any], state: GameState) -> Optional[int]:
    """Map a TBP placement to a legal placement action id, or ``None``.

    The mapping is geometry based: the move is converted to its four absolute
    board cells (top-down) and matched against the cells of every legal
    hard-drop placement.  This is robust against the engines' different
    rotation-state naming.  Hold is preferred/required according to which piece
    the engine placed.
    """
    if state.current is None:
        return None
    try:
        piece, target = tbp_move_cells(move, state.board.height)
    except (TBPError, KeyError, TypeError, ValueError):
        return None
    expects_hold = piece != state.current.name
    fallback_match: Optional[int] = None
    for action in state.legal_actions():
        placement = state.resolve(action)
        if placement is None or placement.piece != piece:
            continue
        if set(placement.cells) != target:
            continue
        if bool(placement.hold) == expects_hold:
            return action
        if fallback_match is None:
            fallback_match = action
    return fallback_match


def build_start_message(
    state: GameState,
    *,
    preview_count: Optional[int] = None,
    garbage_rows: Iterable[int] = (),
) -> Dict[str, Any]:
    """Build the TBP ``start`` message for the current state.

    Queue convention (verified against the built binary): Cold Clear 2 treats
    ``queue[0]`` as the reserve/hold slot when ``hold`` is null, and as the
    current piece when ``hold`` is not null.  We therefore send
    ``[first_preview, current, *previews]`` when hold is empty so that the
    engine's root piece is the current piece, and ``[current, *previews]`` when
    a hold piece exists.
    """
    if state.current is None:
        raise TBPError("cannot build a start message without a current piece")
    current = state.current.name
    n = state.ruleset.board.preview if preview_count is None else int(preview_count)
    previews = state.preview(max(0, n))
    if state.hold is not None:
        queue = [current, *previews]
    elif previews:
        queue = [previews[0], current, *previews]
    else:  # no previews configured: duplicate the current piece to stay valid
        queue = [current, current]
    return {
        "type": "start",
        "hold": state.hold,
        "queue": queue,
        # Our engine follows TETR.IO's ``-1 = no combo`` convention; TBP asks
        # for the *count* of consecutive clears (a u32), so shift to 0-based.
        "combo": max(0, int(state.combo) + 1),
        "back_to_back": bool(state.b2b_active),
        "board": board_to_tbp_rows(state.board, garbage_rows),
    }


def parse_suggestion(message: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate and return ``(moves, move_info)`` from a ``suggestion`` message."""
    if message.get("type") != "suggestion":
        raise TBPError(f"expected a suggestion message, got {message.get('type')!r}")
    moves = message.get("moves")
    if not isinstance(moves, list):
        raise TBPError("suggestion message has no 'moves' list")
    info = message.get("move_info") or {}
    return moves, dict(info) if isinstance(info, dict) else {}


# ---------------------------------------------------------------------------
# Subprocess session
# ---------------------------------------------------------------------------
_EOF = object()


class TBPSession:
    """A live Cold Clear 2 / TBP subprocess with non-blocking message reads."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        handshake_timeout: float = 10.0,
    ) -> None:
        self.command = list(command)
        self.handshake_timeout = float(handshake_timeout)
        self.engine_info: Dict[str, Any] = {}
        self._messages: "queue.Queue[Any]" = queue.Queue()
        self._stderr_lines: List[str] = []
        self._closed = False
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._stdout_thread = threading.Thread(target=self._read_stdout, name="tbp-stdout", daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, name="tbp-stderr", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    # -- threads --------------------------------------------------------
    def _read_stdout(self) -> None:
        try:
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._messages.put(json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._messages.put({"type": "__invalid_json__", "line": line[:500]})
        finally:
            self._messages.put(_EOF)

    def _read_stderr(self) -> None:
        try:
            assert self.proc.stderr is not None
            for line in self.proc.stderr:
                text = line.rstrip()
                if not text:
                    continue
                if len(self._stderr_lines) >= 200:
                    self._stderr_lines.pop(0)
                self._stderr_lines.append(text)
        except (ValueError, OSError):
            pass

    # -- state ----------------------------------------------------------
    def alive(self) -> bool:
        return self.proc.poll() is None

    def stderr_tail(self, n: int = 20) -> str:
        return "\n".join(self._stderr_lines[-n:])

    def _process_error(self, what: str) -> TBPProcessError:
        code = self.proc.poll()
        tail = self.stderr_tail()
        return TBPProcessError(f"{what}: engine exited (code {code})" + (f"; stderr: {tail}" if tail else ""))

    # -- io -------------------------------------------------------------
    def send(self, message: Dict[str, Any]) -> None:
        if self._closed or not self.alive() or self.proc.stdin is None:
            raise self._process_error("cannot send")
        line = json.dumps(message, separators=(",", ":"))
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise self._process_error(f"broken stdin ({exc})") from exc

    def read_message(self, timeout: float) -> Dict[str, Any]:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TBPTimeout(f"timed out waiting for engine message after {timeout:.3f}s")
            try:
                item = self._messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TBPTimeout(f"timed out waiting for engine message after {timeout:.3f}s") from exc
            if item is _EOF:
                raise self._process_error("engine closed stdout")
            return item

    def wait_for(self, types: Iterable[str], timeout: float) -> Dict[str, Any]:
        wanted = set(types)
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TBPTimeout(f"timed out waiting for {sorted(wanted)}")
            message = self.read_message(remaining)
            if message.get("type") in wanted:
                return message
            # Unknown / stale messages are ignored per the TBP spec.

    def drain(self) -> None:
        while True:
            try:
                self._messages.get_nowait()
            except queue.Empty:
                return

    # -- lifecycle ------------------------------------------------------
    def handshake(self) -> Dict[str, Any]:
        info = self.wait_for(("info",), self.handshake_timeout)
        self.engine_info = dict(info)
        self.send({"type": "rules"})
        reply = self.wait_for(("ready", "error"), self.handshake_timeout)
        if reply.get("type") == "error":
            raise TBPError(f"engine rejected rules: {reply.get('reason')}")
        return self.engine_info

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.alive() and self.proc.stdin is not None:
                self.proc.stdin.write(json.dumps({"type": "quit"}) + "\n")
                self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                self.proc.kill()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread.is_alive():
                thread.join(timeout=0.5)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
@dataclass
class TBPStats:
    """Counters exposed for experiments and honest reporting."""

    engine_starts: int = 0
    suggestions: int = 0
    accepted: int = 0
    invalid_suggestions: int = 0
    fallbacks: int = 0
    timeouts: int = 0
    protocol_errors: int = 0
    engine_restarts: int = 0
    answer_latency_ms: float = 0.0
    nodes_total: int = 0
    last_move_info: Dict[str, Any] = field(default_factory=dict)
    last_error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        out = dict(self.__dict__)
        if self.suggestions:
            out["mean_answer_latency_ms"] = round(self.answer_latency_ms / self.suggestions, 3)
        return out


class TBPAgent(BaseAgent):
    """Cold Clear 2 (TBP) as a versus opponent.

    Parameters
    ----------
    binary:
        Path to the Cold Clear 2 release binary.  Defaults to the clone under
        ``third_party/cold-clear-2`` (or ``$TETRISRL_COLDCLEAR_BIN``).
    command:
        Full command override (used by tests to launch :mod:`mock_bot`).
    think_time:
        Seconds to let the engine search after each ``start`` before asking for
        a suggestion.  Cold Clear 2 restarts its tree for each ``start``; the
        adapter sends one ``start`` per piece (TBP has no per-tick board update
        message, and reusing ``play`` would desynchronise on our fallback).
    timeout:
        Deadline for a suggestion (including ``think_time``).
    fallback:
        Agent used whenever the engine is unavailable, times out, or suggests a
        placement our action space cannot express.
    allow_in_tests:
        Required for launching under pytest; without it the adapter refuses to
        spawn a process so test collection can never start an engine.
    """

    name = "coldclear"

    def __init__(
        self,
        binary: Optional[str | os.PathLike[str]] = None,
        *,
        config_path: Optional[str | os.PathLike[str]] = None,
        think_time: float = 0.06,
        timeout: float = 5.0,
        handshake_timeout: float = 10.0,
        fallback: Optional[BaseAgent] = None,
        command: Optional[Sequence[str]] = None,
        allow_in_tests: bool = False,
        name: Optional[str] = None,
    ) -> None:
        self.binary = coldclear_binary_path(binary)
        self.config_path = Path(config_path).expanduser() if config_path else None
        self.think_time = max(0.0, float(think_time))
        self.timeout = max(0.001, float(timeout))
        self.handshake_timeout = max(0.001, float(handshake_timeout))
        self.command = list(command) if command is not None else None
        self.allow_in_tests = bool(allow_in_tests)
        if name:
            self.name = name
        self.stats = TBPStats()
        self.seed = 0
        self._fallback: BaseAgent = fallback if fallback is not None else HeuristicAgent(seed=0)
        self._session: Optional[TBPSession] = None
        self.last_suggestion: Optional[Dict[str, Any]] = None
        self.engine_info: Dict[str, Any] = {}

    # -- counters -------------------------------------------------------
    @property
    def fallback_count(self) -> int:
        return self.stats.fallbacks

    @property
    def invalid_count(self) -> int:
        return self.stats.invalid_suggestions

    # -- BaseAgent API --------------------------------------------------
    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        self._close_session()
        self._fallback.reset(self.seed)
        self.stats = TBPStats()
        self.last_suggestion = None

    def observe(self, state: GameState, opponent_state: Optional[GameState] = None) -> Dict[str, Any]:
        return {}

    def receive_result(self, result: Any) -> None:
        return None

    def terminate(self) -> None:
        self._close_session()

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        if state.current is None or state.finished or not state.legal_actions():
            return -1
        try:
            moves = self._request_suggestion(state)
        except TBPTimeout as exc:
            self.stats.timeouts += 1
            self.stats.last_error = str(exc)
            self._close_session()
            return self._fallback_action(state, opponent_state)
        except Exception as exc:  # never let a broken engine crash a match
            self.stats.protocol_errors += 1
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
            self._close_session()
            return self._fallback_action(state, opponent_state)

        if not moves:
            self.stats.invalid_suggestions += 1
            self.stats.last_error = "engine returned no moves"
            return self._fallback_action(state, opponent_state)

        move = moves[0]
        self.last_suggestion = move
        action = action_for_tbp_move(move, state)
        if action is None:
            self.stats.invalid_suggestions += 1
            self.stats.last_error = f"suggested placement not expressible in our action space: {move!r}"
            return self._fallback_action(state, opponent_state)
        self.stats.accepted += 1
        return action

    # -- internals ------------------------------------------------------
    def _fallback_action(self, state: GameState, opponent_state: Optional[GameState]) -> int:
        self.stats.fallbacks += 1
        action = self._fallback.choose_action(state, opponent_state)
        if not isinstance(action, int) or action < 0:
            legal = state.legal_actions()
            return legal[0] if legal else -1
        return action

    def _launch_command(self) -> List[str]:
        if self.command is not None:
            return list(self.command)
        command = [str(self.binary)]
        if self.config_path is not None:
            command += ["--config", str(self.config_path)]
        return command

    def _ensure_session(self) -> TBPSession:
        if self._session is not None and self._session.alive():
            return self._session
        if self._session is not None:
            self._session.close()
            self._session = None
            self.stats.engine_restarts += 1
        if os.environ.get("TETRISRL_TBP_DISABLE") == "1":
            raise TBPError("engine launch disabled by TETRISRL_TBP_DISABLE=1")
        if _pytest_active() and not self.allow_in_tests:
            raise TBPError(
                "TBPAgent refuses to launch an engine under pytest (test-collection "
                "guard); pass allow_in_tests=True explicitly"
            )
        command = self._launch_command()
        if not self.command and not coldclear_available(self.binary):
            raise TBPProcessError(
                f"Cold Clear 2 binary not found/executable at {self.binary}; "
                "build it with `cargo build --release` in third_party/cold-clear-2"
            )
        session = TBPSession(command, handshake_timeout=self.handshake_timeout)
        try:
            self.engine_info = session.handshake()
        except Exception:
            session.close()
            raise
        self.stats.engine_starts += 1
        self._session = session
        return session

    def _request_suggestion(self, state: GameState) -> List[Dict[str, Any]]:
        session = self._ensure_session()
        session.drain()  # drop any late reply from a previous timeout
        session.send(build_start_message(state))
        started = time.monotonic()
        budget = self.timeout
        sleep_for = min(self.think_time, budget * 0.5)
        if sleep_for > 0:
            time.sleep(sleep_for)
        deadline = started + budget
        while time.monotonic() < deadline:
            session.send({"type": "suggest"})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            reply = session.wait_for(("suggestion", "error"), remaining)
            if reply.get("type") == "error":
                raise TBPError(f"engine error: {reply.get('reason')}")
            moves, info = parse_suggestion(reply)
            if moves:
                self.stats.suggestions += 1
                self.stats.answer_latency_ms += (time.monotonic() - started) * 1000.0
                self.stats.last_move_info = info
                try:
                    self.stats.nodes_total += int(info.get("nodes", 0) or 0)
                except (TypeError, ValueError):
                    pass
                return moves
            # The engine had not expanded the root node yet; ask again shortly.
            time.sleep(min(0.003, self.think_time) if self.think_time else 0.001)
        raise TBPTimeout(f"engine produced no suggestion within {self.timeout:.3f}s")

    def _close_session(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def __del__(self) -> None:  # best effort; explicit terminate() is preferred
        try:
            self._close_session()
        except Exception:
            pass


__all__ = [
    "CC_NORTH_CELLS",
    "DEFAULT_BINARY",
    "TBPAgent",
    "TBPError",
    "TBPProcessError",
    "TBPSession",
    "TBPStats",
    "TBPTimeout",
    "TBP_HEIGHT",
    "TBP_WIDTH",
    "action_for_tbp_move",
    "board_to_tbp_rows",
    "board_to_text_rows",
    "build_start_message",
    "coldclear_available",
    "coldclear_binary_path",
    "parse_suggestion",
    "tbp_move_cells",
    "tbp_rows_to_board_rows",
]
