"""RIKU0804/tetris-ai opponent adapter over the Tetris Bot Protocol (TBP).

This module wraps the MIT-licensed Rust core of
`RIKU0804/tetris-ai <https://github.com/RIKU0804/tetris-ai>`_ (pinned at
``d3f92d289a24e09ec72679d8ce653bfd8a98679e``) so it can play as a real,
external opponent inside :class:`tetrisrl.environment.versus.VersusMatch`.

The Rust binary (``tetris-core``) is driven over TBP exactly like Cold Clear 2:
one JSON message per line on stdin/stdout, ``start`` → ``suggest`` →
``suggestion``.  The subprocess plumbing, timeouts, lifecycle and
fallback accounting are inherited unchanged from
:class:`tetrisrl.agents.opponents.tbp.TBPAgent`; this module only adds what is
*engine-specific*:

1. the launch command (``tetris-core tbp --weights ... --width ... --depth ...``);
2. the ``start`` queue convention (RIKU always treats ``queue[0]`` as the
   current piece, whereas Cold Clear 2 treats it as the reserve slot when
   ``hold`` is null);
3. a coordinate normalisation for suggested placements (RIKU emits its own
   bounding-box origin, which is *not* the TBP SRS-centre convention that
   ``tbp.tbp_move_cells`` implements; the I and O pieces need a correction);
4. a RIKU-specific error message when the binary is missing.

Compatibility scope (see ``docs/integration_riku.md``)
------------------------------------------------------
* RIKU is a **placement suggester only**.  ``tetrisrl`` owns the match: attack,
  garbage, cancellation, B2B charging, surge, top-out and the action space.
* RIKU implements **guideline SRS**, not TETR.IO **SRS+**, and has **no 180°
  rotation**.  It also has no TETR.IO Season 2 mechanics.  Placements that our
  engine rejects (or that only a tuck/slide could reach) are counted and played
  by the in-repo heuristic fallback; the rate is reported, never hidden.
* TBP has no pending-garbage or opponent-board message, so the engine cannot
  plan around garbage that has not landed yet.
* RIKU emits a single candidate move and **no** ``move_info`` (no node count,
  no search telemetry); the adapter records an empty ``last_move_info``.

No process is started at import time.  Under pytest the inherited guard
refuses to launch the engine unless ``allow_in_tests=True`` is passed.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .tbp import (
    CC_NORTH_CELLS,
    TBP_HEIGHT,
    TBP_WIDTH,
    TBPAgent,
    TBPError,
    TBPTimeout,
    _cc_rotate_cell,
    board_to_tbp_rows,
    parse_suggestion,
)
from ..base import BaseAgent
from ...environment.engine import GameState

#: Upstream commit the adapter was developed and verified against.
RIKU_COMMIT = "d3f92d289a24e09ec72679d8ce653bfd8a98679e"

_REPO_ROOT = Path(__file__).resolve().parents[3]
#: ``cargo build --release`` output of ``third_party/riku-tetris-ai/core-rs``.
DEFAULT_RIKU_BINARY = (
    _REPO_ROOT / "third_party" / "riku-tetris-ai" / "core-rs" / "target" / "release" / "tetris-core"
)
#: Pre-tuned versus weights shipped by the repository (optional; the engine
#: falls back to its built-in attack preset when they are absent).
DEFAULT_RIKU_WEIGHTS = _REPO_ROOT / "third_party" / "riku-tetris-ai" / "weights" / "champion-vs.json"

#: The binary's TBP mode is selected by a subcommand, not by argv flags.
RIKU_TBP_SUBCOMMAND = "tbp"

RIKU_ORIENTATIONS: Tuple[str, ...] = ("north", "east", "south", "west")

#: RIKU's own piece cells (``core-rs/src/engine.rs::SHAPES``), as ``(x, y)``
#: offsets from the top-left corner of the piece's bounding box, ``y``
#: downwards.  These are the SRS rotation states (identical to
#: ``tetrisrl.environment.pieces.CELLS`` up to each piece's box convention:
#: RIKU puts ``O`` in a 3-wide box with cells at box columns 1-2).
RIKU_SHAPES: Dict[str, Tuple[Tuple[Tuple[int, int], ...], ...]] = {
    "I": (
        ((0, 1), (1, 1), (2, 1), (3, 1)),
        ((2, 0), (2, 1), (2, 2), (2, 3)),
        ((0, 2), (1, 2), (2, 2), (3, 2)),
        ((1, 0), (1, 1), (1, 2), (1, 3)),
    ),
    "O": (((1, 0), (2, 0), (1, 1), (2, 1)),) * 4,
    "T": (
        ((1, 0), (0, 1), (1, 1), (2, 1)),
        ((1, 0), (1, 1), (2, 1), (1, 2)),
        ((0, 1), (1, 1), (2, 1), (1, 2)),
        ((1, 0), (0, 1), (1, 1), (1, 2)),
    ),
    "S": (
        ((1, 0), (2, 0), (0, 1), (1, 1)),
        ((1, 0), (1, 1), (2, 1), (2, 2)),
        ((1, 1), (2, 1), (0, 2), (1, 2)),
        ((0, 0), (0, 1), (1, 1), (1, 2)),
    ),
    "Z": (
        ((0, 0), (1, 0), (1, 1), (2, 1)),
        ((2, 0), (1, 1), (2, 1), (1, 2)),
        ((0, 1), (1, 1), (1, 2), (2, 2)),
        ((1, 0), (0, 1), (1, 1), (0, 2)),
    ),
    "J": (
        ((0, 0), (0, 1), (1, 1), (2, 1)),
        ((1, 0), (2, 0), (1, 1), (1, 2)),
        ((0, 1), (1, 1), (2, 1), (2, 2)),
        ((1, 0), (1, 1), (0, 2), (1, 2)),
    ),
    "L": (
        ((2, 0), (0, 1), (1, 1), (2, 1)),
        ((1, 0), (1, 1), (1, 2), (2, 2)),
        ((0, 1), (1, 1), (2, 1), (0, 2)),
        ((0, 0), (1, 0), (1, 1), (1, 2)),
    ),
}


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
def riku_binary_path(binary: Optional[str | os.PathLike[str]] = None) -> Path:
    """Resolve the ``tetris-core`` binary path (argument, env override, default)."""
    if binary is not None:
        return Path(binary).expanduser()
    env = os.environ.get("TETRISRL_RIKU_BIN")
    if env:
        return Path(env).expanduser()
    return DEFAULT_RIKU_BINARY


def riku_available(binary: Optional[str | os.PathLike[str]] = None) -> bool:
    """True when the resolved binary exists and is executable."""
    path = riku_binary_path(binary)
    return path.is_file() and os.access(path, os.X_OK)


def riku_weights_path(weights: Optional[str | os.PathLike[str]] = None) -> Optional[Path]:
    """Resolve the optional weights file (``None`` if it does not exist)."""
    candidate = Path(weights).expanduser() if weights is not None else DEFAULT_RIKU_WEIGHTS
    return candidate if candidate.is_file() else None


# ---------------------------------------------------------------------------
# Wire geometry: RIKU's coordinates -> our board cells
# ---------------------------------------------------------------------------
def riku_move_cells(
    move: Dict[str, Any], board_height: int = TBP_HEIGHT
) -> Tuple[str, Set[Tuple[int, int]]]:
    """Convert a RIKU TBP move into ``(piece, cells)`` in our top-down frame.

    RIKU's ``core-rs/src/tbp.rs`` maps its bounding-box origin ``(ix, iy)`` to
    the wire with ``x = ix + 1`` and ``y = HEIGHT - 2 - iy`` (i.e.
    ``iy = 38 - ty`` for the 40-row board), then adds its own ``SHAPES``
    offsets.  That is *not* the SRS-rotation-centre convention that
    :func:`tetrisrl.agents.opponents.tbp.tbp_move_cells` expects for the I and
    O pieces, so the adapter recomputes the absolute cells from RIKU's own
    convention and only then matches them against legal placements.
    """
    if board_height != TBP_HEIGHT:
        raise TBPError(
            f"RIKU requires a {TBP_HEIGHT}-row board, got {board_height}; "
            "the adapter refuses to silently pad/truncate"
        )
    location = move.get("location", move)
    piece = str(location["type"])
    if piece not in RIKU_SHAPES:
        raise TBPError(f"unknown piece type {piece!r}")
    try:
        rotation = RIKU_ORIENTATIONS.index(str(location.get("orientation", "north")))
    except ValueError as exc:
        raise TBPError(f"unknown orientation {location.get('orientation')!r}") from exc
    box_x = int(location["x"]) - 1
    box_y = (TBP_HEIGHT - 2) - int(location["y"])
    cells: Set[Tuple[int, int]] = set()
    for lx, ly in RIKU_SHAPES[piece][rotation]:
        x, y = box_x + lx, box_y + ly
        if not (0 <= x < TBP_WIDTH and 0 <= y < board_height):
            raise TBPError(f"move cell ({x}, {y}) is outside the board")
        cells.add((x, y))
    if len(cells) != 4:
        raise TBPError(f"move does not contain 4 distinct cells: {move!r}")
    return piece, cells


def _canonical_tbp_centre(
    piece: str, rotation: int, cells: Set[Tuple[int, int]]
) -> Tuple[int, int]:
    """Find the TBP ``(x, y)`` centre that ``tbp_move_cells`` maps to ``cells``."""
    base = {
        (dx, TBP_HEIGHT - 1 - dy)
        for dx, dy in (_cc_rotate_cell(rotation, cell) for cell in CC_NORTH_CELLS[piece])
    }
    anchor_x, anchor_y = next(iter(base))
    for target_x, target_y in cells:
        ox, oy = target_x - anchor_x, target_y - anchor_y
        if {(x + ox, y + oy) for x, y in base} == cells:
            # tbp_move_cells: (x, y) -> (cx + dx, 39 - cy - dy); translating the
            # base set by (ox, oy) means cx = ox and cy = -oy.
            return ox, -oy
    raise TBPError(f"cannot express {piece} {RIKU_ORIENTATIONS[rotation]} cells {sorted(cells)} as a TBP move")


def normalise_riku_move(move: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite a RIKU move into the canonical TBP SRS-centre convention.

    The returned move carries the same piece, orientation, spin and absolute
    cells, but its ``x``/``y`` are expressed the way
    :func:`tetrisrl.agents.opponents.tbp.tbp_move_cells` interprets them, so
    :func:`tetrisrl.agents.opponents.tbp.action_for_tbp_move` (used by the
    inherited :meth:`TBPAgent.choose_action`) can map it to an action id.
    """
    piece, cells = riku_move_cells(move)
    location = move.get("location", move)
    rotation = RIKU_ORIENTATIONS.index(str(location.get("orientation", "north")))
    cx, cy = _canonical_tbp_centre(piece, rotation, cells)
    out = dict(move)
    out["location"] = {
        "type": piece,
        "orientation": RIKU_ORIENTATIONS[rotation],
        "x": cx,
        "y": cy,
    }
    return out


