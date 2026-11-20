"""Frostetra as a versus opponent over the Stacker Bot Protocol (SBP/1).

This is a **real** external-engine adapter.  It launches the compiled
``frostetra`` binary as a subprocess and speaks SBP/1 (newline-delimited JSON)
over stdin/stdout: ``register`` → ``rules`` → ``ready`` → (``start`` →
``suggest`` → ``suggestion`` → ``advance``) per piece → ``quit``.

Scope and honesty notes
-----------------------
* Frostetra is a **placement suggester**.  It never receives attack, Surge,
  garbage insertion or Season 2 charging state, and it does not own the game
  loop.  :mod:`tetrisrl.environment.versus` remains the single authority for
  every competitive rule.
* Frostetra advertises ``srs_plus``, ``rot180`` and several spin-detection
  modes.  We request ``srs_plus``/``rot180`` because those are our ruleset's
  rotation model.  This is source-level capability evidence, not proof that a
  concrete suggested placement *required* an SRS+-only kick or a 180; see
  ``docs/integration_frostetra.md``.
* SBP ``incoming_garbage`` is sent on ``start`` and ``suggest`` for forward
  compatibility.  In the pinned commit the field is deserialised and then
  discarded (``src/runtime/bot_factory.rs`` destructures it as ``_`` and the
  dispatcher handles ``Suggest { .. }``), so it cannot influence the search.
* The engine's ``start`` handling differs from the SBP/1 text: it builds its
  internal queue as ``[active] + queue`` when ``hold`` is set and as ``queue``
  otherwise, then places that queue's head.  Verified empirically against the
  built binary.  We therefore send ``active = current`` and a hold-dependent
  queue: ``[current, *previews]`` with an empty hold, ``[*previews]`` with a
  hold.  Consequence: when our hold slot is empty the engine models it as
  containing the current piece, so frostetra cannot initiate a hold from an
  empty slot (a documented handicap).
* The engine's seven-bag tracker would observe the duplicated current piece
  from the empty-hold queue and infer an impossible bag.  To keep the bag
  information truthful we also send ``piece_stream`` with the observed
  generated-piece order (an advertised capability).  The engine's
  ``visible_queue_len = queue.len() + 1`` still assumes an SBP-standard queue:
  it is exact when a hold is set and the current piece is the newest generated
  one, one piece behind with an empty hold, and stale after a held-piece move.
  Speculation may therefore treat the current piece as still upcoming.  This
  affects only the engine's hypothetical search, never the legality of its root
  suggestion.
* Suggested placements are matched geometrically against
  :meth:`GameState.legal_actions`: our action space is a hard-drop placement
  (rotation + left-most column + hold), while frostetra enumerates every
  reachable lock including tucks.  Suggestions our action space cannot express
  fall back to the in-repo heuristic and are counted.
* Importing this module, constructing an agent, or collecting pytest tests never
  launches a process.  Launching is lazy and refused under pytest unless
  ``allow_in_tests=True`` is passed explicitly.

Frostetra is MIT-licensed (a Cold Clear 2 derivative).  See
``third_party/FROSTETRA_NOTICE.md``; no upstream source is copied into this
file.  The SBP field semantics implemented below come from the protocol's field
documentation and the engine's own ``src/protocol/sbp.rs`` dialect.
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

#: SBP default board geometry: 10 columns x 40 rows, y = 0 at the bottom.
SBP_WIDTH = 10
SBP_HEIGHT = 40

#: Piece geometry from the SBP/1 anchor convention (``north`` orientation,
#: relative to the placement anchor; ``y`` grows upward).  This is protocol
#: field data, not upstream engine code.
SBP_NORTH_CELLS: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "I": ((-1, 0), (0, 0), (1, 0), (2, 0)),
    "J": ((-1, 0), (0, 0), (1, 0), (-1, 1)),
    "L": ((-1, 0), (0, 0), (1, 0), (1, 1)),
    "O": ((0, 0), (1, 0), (0, 1), (1, 1)),
    "S": ((-1, 0), (0, 0), (0, 1), (1, 1)),
    "T": ((-1, 0), (0, 0), (1, 0), (0, 1)),
    "Z": ((-1, 1), (0, 1), (0, 0), (1, 0)),
}

SBP_ORIENTATIONS: Dict[str, int] = {"north": 0, "east": 1, "south": 2, "west": 3}

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BINARY = _REPO_ROOT / "third_party" / "frostetra" / "target" / "release" / "frostetra"

#: How many generated pieces to include in ``start.piece_stream`` (the engine
#: only needs enough to reason about bag boundaries; 4 bags is generous).
PIECE_STREAM_WINDOW = 28


class SBPError(RuntimeError):
    """Base class for protocol/process failures."""


class SBPTimeout(SBPError):
    """The engine did not answer within the configured timeout."""


class SBPProcessError(SBPError):
    """The engine process exited or a pipe broke."""


def _pytest_active() -> bool:
    return "pytest" in sys.modules or "_pytest" in sys.modules


def frostetra_binary_path(binary: Optional[str | os.PathLike[str]] = None) -> Path:
    """Resolve the frostetra binary (argument > ``TETRISRL_FROSTETRA_BIN`` > default)."""
    if binary is not None:
        return Path(binary).expanduser()
    env = os.environ.get("TETRISRL_FROSTETRA_BIN")
    if env:
        return Path(env).expanduser()
    return DEFAULT_BINARY


def frostetra_available(binary: Optional[str | os.PathLike[str]] = None) -> bool:
    path = frostetra_binary_path(binary)
    return path.is_file() and os.access(path, os.X_OK)


# ---------------------------------------------------------------------------
# Wire encoding
# ---------------------------------------------------------------------------
def board_to_sbp_rows(board: Board) -> List[List[Optional[str]]]:
    """Encode a board as SBP rows, **bottom row first**.

    SBP cells are ``null`` (empty) or a string (occupied); all non-null cells
    are treated as occupied.  ``None`` is used for empty cells and ``"X"`` for
    blocks.  Our :class:`Board` stores occupancy only, so garbage provenance is
    not available and is not fabricated.
    """
    rows: List[List[Optional[str]]] = []
    for y in range(board.height - 1, -1, -1):  # bottom-up on the wire
        row = board.rows[y]
        rows.append(["X" if (row >> x) & 1 else None for x in range(board.width)])
    return rows


def build_rules_message(
    state: Optional[GameState] = None, *, randomizer: Optional[str] = "seven_bag"
) -> Dict[str, Any]:
    """Build the ``rules`` message from our ruleset.

    Only fields the engine advertises are negotiated.  ``sonic_drop="only"``
    selects frostetra's hard-drop move enumeration; ``spin_detection="t-spins"``
    is the closest advertised mode to our engine's T-spin-first model (our
    non-T spin credit is disabled by default, so an all-spin mode would credit
    more than our arena does).  ``back_to_back_sources`` mirrors our B2B
    definition; our arena still recomputes B2B and Surge itself.
    """
    if state is not None:
        ruleset = state.ruleset
        board = ruleset.board
        preset = ruleset.rotation.preset
        rot180 = bool(ruleset.rotation.allow_180)
        # Our spawn box bottom row is ``spawn_y + 1`` (top-down); SBP anchors
        # use a bottom-up y.  The SRS anchor column is 4 for a 10-wide board.
        spawn_y = board.height - 1 - (board.spawn_y + 1)
        sources = ["quad", "t-spin", "t-spin-mini"]
        if ruleset.attack.all_clear_counts_as_b2b:
            sources.append("perfect-clear")
    else:
        board = Board()
        preset = "srs_plus"
        rot180 = True
        spawn_y = 20
        sources = ["quad", "t-spin", "t-spin-mini", "perfect-clear"]
    message: Dict[str, Any] = {
        "type": "rules",
        "kickset": "srs_plus" if preset in ("srs_plus", "srs_plus_plain180") else "srs",
        "rot180": rot180,
        "sonic_drop": "only",
        "spin_detection": "t-spins",
        "back_to_back_sources": sources,
        "spawn_position": {"x": 4, "y": spawn_y},
        "board_size": {"width": board.width, "height": board.height},
    }
    if randomizer is not None:
        message["randomizer"] = randomizer
    return message


def build_start_message(
    state: GameState,
    *,
    preview_count: Optional[int] = None,
    incoming_garbage: Optional[Iterable[int]] = None,
    piece_stream: Optional[Sequence[str]] = None,
    piece_stream_offset: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the SBP ``start`` snapshot for the current state.

    The pinned frostetra build always places its internal queue head, which is
    ``queue[0]`` when ``hold`` is null and ``active`` when ``hold`` is set
    (empirically verified; the SBP/1 text says the queue excludes ``active``).
    ``combo`` is converted from our ``-1 = none`` convention to the engine's
    "number of consecutive clears" convention.
    """
    if state.current is None:
        raise SBPError("cannot build a start message without a current piece")
    current = state.current.name
    n = state.ruleset.board.preview if preview_count is None else int(preview_count)
    previews = state.preview(max(0, n))
    if incoming_garbage is None:
        garbage = [int(entry.amount) for entry in state.garbage.entries if entry.amount > 0]
    else:
        garbage = [int(amount) for amount in incoming_garbage if int(amount) > 0]
    # The pinned engine builds its internal queue as
    # ``[active] + queue`` when ``hold`` is set, and as ``queue`` when it is
    # null.  ``queue[0]`` is always the piece it searches for.  So:
    #   * hold empty  -> active=current and queue=[current, *previews]
    #   * hold set    -> active=current and queue=[*previews]
    # Repeating the current piece in both fields would make the engine search
    # the current piece twice when a hold exists.
    queue = [current, *previews] if state.hold is None else [*previews]
    message: Dict[str, Any] = {
        "type": "start",
        "board": board_to_sbp_rows(state.board),
        "active": current,
        "queue": queue,
        "hold": state.hold,
        "combo": max(0, int(state.combo) + 1),
        "back_to_back": int(state.b2b_count),
        "incoming_garbage": garbage,
    }
    if piece_stream is not None:
        stream: Dict[str, Any] = {"pieces": list(piece_stream)}
        if piece_stream_offset is not None:
            stream["offset"] = int(piece_stream_offset)
        message["piece_stream"] = stream
    return message


