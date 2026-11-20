"""Blockfish opponent adapter: a **cheese / downstacking specialist**.

Blockfish (https://github.com/blockfish/blockfish, LGPL-2.1) is a Rust
cheese-race engine: its objective is to clear a garbage stack using as few
pieces as possible.  It models neither versus play nor TETR.IO Season 2.  This
adapter therefore exposes it as ``specialist = "cheese"`` and explicitly marks
it as **not a versus benchmark**.  Use it for downstacking experiments and as a
clearly-labelled specialist, never as evidence of competitive strength.

Scope and honesty notes
-----------------------
* Blockfish is used only as a **placement suggester**.  This module speaks its
  protobuf-over-stdio service protocol in a subprocess (no blockfish source is
  copied into this repository; LGPL compliance relies on the subprocess
  boundary and the notice in ``third_party/BLOCKFISH_NOTICE.md``).
  :mod:`tetrisrl.environment.versus` remains the sole authority for attack,
  garbage, cancellation, B2B charging and Surge.
* Blockfish has no 180-degree rotation, no spin detection, no attack, no B2B
  and no incoming-garbage queue beyond the cheese rows it can see on the board.
  It cannot plan around pending garbage, and it cannot represent TETR.IO
  Season 2 mechanics.
* Its service is **stateless per analysis**: we send a full snapshot (board,
  hold, queue) for every piece and receive a key-input sequence.  The adapter
  replays that sequence on our own board and maps the resulting placement to
  one of our placement action ids; placements our action space cannot express
  (tucks reached only via soft/quick drops it chose, multiple kicks, etc.)
  fall back to the in-repo heuristic and are counted.

Protocol mapping (verified against the pinned source)
-----------------------------------------------------
* ``blockfish.proto``: ``Request.analyze.snapshot`` carries ``hold`` (string),
  ``queue`` (string) and ``rows`` (repeated string).  The service reads
  messages length-delimited with a protobuf varint prefix on stdin and writes
  the same framing on stdout (``CodedInputStream::read_message`` /
  ``write_message_no_tag``).
* ``rows`` are 10-column strings ordered **bottom line first**
  (``blockfish-js/src/ai.js`` documents this, and ``service.rs::matrix`` indexes
  the first string as row 0).  Any alphabetic character marks an occupied cell
  (``Color::try_from`` accepts alphabetic chars); this adapter sends ``X`` for
  occupied and ``.`` for empty.
* Blockfish's board is 10x25 (20 visible + 5 hidden).  Our board is 10x40
  (20 visible + 20 buffer).  We send exactly the **bottom 25 rows of our
  board**, reversed: our rows ``[height-25 : height]`` (top-down) become
  blockfish rows 0..24 (bottom-up).  Our rows above that window are above
  blockfish's snapshot; they are dropped and counted in
  ``stats.board_rows_unrepresentable``.  They are only occupied when the stack
  has already reached the hidden buffer, i.e. near top-out.
* ``hold``/``queue`` pieces use the letters ``IOTSZJL``.  The queue is
  ``[current, *previews]``; ``hold`` is empty when our hold slot is empty.
  Blockfish treats ``queue[0]`` as the current piece and derives the hold
  target itself, which matches our hold semantics.
* ``Suggestion.inputs`` is a key sequence over ``left, right, cw, ccw, hold,
  sd, hd`` (``sd`` is a sonic/hard drop in blockfish).  ``rating`` is a cost:
  lower is better.  We take the first (best) suggestion and replay its inputs
  from our current spawn with guideline SRS kicks; the resulting four cells are
  matched against ``state.legal_actions()``.

The adapter never launches a process at import time or during pytest
collection: the subprocess is created lazily on the first ``choose_action`` and
refuses to launch under pytest unless ``allow_in_tests=True``.
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from ..base import BaseAgent
from ..heuristic_agent import HeuristicAgent
from ...environment.board import Board
from ...environment.engine import GameState
from ...environment.pieces import CELLS
from ...environment.placement import spawn_x
from ...environment.rotation import build_kick_tables

#: Pinned upstream commit (``git -C third_party/blockfish rev-parse HEAD``).
BLOCKFISH_COMMIT = "739953f9331b7648f269fc52cff5aae330108ccd"

#: Blockfish's fixed snapshot geometry: 10 columns, 25 rows (20 visible + 5).
BLOCKFISH_WIDTH = 10
BLOCKFISH_ROWS = 25

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BINARY = _REPO_ROOT / "third_party" / "blockfish" / "target" / "release" / "blockfish"

#: The service protobuf ``Input`` enum, in wire-value order.
INPUT_NAMES: Tuple[str, ...] = ("left", "right", "cw", "ccw", "hold", "sd", "hd")


class BlockfishError(RuntimeError):
    """Base class for protocol/process failures."""


class BlockfishTimeout(BlockfishError):
    """The engine did not answer within the configured timeout."""


class BlockfishProcessError(BlockfishError):
    """The engine process exited, could not start, or a pipe broke."""


def _pytest_active() -> bool:
    return "pytest" in sys.modules or "_pytest" in sys.modules


def blockfish_binary_path(binary: Optional[str | os.PathLike[str]] = None) -> Path:
    """Resolve the blockfish service binary (argument, env override, default)."""
    if binary is not None:
        return Path(binary).expanduser()
    env = os.environ.get("TETRISRL_BLOCKFISH_BIN")
    if env:
        return Path(env).expanduser()
    return DEFAULT_BINARY


def blockfish_available(binary: Optional[str | os.PathLike[str]] = None) -> bool:
    """True when the service binary exists and is executable."""
    path = blockfish_binary_path(binary)
    return path.is_file() and os.access(path, os.X_OK)


# ---------------------------------------------------------------------------
# Minimal protobuf wire encoding / decoding
# ---------------------------------------------------------------------------
# We only need the handful of messages in blockfish.proto.  A tiny local codec
# avoids pulling `google.protobuf` into this project's runtime requirements and
# keeps the adapter self-contained.  It is *not* a general protobuf library.


def _encode_varint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        raise ValueError("varint must be non-negative")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _encode_tag(field_number: int, wire_type: int) -> bytes:
    return _encode_varint((field_number << 3) | wire_type)


def _encode_uint(field_number: int, value: int) -> bytes:
    return _encode_tag(field_number, 0) + _encode_varint(value)


def _encode_bytes(field_number: int, payload: bytes) -> bytes:
    return _encode_tag(field_number, 2) + _encode_varint(len(payload)) + payload


def _decode_varint(data: bytes, pos: int = 0) -> Tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise BlockfishError("truncated protobuf varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 70:
            raise BlockfishError("protobuf varint too long")


def iter_fields(data: bytes) -> Iterator[Tuple[int, int, Any]]:
    """Yield ``(field_number, wire_type, value)`` tuples from a message."""
    pos = 0
    while pos < len(data):
        key, pos = _decode_varint(data, pos)
        field_number, wire_type = key >> 3, key & 7
        if wire_type == 0:
            value, pos = _decode_varint(data, pos)
        elif wire_type == 1:
            if pos + 8 > len(data):
                raise BlockfishError("truncated fixed64 field")
            value = data[pos : pos + 8]
            pos += 8
        elif wire_type == 2:
            length, pos = _decode_varint(data, pos)
            if pos + length > len(data):
                raise BlockfishError("truncated length-delimited field")
            value = data[pos : pos + length]
            pos += length
        elif wire_type == 5:
            if pos + 4 > len(data):
                raise BlockfishError("truncated fixed32 field")
            value = data[pos : pos + 4]
            pos += 4
        else:
            raise BlockfishError(f"unsupported protobuf wire type {wire_type}")
        yield field_number, wire_type, value


def _first_field(data: bytes, field_number: int, default: Any = None) -> Any:
    for number, _wire, value in iter_fields(data):
        if number == field_number:
            return value
    return default


def _packed_varints(data: bytes) -> List[int]:
    values: List[int] = []
    pos = 0
    while pos < len(data):
        value, pos = _decode_varint(data, pos)
        values.append(value)
    return values


def _zigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BlockfishSnapshot:
    """The three fields of ``blockfish.Snapshot`` plus mapping diagnostics."""

    hold: str
    queue: List[str]
    rows: List[str]
    unrepresentable_rows: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "hold": self.hold,
            "queue": list(self.queue),
            "rows": list(self.rows),
            "unrepresentable_rows": self.unrepresentable_rows,
        }


def board_to_blockfish_rows(board: Board) -> Tuple[List[str], int]:
    """Encode a board as blockfish rows (bottom-first, 10x25).

    Returns ``(rows, unrepresentable_occupied_rows)``.  Our bottom
    :data:`BLOCKFISH_ROWS` rows are sent; any occupied row above that window
    cannot be represented and is counted (never silently "padded" into the
    snapshot).
    """
    if board.width != BLOCKFISH_WIDTH:
        raise BlockfishError(
            f"blockfish requires a {BLOCKFISH_WIDTH}-column board, got {board.width}"
        )
    start = max(0, board.height - BLOCKFISH_ROWS)
    unrepresentable = sum(1 for row in board.rows[:start] if row)
    rows: List[str] = []
    # Bottom-first on the wire: our last board row is blockfish row 0.
    for y in range(board.height - 1, start - 1, -1):
        mask = board.rows[y]
        rows.append(
            "".join("X" if (mask >> x) & 1 else "." for x in range(BLOCKFISH_WIDTH))
        )
    return rows, unrepresentable


def build_snapshot(
    state: GameState,
    *,
    preview_count: Optional[int] = None,
) -> BlockfishSnapshot:
    """Build the blockfish snapshot for the current state.

    ``queue`` is ``[current, *previews]`` (blockfish derives the hold target
    itself).  ``hold`` is ``""`` when our hold slot is empty.
    """
    if state.current is None:
        raise BlockfishError("cannot build a snapshot without a current piece")
    n = state.ruleset.board.preview if preview_count is None else int(preview_count)
    previews = state.preview(max(0, n))
    rows, unrepresentable = board_to_blockfish_rows(state.board)
    return BlockfishSnapshot(
        hold=state.hold or "",
        queue=[state.current.name, *previews],
        rows=rows,
        unrepresentable_rows=unrepresentable,
    )


def encode_config_request(
    node_limit: int,
    *,
    max_results: int = 1,
    max_placements: int = 1,
) -> bytes:
    """Encode ``Request.set_config`` (fields 1/3/4 of ``Request.Config``)."""
    config = b""
    if node_limit > 0:
        config += _encode_uint(1, int(node_limit))
    if max_results > 0:
        config += _encode_uint(3, int(max_results))
    if max_placements > 0:
        config += _encode_uint(4, int(max_placements))
    return _encode_bytes(1, config)


def encode_analyze_request(
    request_id: int,
    snapshot: BlockfishSnapshot,
) -> bytes:
    """Encode ``Request.analyze`` with its snapshot."""
    payload = _encode_uint(1, int(request_id))
    snap = b""
    snap += _encode_bytes(1, snapshot.hold.encode("ascii"))
    snap += _encode_bytes(2, "".join(snapshot.queue).encode("ascii"))
    for row in snapshot.rows:
        snap += _encode_bytes(3, row.encode("ascii"))
    payload += _encode_bytes(2, snap)
    return _encode_bytes(3, payload)


# ---------------------------------------------------------------------------
# Response decoding
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BlockfishSuggestion:
    """One ``Response.Analysis.Suggestion``."""

    rating: int
    inputs: Tuple[str, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {"rating": self.rating, "inputs": list(self.inputs)}


@dataclass
class BlockfishAnalysis:
    """A decoded ``Response.finished`` message."""

    request_id: int
    stats: Dict[str, int] = field(default_factory=dict)
    suggestions: List[BlockfishSuggestion] = field(default_factory=list)


def parse_greeting(message: bytes) -> Dict[str, Any]:
    """Decode ``Response.greeting`` fields (version, motd)."""
    greeting = _first_field(message, 1)
    if not isinstance(greeting, bytes):
        raise BlockfishError("response is not a greeting")
    version = _first_field(greeting, 1, b"") or b""
    motd = _first_field(greeting, 2, b"") or b""
    return {"version": version.decode("utf-8", "replace"), "motd": motd.decode("utf-8", "replace")}


def parse_analysis(message: bytes) -> BlockfishAnalysis:
    """Decode ``Response.finished`` (id, stats, suggestions)."""
    finished = _first_field(message, 2)
    if not isinstance(finished, bytes):
        raise BlockfishError("response is not an analysis")
    request_id = int(_first_field(finished, 1, 0))
    stats: Dict[str, int] = {}
    raw_stats = _first_field(finished, 2)
    if isinstance(raw_stats, bytes):
        for name, number in (("nodes", 1), ("iterations", 2), ("time_taken_millis", 3)):
            value = _first_field(raw_stats, number)
            if value is not None:
                stats[name] = int(value)
    suggestions: List[BlockfishSuggestion] = []
    for number, _wire, value in iter_fields(finished):
        if number != 3 or not isinstance(value, bytes):
            continue
        rating_raw = _first_field(value, 1, 0)
        rating = _zigzag(int(rating_raw))
        inputs: List[str] = []
        for field_number, wire_type, field_value in iter_fields(value):
            if field_number != 2:
                continue
            if wire_type == 2:
                raw_values = _packed_varints(field_value)
            elif wire_type == 0:
                raw_values = [int(field_value)]
            else:
                raise BlockfishError(f"unexpected wire type {wire_type} for Input")
            for raw in raw_values:
                if not (0 <= raw < len(INPUT_NAMES)):
                    raise BlockfishError(f"unknown blockfish Input enum value {raw}")
                inputs.append(INPUT_NAMES[raw])
        suggestions.append(BlockfishSuggestion(rating=rating, inputs=tuple(inputs)))
    return BlockfishAnalysis(request_id=request_id, stats=stats, suggestions=suggestions)


# ---------------------------------------------------------------------------
# Input-sequence replay and action mapping
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SimulatedPlacement:
    """A blockfish key sequence replayed on our board."""

    piece: str
    rotation: int
    cells: Tuple[Tuple[int, int], ...]
    hold_used: bool

    @property
    def column(self) -> int:
        return min(x for x, _y in self.cells)


_GUIDELINE_KICK_TABLES: Optional[Dict[str, Dict[Tuple[int, int], Sequence[Tuple[int, int]]]]] = None


def guideline_kick_tables() -> Dict[str, Dict[Tuple[int, int], Sequence[Tuple[int, int]]]]:
    """Pure guideline SRS kicks (blockfish's ruleset), cached."""
    global _GUIDELINE_KICK_TABLES
    if _GUIDELINE_KICK_TABLES is None:
        _GUIDELINE_KICK_TABLES = build_kick_tables("srs")
    return _GUIDELINE_KICK_TABLES


def simulate_inputs(
    state: GameState,
    inputs: Iterable[str],
    *,
    kick_tables: Optional[Dict[str, Dict[Tuple[int, int], Sequence[Tuple[int, int]]]]] = None,
) -> Optional[SimulatedPlacement]:
    """Replay blockfish inputs from our spawn and return the final placement.

    Blockfish computes its inputs from the spawn position using guideline SRS
    (no 180-degree rotation).  We replay them on our board with guideline SRS
    kicks so the resulting cells can be compared with our placement actions.
    Returns ``None`` if the sequence cannot be replayed (which the caller
    counts as an invalid suggestion and falls back on).
    """
    if state.current is None:
        return None
    tables = kick_tables if kick_tables is not None else guideline_kick_tables()
    board = state.board
    piece = state.current.name
    rotation = state.current.rotation % 4
    box_x = state.current.x
    box_y = state.current.y
    hold = state.hold
    can_hold = state.can_hold
    hold_used = False

    def cells(p: str, r: int, x: int, y: int) -> Tuple[Tuple[int, int], ...]:
        return tuple((x + cx, y + cy) for cx, cy in CELLS[p][r % 4])

    def fits(p: str, r: int, x: int, y: int) -> bool:
        return board.fits(cells(p, r, x, y))

    def sonic_drop(p: str, r: int, x: int, y: int) -> int:
        while fits(p, r, x, y + 1):
            y += 1
        return y

    for raw in inputs:
        name = str(raw).lower()
        if name == "hold":
            if not can_hold or hold_used:
                return None
            previous = piece
            if hold is None:
                preview = state.preview(1)
                if not preview:
                    return None
                piece = preview[0]
            else:
                piece = hold
            hold = previous
            hold_used = True
            can_hold = False
            rotation = 0
            box_x = spawn_x(piece)
            box_y = state.ruleset.board.spawn_y
            if not fits(piece, rotation, box_x, box_y):
                return None
        elif name in ("left", "right"):
            dx = -1 if name == "left" else 1
            if fits(piece, rotation, box_x + dx, box_y):
                box_x += dx
        elif name in ("cw", "ccw"):
            target = (rotation + (1 if name == "cw" else -1)) % 4
            kicks = tables.get(piece, {}).get((rotation, target), ((0, 0),))
            for dx, dy_up in kicks:
                if fits(piece, target, box_x + dx, box_y - dy_up):
                    rotation = target
                    box_x += dx
                    box_y -= dy_up
                    break
            else:
                return None
        elif name in ("sd", "hd"):
            box_y = sonic_drop(piece, rotation, box_x, box_y)
        else:
            return None

    if not fits(piece, rotation, box_x, box_y):
        return None
    return SimulatedPlacement(
        piece=piece,
        rotation=rotation,
        cells=tuple(sorted(cells(piece, rotation, box_x, box_y))),
        hold_used=hold_used,
    )


def action_for_simulated_placement(
    state: GameState,
    placement: SimulatedPlacement,
) -> Tuple[Optional[int], bool]:
    """Map a simulated placement to a legal action id.

    Returns ``(action, exact)``.  ``exact`` is ``True`` when an action's final
    cells match the replayed cells exactly; otherwise a same-piece,
    same-rotation, same-column legal action is accepted as an approximation
    (``exact=False``).  The returned action is always in
    ``state.legal_actions()``; ``None`` means no mapping was possible.
    """
    target = set(placement.cells)
    exact: List[Tuple[int, int]] = []
    approximate: List[Tuple[int, int]] = []
    for action in state.legal_actions():
        resolved = state.resolve(action)
        if resolved is None or resolved.piece != placement.piece:
            continue
        hold_rank = 0 if bool(resolved.hold) == placement.hold_used else 1
        resolved_cells = set(resolved.cells)
        if resolved_cells == target:
            exact.append((hold_rank, action))
            continue
        if resolved.rotation == placement.rotation and resolved.column == placement.column:
            approximate.append((hold_rank, action))
    if exact:
        return min(exact)[1], True
    if approximate:
        return min(approximate)[1], False
    return None, False


# ---------------------------------------------------------------------------
# Subprocess session
# ---------------------------------------------------------------------------
class BlockfishSession:
    """A live blockfish service subprocess (protobuf, varint-delimited)."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        handshake_timeout: float = 10.0,
    ) -> None:
        self.command = list(command)
        self.handshake_timeout = float(handshake_timeout)
        self.engine_info: Dict[str, Any] = {}
        self._stderr_lines: List[str] = []
        self._closed = False
        self._next_id = 0
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, name="blockfish-stderr", daemon=True
        )
        self._stderr_thread.start()

    # -- diagnostics ----------------------------------------------------
    def _read_stderr(self) -> None:
        try:
            assert self.proc.stderr is not None
            for line in self.proc.stderr:
                text = line.decode("utf-8", "replace").rstrip()
                if not text:
                    continue
                if len(self._stderr_lines) >= 100:
                    self._stderr_lines.pop(0)
                self._stderr_lines.append(text)
        except (ValueError, OSError):
            pass

    def stderr_tail(self, n: int = 10) -> str:
        return "\n".join(self._stderr_lines[-n:])

    def alive(self) -> bool:
        return self.proc.poll() is None

    def _process_error(self, what: str) -> BlockfishProcessError:
        code = self.proc.poll()
        tail = self.stderr_tail()
        return BlockfishProcessError(
            f"{what}: engine exited (code {code})" + (f"; stderr: {tail}" if tail else "")
        )

    # -- framing --------------------------------------------------------
    def _read_exact(self, size: int, deadline: float) -> bytes:
        assert self.proc.stdout is not None
        chunks: List[bytes] = []
        remaining = size
        while remaining > 0:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise BlockfishTimeout("timed out waiting for blockfish response")
            ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
            if not ready:
                raise BlockfishTimeout("timed out waiting for blockfish response")
            chunk = os.read(self.proc.stdout.fileno(), remaining)
            if not chunk:
                raise self._process_error("engine closed stdout")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read_message(self, timeout: float) -> bytes:
        deadline = time.monotonic() + max(0.0, float(timeout))
        length = 0
        shift = 0
        while True:
            byte = self._read_exact(1, deadline)[0]
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
            if shift > 70:
                raise BlockfishError("blockfish message length varint too long")
        return self._read_exact(length, deadline)

    def send(self, message: bytes) -> None:
        if self._closed or not self.alive() or self.proc.stdin is None:
            raise self._process_error("cannot send")
        try:
            self.proc.stdin.write(_encode_varint(len(message)) + message)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise self._process_error(f"broken stdin ({exc})") from exc

    # -- protocol -------------------------------------------------------
    def handshake(self) -> Dict[str, Any]:
        self.engine_info = parse_greeting(self.read_message(self.handshake_timeout))
        return self.engine_info

    def analyze(self, snapshot: BlockfishSnapshot, *, timeout: float) -> BlockfishAnalysis:
        request_id = self._next_id
        self._next_id += 1
        self.send(encode_analyze_request(request_id, snapshot))
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BlockfishTimeout("timed out waiting for blockfish analysis")
            message = self.read_message(remaining)
            analysis = parse_analysis(message)
            if analysis.request_id == request_id:
                return analysis

    # -- lifecycle ------------------------------------------------------
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        if self.alive():
            try:
                self.proc.terminate()
            except OSError:
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
        if self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=0.5)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
@dataclass
class BlockfishStats:
    """Counters exposed for experiments and honest reporting."""

    engine_starts: int = 0
    engine_restarts: int = 0
    analyses: int = 0
    suggestions: int = 0
    accepted: int = 0
    accepted_approx: int = 0
    rejected: int = 0
    fallbacks: int = 0
    timeouts: int = 0
    protocol_errors: int = 0
    answer_latency_ms: float = 0.0
    nodes_total: int = 0
    board_rows_unrepresentable: int = 0
    last_rating: int = 0
    last_inputs: List[str] = field(default_factory=list)
    last_error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        out = dict(self.__dict__)
        if self.analyses:
            out["mean_answer_latency_ms"] = round(self.answer_latency_ms / self.analyses, 3)
        out["accepted"] = self.accepted
        out["accepted_exact"] = self.accepted - self.accepted_approx
        out["fallback_rate"] = self.fallbacks / max(1, self.accepted + self.fallbacks)
        return out


class BlockfishAgent(BaseAgent):
    """Blockfish as a **cheese / downstacking specialist** (not a versus bot).

    Blockfish is a cheese-race engine.  It suggests placements that minimize
    the number of pieces needed to clear a garbage stack; it has no versus
    model, no attack, no B2B charging, no Surge and no TETR.IO Season 2
    mechanics.  Do not present match results against it as a competitive
    versus benchmark.

    Parameters
    ----------
    binary:
        Path to the blockfish service binary (built with
        ``cargo build --release -p blockfish --features service``).  Defaults
        to ``third_party/blockfish/target/release/blockfish`` or
        ``$TETRISRL_BLOCKFISH_BIN``.
    node_limit:
        Search node budget per analysis (blockfish's ``search_limit``).
    timeout:
        Seconds to wait for one analysis response.
    fallback:
        Agent used when the engine is unavailable, times out, or suggests a
        placement our action space cannot express (default: heuristic).
    command:
        Full command override (used by tests / alternative installations).
    allow_in_tests:
        Required to launch under pytest, so test collection can never spawn a
        process by accident.
    """

    name = "blockfish"
    #: Explicit specialist metadata: blockfish is a cheese/downstack engine.
    specialist = "cheese"
    #: Blockfish models neither versus play nor TETR.IO Season 2.
    is_versus_benchmark = False
    not_a_versus_benchmark = True

    def __init__(
        self,
        binary: Optional[str | os.PathLike[str]] = None,
        *,
        node_limit: int = 20_000,
        timeout: float = 10.0,
        handshake_timeout: float = 10.0,
        preview_count: Optional[int] = None,
        fallback: Optional[BaseAgent] = None,
        command: Optional[Sequence[str]] = None,
        allow_in_tests: bool = False,
        name: Optional[str] = None,
    ) -> None:
        self.binary = blockfish_binary_path(binary)
        self.node_limit = max(0, int(node_limit))
        self.timeout = max(0.001, float(timeout))
        self.handshake_timeout = max(0.001, float(handshake_timeout))
        self.preview_count = preview_count
        self.command = list(command) if command is not None else None
        self.allow_in_tests = bool(allow_in_tests)
        if name:
            self.name = name
        self.stats = BlockfishStats()
        self.seed = 0
        self.engine_info: Dict[str, Any] = {}
        self.last_suggestion: Optional[BlockfishSuggestion] = None
        self.last_snapshot: Optional[BlockfishSnapshot] = None
        self._fallback: BaseAgent = fallback if fallback is not None else HeuristicAgent(seed=0)
        self._session: Optional[BlockfishSession] = None

    # -- counters -------------------------------------------------------
    @property
    def fallback_count(self) -> int:
        return self.stats.fallbacks

    @property
    def invalid_count(self) -> int:
        return self.stats.rejected

    # -- BaseAgent API --------------------------------------------------
    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = int(seed)
        self._close_session()
        self._fallback.reset(self.seed)
        self.stats = BlockfishStats()
        self.last_suggestion = None
        self.last_snapshot = None

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
            analysis = self._request_analysis(state)
        except BlockfishTimeout as exc:
            self.stats.timeouts += 1
            self.stats.last_error = str(exc)
            self._close_session()
            return self._fallback_action(state, opponent_state)
        except Exception as exc:  # never let a broken engine crash a match
            self.stats.protocol_errors += 1
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
            self._close_session()
            return self._fallback_action(state, opponent_state)

        if not analysis.suggestions:
            self.stats.rejected += 1
            self.stats.last_error = "engine returned no suggestions"
            return self._fallback_action(state, opponent_state)

        suggestion = analysis.suggestions[0]
        self.last_suggestion = suggestion
        simulated = simulate_inputs(state, suggestion.inputs)
        if simulated is None:
            self.stats.rejected += 1
            self.stats.last_error = f"could not replay suggested inputs: {list(suggestion.inputs)}"
            return self._fallback_action(state, opponent_state)

        action, exact = action_for_simulated_placement(state, simulated)
        if action is None:
            self.stats.rejected += 1
            self.stats.last_error = (
                "suggested placement not expressible in our action space: "
                f"piece={simulated.piece} rot={simulated.rotation} col={simulated.column}"
            )
            return self._fallback_action(state, opponent_state)

        self.stats.accepted += 1
        if not exact:
            self.stats.accepted_approx += 1
        return action

    # -- internals ------------------------------------------------------
    def _fallback_action(self, state: GameState, opponent_state: Optional[GameState]) -> int:
        self.stats.fallbacks += 1
        action = self._fallback.choose_action(state, opponent_state)
        if not isinstance(action, int) or action < 0 or action not in state.legal_actions():
            legal = state.legal_actions()
            return legal[0] if legal else -1
        return action

    def _launch_command(self) -> List[str]:
        if self.command is not None:
            return list(self.command)
        return [str(self.binary)]

    def _ensure_session(self) -> BlockfishSession:
        if self._session is not None and self._session.alive():
            return self._session
        if self._session is not None:
            self._session.close()
            self._session = None
            self.stats.engine_restarts += 1
        if os.environ.get("TETRISRL_BLOCKFISH_DISABLE") == "1":
            raise BlockfishError("engine launch disabled by TETRISRL_BLOCKFISH_DISABLE=1")
        if _pytest_active() and not self.allow_in_tests:
            raise BlockfishError(
                "BlockfishAgent refuses to launch an engine under pytest "
                "(test-collection guard); pass allow_in_tests=True explicitly"
            )
        command = self._launch_command()
        if self.command is None and not blockfish_available(self.binary):
            raise BlockfishProcessError(
                f"blockfish binary not found/executable at {self.binary}; build it with "
                "`cargo build --release -p blockfish --features service` in "
                "third_party/blockfish (requires protoc)"
            )
        session = BlockfishSession(command, handshake_timeout=self.handshake_timeout)
        try:
            self.engine_info = session.handshake()
            config = encode_config_request(
                self.node_limit, max_results=1, max_placements=1
            )
            if config:
                session.send(config)
        except Exception:
            session.close()
            raise
        self.stats.engine_starts += 1
        self._session = session
        return session

    def _request_analysis(self, state: GameState) -> BlockfishAnalysis:
        snapshot = build_snapshot(state, preview_count=self.preview_count)
        self.last_snapshot = snapshot
        self.stats.board_rows_unrepresentable += snapshot.unrepresentable_rows
        session = self._ensure_session()
        started = time.monotonic()
        analysis = session.analyze(snapshot, timeout=self.timeout)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self.stats.analyses += 1
        self.stats.answer_latency_ms += elapsed_ms
        if analysis.suggestions:
            self.stats.suggestions += 1
            suggestion = analysis.suggestions[0]
            self.stats.last_rating = suggestion.rating
            self.stats.last_inputs = list(suggestion.inputs)
            try:
                self.stats.nodes_total += int(analysis.stats.get("nodes", 0) or 0)
            except (TypeError, ValueError):
                pass
        return analysis

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
    "BLOCKFISH_COMMIT",
    "BLOCKFISH_ROWS",
    "BLOCKFISH_WIDTH",
    "BlockfishAgent",
    "BlockfishAnalysis",
    "BlockfishError",
    "BlockfishProcessError",
    "BlockfishSession",
    "BlockfishSnapshot",
    "BlockfishStats",
    "BlockfishSuggestion",
    "BlockfishTimeout",
    "DEFAULT_BINARY",
    "INPUT_NAMES",
    "SimulatedPlacement",
    "action_for_simulated_placement",
    "blockfish_available",
    "blockfish_binary_path",
    "board_to_blockfish_rows",
    "build_snapshot",
    "encode_analyze_request",
    "encode_config_request",
    "guideline_kick_tables",
    "parse_analysis",
    "parse_greeting",
    "simulate_inputs",
]