def build_riku_start_message(
    state: GameState,
    *,
    preview_count: Optional[int] = None,
    garbage_rows: Iterable[int] = (),
) -> Dict[str, Any]:
    """Build the TBP ``start`` message with RIKU's queue convention.

    RIKU's beam search always starts at ``queue[0]`` (``core-rs/src/main.rs::
    best_move``), whether or not a hold piece exists.  This differs from Cold
    Clear 2, which uses ``queue[0]`` as the reserve slot when ``hold`` is null;
    :func:`tbp.build_start_message` implements the Cold Clear convention, so
    the adapter sends its own message instead of reusing it.
    """
    if state.current is None:
        raise TBPError("cannot build a start message without a current piece")
    if state.board.height != TBP_HEIGHT:
        raise TBPError(
            f"RIKU requires a {TBP_HEIGHT}-row board, got {state.board.height}"
        )
    n = state.ruleset.board.preview if preview_count is None else int(preview_count)
    previews = state.preview(max(0, n))
    return {
        "type": "start",
        "hold": state.hold,
        "queue": [state.current.name, *previews],
        # Our engine follows TETR.IO's ``-1 = no combo``; RIKU (like TBP) keeps
        # a non-negative consecutive-clear count.
        "combo": max(0, int(state.combo) + 1),
        "back_to_back": bool(state.b2b_active),
        "board": board_to_tbp_rows(state.board, garbage_rows),
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class RikuAgent(TBPAgent):
    """RIKU0804/tetris-ai's Rust beam-search core as a versus opponent.

    Parameters
    ----------
    binary:
        Path to the ``tetris-core`` release binary.  Defaults to
        ``$TETRISRL_RIKU_BIN`` or the build under
        ``third_party/riku-tetris-ai/core-rs/target/release/``.
    weights:
        Optional JSON weights file (``--weights``).  Defaults to the clone's
        ``weights/champion-vs.json`` when present; otherwise the engine's own
        built-in attack preset is used.
    width, depth:
        Beam width and lookahead depth (RIKU's ``tbp`` flags, defaults 16/6).
    think_time:
        Seconds to wait after ``start`` before polling for a suggestion.
        RIKU answers ``suggest`` synchronously, so this is normally ``0``.
    timeout, handshake_timeout:
        As in :class:`TBPAgent`.
    fallback:
        Agent used when the engine is unavailable, times out, errors, or
        suggests a placement our hard-drop action space cannot express.
        Defaults to the in-repo :class:`~tetrisrl.agents.heuristic_agent.HeuristicAgent`.
    command:
        Full command override (tests / alternate builds).  When given, no
        ``tbp``/``--weights`` flags are appended.
    allow_in_tests:
        Required to launch the engine under pytest (inherited guard).
    """

    name = "riku"

    def __init__(
        self,
        binary: Optional[str | os.PathLike[str]] = None,
        *,
        weights: Optional[str | os.PathLike[str]] = None,
        width: int = 16,
        depth: int = 6,
        think_time: float = 0.0,
        timeout: float = 5.0,
        handshake_timeout: float = 10.0,
        fallback: Optional[BaseAgent] = None,
        command: Optional[Sequence[str]] = None,
        allow_in_tests: bool = False,
        name: Optional[str] = None,
    ) -> None:
        self.width = max(1, int(width))
        self.depth = max(1, int(depth))
        super().__init__(
            binary=riku_binary_path(binary),
            think_time=think_time,
            timeout=timeout,
            handshake_timeout=handshake_timeout,
            fallback=fallback,
            command=command,
            allow_in_tests=allow_in_tests,
            name=name or type(self).name,
        )
        self.weights = riku_weights_path(weights)

    # -- launch -----------------------------------------------------------
    def _launch_command(self) -> List[str]:
        if self.command is not None:
            return list(self.command)
        command = [
            str(self.binary),
            RIKU_TBP_SUBCOMMAND,
            "--width",
            str(self.width),
            "--depth",
            str(self.depth),
        ]
        if self.weights is not None:
            command += ["--weights", str(self.weights)]
        return command

    def _ensure_session(self):  # noqa: ANN201 - TBPSession
        if self.command is None and not riku_available(self.binary):
            raise TBPError(
                f"RIKU tetris-core binary not found/executable at {self.binary}; "
                "build it with `cargo build --release` in "
                "third_party/riku-tetris-ai/core-rs (or set TETRISRL_RIKU_BIN)"
            )
        return super()._ensure_session()

    # -- transport --------------------------------------------------------
    def _request_suggestion(self, state: GameState) -> List[Dict[str, Any]]:
        """Send ``start``/``suggest`` and return normalised TBP moves.

        Same retry/timeout/counter logic as :meth:`TBPAgent._request_suggestion`
        (which cannot be reused because it builds Cold Clear 2's queue
        convention and returns moves unnormalised).
        """
        session = self._ensure_session()
        session.drain()  # drop any late reply from a previous timeout
        session.send(build_riku_start_message(state))
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
                normalised = [normalise_riku_move(move) for move in moves]
                self.stats.suggestions += 1
                self.stats.answer_latency_ms += (time.monotonic() - started) * 1000.0
                self.stats.last_move_info = info
                return normalised
            # RIKU answers synchronously; an empty list means it found no
            # placement (e.g. an empty queue).  Ask again shortly.
            time.sleep(0.001)
        raise TBPTimeout(f"engine produced no suggestion within {self.timeout:.3f}s")


__all__ = [
    "DEFAULT_RIKU_BINARY",
    "DEFAULT_RIKU_WEIGHTS",
    "RIKU_COMMIT",
    "RIKU_ORIENTATIONS",
    "RIKU_SHAPES",
    "RikuAgent",
    "build_riku_start_message",
    "normalise_riku_move",
    "riku_available",
    "riku_binary_path",
    "riku_move_cells",
    "riku_weights_path",
]