def sbp_move_cells(
    move: Dict[str, Any], board_height: int = SBP_HEIGHT
) -> Tuple[str, Set[Tuple[int, int]]]:
    """Convert an SBP placement into ``(piece, cells)`` in our top-down board.

    SBP's anchor is the SRS rotation centre: absolute bottom-up cell
    ``(x + dx, y + dy)``.  Our board uses top-down rows, so ``y`` is mirrored.
    """
    location = move.get("location", move)
    piece = str(location["piece"])
    if piece not in SBP_NORTH_CELLS:
        raise SBPError(f"unknown piece type {piece!r}")
    orientation = str(location.get("orientation", "north"))
    if orientation not in SBP_ORIENTATIONS:
        raise SBPError(f"unknown orientation {orientation!r}")
    rotation = SBP_ORIENTATIONS[orientation]
    x = int(location["x"])
    y = int(location["y"])
    cells: Set[Tuple[int, int]] = set()
    for cell_x, cell_y in SBP_NORTH_CELLS[piece]:
        sx, sy = _rotate_cell(rotation, (cell_x, cell_y))
        board_x, board_y_up = x + sx, y + sy
        if not (0 <= board_x < SBP_WIDTH and 0 <= board_y_up < board_height):
            raise SBPError(f"move cell ({board_x}, {board_y_up}) is outside the board")
        cells.add((board_x, board_height - 1 - board_y_up))
    if len(cells) != 4:
        raise SBPError(f"move does not contain 4 distinct cells: {move!r}")
    return piece, cells


def _rotate_cell(orientation: int, cell: Tuple[int, int]) -> Tuple[int, int]:
    """SBP/1 relative-cell transform (y grows upward)."""
    x, y = cell
    if orientation == 0:  # north
        return x, y
    if orientation == 1:  # east
        return y, -x
    if orientation == 2:  # south
        return -x, -y
    if orientation == 3:  # west
        return -y, x
    raise SBPError(f"invalid orientation {orientation}")


def action_for_sbp_move(move: Dict[str, Any], state: GameState) -> Optional[int]:
    """Map an SBP placement to a legal placement action id, or ``None``.

    Matching is geometric (the four absolute cells) and prefers the hold flag
    implied by which piece the engine placed.  A cell-identical action with the
    other hold flag is accepted as a fallback (duplicate piece types).
    """
    if state.current is None:
        return None
    try:
        piece, target = sbp_move_cells(move, state.board.height)
    except (SBPError, KeyError, TypeError, ValueError):
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


def parse_suggestion(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Validate and return the moves of a ``suggestion`` message."""
    if message.get("type") != "suggestion":
        raise SBPError(f"expected a suggestion message, got {message.get('type')!r}")
    moves = message.get("moves")
    if not isinstance(moves, list):
        raise SBPError("suggestion message has no 'moves' list")
    return moves


# ---------------------------------------------------------------------------
# Subprocess session
# ---------------------------------------------------------------------------
_EOF = object()


class SBPSession:
    """A live frostetra (or any SBP bot) subprocess with non-blocking reads."""

    def __init__(self, command: Sequence[str], *, handshake_timeout: float = 10.0) -> None:
        self.command = list(command)
        self.handshake_timeout = float(handshake_timeout)
        self.register_message: Dict[str, Any] = {}
        self.capabilities: Dict[str, Any] = {}
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
        self._stdout_thread = threading.Thread(target=self._read_stdout, name="sbp-stdout", daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, name="sbp-stderr", daemon=True)
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

    def _process_error(self, what: str) -> SBPProcessError:
        code = self.proc.poll()
        tail = self.stderr_tail()
        return SBPProcessError(
            f"{what}: engine exited (code {code})" + (f"; stderr: {tail}" if tail else "")
        )

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
                raise SBPTimeout(f"timed out waiting for engine message after {timeout:.3f}s")
            try:
                item = self._messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise SBPTimeout(f"timed out waiting for engine message after {timeout:.3f}s") from exc
            if item is _EOF:
                raise self._process_error("engine closed stdout")
            return item

    def wait_for(self, types: Iterable[str], timeout: float) -> Dict[str, Any]:
        wanted = set(types)
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SBPTimeout(f"timed out waiting for {sorted(wanted)}")
            message = self.read_message(remaining)
            if message.get("type") in wanted:
                return message

    def drain(self) -> None:
        while True:
            try:
                self._messages.get_nowait()
            except queue.Empty:
                return

    # -- lifecycle ------------------------------------------------------
    def handshake(self, rules: Dict[str, Any]) -> Dict[str, Any]:
        """Receive ``register``, send ``rules``, wait for ``ready``."""
        register = self.wait_for(("register", "error"), self.handshake_timeout)
        if register.get("type") == "error":
            raise SBPError(f"engine failed to start: {register.get('reason')}")
        self.register_message = dict(register)
        capabilities = register.get("capabilities")
        self.capabilities = dict(capabilities) if isinstance(capabilities, dict) else {}
        self._validate_capabilities(rules)
        self.send(rules)
        reply = self.wait_for(("ready", "error"), self.handshake_timeout)
        if reply.get("type") == "error":
            raise SBPError(f"engine rejected rules: {reply.get('reason')}")
        return self.register_message

    def _validate_capabilities(self, rules: Dict[str, Any]) -> None:
        caps = self.capabilities
        if not caps:
            return  # capabilities are optional in SBP/1
        kicksets = caps.get("kicksets")
        if isinstance(kicksets, list) and rules["kickset"] not in kicksets:
            raise SBPError(f"engine does not advertise kickset {rules['kickset']!r}: {kicksets}")
        if rules.get("rot180") and not caps.get("rot180", False):
            raise SBPError("engine does not advertise rot180")
        randomizer = rules.get("randomizer")
        randomizers = caps.get("randomizers")
        if randomizer and isinstance(randomizers, list) and randomizer not in randomizers:
            raise SBPError(f"engine does not advertise randomizer {randomizer!r}: {randomizers}")
        modes = caps.get("spin_detection")
        if isinstance(modes, list) and rules["spin_detection"] not in modes:
            raise SBPError(
                f"engine does not advertise spin_detection {rules['spin_detection']!r}: {modes}"
            )
        size = caps.get("board_size")
        if isinstance(size, dict):
            width = size.get("width")
            height = size.get("height")
            requested_width = rules["board_size"]["width"]
            requested_height = rules["board_size"]["height"]
            if not _range_contains(width, requested_width):
                raise SBPError(f"engine does not support board width {requested_width}: {width}")
            if not _range_contains(height, requested_height):
                raise SBPError(f"engine does not support board height {requested_height}: {height}")

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


def _range_contains(spec: Any, value: int) -> bool:
    """SBP capability range: an integer or ``{min, max}``."""
    if isinstance(spec, bool):
        return False
    if isinstance(spec, int):
        return spec == value
    if isinstance(spec, dict):
        low, high = spec.get("min"), spec.get("max")
        return isinstance(low, int) and isinstance(high, int) and low <= value <= high
    return False


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
@dataclass
class FrostetraStats:
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
    garbage_queries: int = 0
    orientation_counts: Dict[str, int] = field(default_factory=dict)
    spin_counts: Dict[str, int] = field(default_factory=dict)
    last_move_info: Dict[str, Any] = field(default_factory=dict)
    last_error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        out = dict(self.__dict__)
        if self.suggestions:
            out["mean_answer_latency_ms"] = round(self.answer_latency_ms / self.suggestions, 3)
        return out


class FrostetraAgent(BaseAgent):
    """Frostetra (SBP/1) as a versus opponent.

    Parameters
    ----------
    binary:
        Path to the release binary.  Defaults to the clone under
        ``third_party/frostetra`` (or ``$TETRISRL_FROSTETRA_BIN``).
    config_path:
        Optional JSON config passed as ``--config``.  Tests use a seeded,
        per-suggestion budget config; matches use the engine defaults.
    command:
        Full command override (tests use it to launch a broken command).
    think_time:
        Seconds to let background search run after ``start`` before asking for
        a suggestion.  The engine's default budget is a 3M-node background cap
        with 4 workers.
    timeout:
        Deadline for a suggestion (including ``think_time``).
    fallback:
        Agent used when the engine is unavailable, times out, or suggests a
        placement our action space cannot express.
    allow_in_tests:
        Required under pytest; without it the adapter refuses to spawn a
        process so test collection can never start an engine.
    """

    name = "frostetra"

    def __init__(
        self,
        binary: Optional[str | os.PathLike[str]] = None,
        *,
        config_path: Optional[str | os.PathLike[str]] = None,
        think_time: float = 0.08,
        timeout: float = 5.0,
        handshake_timeout: float = 10.0,
        fallback: Optional[BaseAgent] = None,
        command: Optional[Sequence[str]] = None,
        allow_in_tests: bool = False,
        preview_count: Optional[int] = None,
        use_piece_stream: bool = True,
        randomizer: Optional[str] = "seven_bag",
        send_advance: bool = True,
        name: Optional[str] = None,
    ) -> None:
        self.binary = frostetra_binary_path(binary)
        self.config_path = Path(config_path).expanduser() if config_path else None
        self.think_time = max(0.0, float(think_time))
        self.timeout = max(0.001, float(timeout))
        self.handshake_timeout = max(0.001, float(handshake_timeout))
        self.command = list(command) if command is not None else None
        self.allow_in_tests = bool(allow_in_tests)
        self.preview_count = preview_count
        self.use_piece_stream = bool(use_piece_stream)
        self.randomizer = randomizer
        self.send_advance = bool(send_advance)
        if name:
            self.name = name
        self.stats = FrostetraStats()
        self.seed = 0
        self._fallback: BaseAgent = fallback if fallback is not None else HeuristicAgent(seed=0)
        self._session: Optional[SBPSession] = None
        self._rules: Optional[Dict[str, Any]] = None
        self._stream: List[str] = []
        self._stream_base: Optional[int] = None
        self._stream_initialized = False
        self.last_suggestion: Optional[Dict[str, Any]] = None
        self.engine_info: Dict[str, Any] = {}
        self._last_opponent: Optional[GameState] = None
        self._last_search_info: Dict[str, Any] = {}

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
        self.stats = FrostetraStats()
        self.last_suggestion = None
        self._stream = []
        self._stream_base = None
        self._stream_initialized = False

    def observe(self, state: GameState, opponent_state: Optional[GameState] = None) -> Dict[str, Any]:
        return {}

    def receive_result(self, result: Any) -> None:
        return None

    def terminate(self) -> None:
        self._close_session()

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int:
        self._last_opponent = opponent_state
        self.last_suggestion = None
        if state.current is None or state.finished or not state.legal_actions():
            return -1
        self._track_piece_stream(state)
        try:
            moves = self._request_suggestion(state)
        except SBPTimeout as exc:
            self.stats.timeouts += 1
            self.stats.last_error = str(exc)
            self._abort_session()
            return self._fallback_action(state, opponent_state)
        except Exception as exc:  # never let a broken engine crash a match
            self.stats.protocol_errors += 1
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
            self._abort_session()
            return self._fallback_action(state, opponent_state)

        if not moves:
            self.stats.invalid_suggestions += 1
            self.stats.last_error = "engine returned no moves"
            return self._fallback_action(state, opponent_state)

        for move in moves:
            action = action_for_sbp_move(move, state)
            if action is None:
                continue
            self.last_suggestion = move
            self.stats.accepted += 1
            location = move.get("location", move) if isinstance(move, dict) else {}
            orientation = str(location.get("orientation", "?"))
            spin = str(move.get("spin", "?")) if isinstance(move, dict) else "?"
            self.stats.orientation_counts[orientation] = (
                self.stats.orientation_counts.get(orientation, 0) + 1
            )
            self.stats.spin_counts[spin] = self.stats.spin_counts.get(spin, 0) + 1
            if self.send_advance:
                self._send_advance(move)
            return action

        self.stats.invalid_suggestions += 1
        self.stats.last_error = (
            f"none of {len(moves)} suggested placements is expressible in our action space: "
            f"{moves!r}"
        )
        return self._fallback_action(state, opponent_state)

    # -- piece/queue bookkeeping ---------------------------------------
    def _track_piece_stream(self, state: GameState) -> None:
        """Maintain the observed generated-piece order for ``start.piece_stream``.

        The engine's queue convention forces us to repeat the current piece in
        ``queue``; feeding the same repetition to its seven-bag tracker would
        corrupt the inferred bag.  ``piece_stream`` lets us send the true
        generated order instead (an advertised capability).

        The stream starts at generation index 0 (a game's first piece starts a
        seven-bag).  On each state we extend the known tail with the newly
        visible previews; if no suffix overlap is found (e.g. after a hold or a
        resync) we restart with an unknown absolute offset rather than invent
        one.
        """
        if not self.use_piece_stream:
            return
        n = (
            state.ruleset.board.preview
            if self.preview_count is None
            else int(self.preview_count)
        )
        previews = state.preview(max(0, n))
        current = state.current.name if state.current is not None else ""
        if not self._stream_initialized:
            self._stream = [current, *previews]
            self._stream_base = 0
            self._stream_initialized = True
            return
        overlap = 0
        for k in range(min(len(self._stream), len(previews)), 0, -1):
            if self._stream[-k:] == previews[:k]:
                overlap = k
                break
        if overlap == 0:
            self._stream = [current, *previews]
            self._stream_base = None
        else:
            self._stream.extend(previews[overlap:])
        if len(self._stream) > PIECE_STREAM_WINDOW:
            drop = len(self._stream) - PIECE_STREAM_WINDOW
            self._stream = self._stream[drop:]
            if self._stream_base is not None:
                self._stream_base += drop

    def _piece_stream_payload(self) -> Tuple[Optional[List[str]], Optional[int]]:
        if not self.use_piece_stream or not self._stream:
            return None, None
        return list(self._stream), self._stream_base

    # -- internals ------------------------------------------------------
    def _fallback_action(self, state: GameState, opponent_state: Optional[GameState]) -> int:
        self.stats.fallbacks += 1
        action = self._fallback.choose_action(state, opponent_state)
        if not isinstance(action, int) or action < 0 or not state.action_mask()[action]:
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

    def _ensure_session(self, state: GameState) -> SBPSession:
        if self._session is not None and self._session.alive():
            return self._session
        if self._session is not None:
            self._session.close()
            self._session = None
            self.stats.engine_restarts += 1
        if os.environ.get("TETRISRL_SBP_DISABLE") == "1" or os.environ.get("TETRISRL_FROSTETRA_DISABLE") == "1":
            raise SBPError("engine launch disabled by TETRISRL_SBP_DISABLE/TETRISRL_FROSTETRA_DISABLE=1")
        if _pytest_active() and not self.allow_in_tests:
            raise SBPError(
                "FrostetraAgent refuses to launch an engine under pytest "
                "(test-collection guard); pass allow_in_tests=True explicitly"
            )
        command = self._launch_command()
        if self.command is None and not frostetra_available(self.binary):
            raise SBPProcessError(
                f"frostetra binary not found/executable at {self.binary}; "
                "build it with `cargo build --release` in third_party/frostetra"
            )
        rules = build_rules_message(state, randomizer=self.randomizer)
        session = SBPSession(command, handshake_timeout=self.handshake_timeout)
        try:
            self.engine_info = session.handshake(rules)
        except Exception:
            session.close()
            raise
        self._rules = rules
        self.stats.engine_starts += 1
        self._session = session
        return session

    def _request_suggestion(self, state: GameState) -> List[Dict[str, Any]]:
        session = self._ensure_session(state)
        session.drain()  # drop any late reply from a previous timeout
        pending = [int(entry.amount) for entry in state.garbage.entries if entry.amount > 0]
        pieces, offset = self._piece_stream_payload()
        session.send(
            build_start_message(
                state,
                preview_count=self.preview_count,
                incoming_garbage=pending,
                piece_stream=pieces,
                piece_stream_offset=offset,
            )
        )
        started = time.monotonic()
        self._last_search_info = {}
        budget = self.timeout
        sleep_for = min(self.think_time, budget * 0.5)
        if sleep_for > 0:
            time.sleep(sleep_for)
        deadline = started + budget
        while time.monotonic() < deadline:
            # Pending garbage is repeated on ``suggest`` per SBP/1 so a bot that
            # reads this field can use it; the pinned build ignores it.
            suggest: Dict[str, Any] = {"type": "suggest"}
            if pending:
                suggest["incoming_garbage"] = pending
                self.stats.garbage_queries += 1
            session.send(suggest)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            reply = self._wait_for_suggestion(session, deadline)
            if reply.get("type") == "error":
                raise SBPError(f"engine error: {reply.get('reason')}")
            moves = parse_suggestion(reply)
            if moves:
                self.stats.suggestions += 1
                self.stats.answer_latency_ms += (time.monotonic() - started) * 1000.0
                self.stats.last_move_info = dict(self._last_search_info)
                version = session.register_message.get("version")
                if version:
                    self.stats.last_move_info["engine_version"] = version
                return moves
            time.sleep(min(0.003, self.think_time) if self.think_time else 0.001)
        raise SBPTimeout(f"engine produced no suggestion within {self.timeout:.3f}s")

    def _wait_for_suggestion(self, session: SBPSession, deadline: float) -> Dict[str, Any]:
        """Read messages until ``suggestion``/``error``, recording ``info``."""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SBPTimeout(
                    f"engine produced no suggestion within {self.timeout:.3f}s"
                )
            message = session.read_message(remaining)
            if message.get("type") == "info":
                self._record_info(message)
                continue
            return message

    def _record_info(self, message: Dict[str, Any]) -> None:
        """Capture ``info`` messages (search statistics / runtime notes)."""
        topic = message.get("topic")
        data = message.get("data")
        if topic == "search" and isinstance(data, dict):
            try:
                self.stats.nodes_total += int(data.get("nodes", 0) or 0)
            except (TypeError, ValueError):
                pass
            self._last_search_info = dict(data)

    def _send_advance(self, move: Dict[str, Any]) -> None:
        """Best-effort ``advance``; the next piece re-syncs with ``start`` anyway."""
        if self._session is None:
            return
        try:
            self._session.send({"type": "advance", "move": move})
        except SBPError as exc:
            self.stats.protocol_errors += 1
            self.stats.last_error = f"advance failed: {exc}"
            self._close_session()

    def _abort_session(self) -> None:
        if self._session is None:
            return
        try:
            self._session.send({"type": "stop", "reason": "adapter_fallback"})
        except SBPError:
            pass
        self._close_session(restart=True)

    def _close_session(self, restart: bool = False) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
            if restart:
                self.stats.engine_restarts += 1

    def __del__(self) -> None:  # best effort; explicit terminate() is preferred
        try:
            self._close_session()
        except Exception:
            pass


__all__ = [
    "DEFAULT_BINARY",
    "FrostetraAgent",
    "FrostetraStats",
    "SBPError",
    "SBPProcessError",
    "SBPSession",
    "SBPTimeout",
    "SBP_HEIGHT",
    "SBP_NORTH_CELLS",
    "SBP_ORIENTATIONS",
    "SBP_WIDTH",
    "action_for_sbp_move",
    "board_to_sbp_rows",
    "build_rules_message",
    "build_start_message",
    "frostetra_available",
    "frostetra_binary_path",
    "parse_suggestion",
    "sbp_move_cells",
]
