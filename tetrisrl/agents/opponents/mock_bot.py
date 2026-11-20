"""Deterministic *mock* TBP bot used to test the adapter plumbing.

This is **not** a Tetris engine and **not** a benchmark opponent.  It speaks a
small, simplified subset of the Tetris Bot Protocol (``info``, ``rules``,
``ready``, ``start``, ``suggest``, ``suggestion``, ``quit``) so that
:class:`tetrisrl.agents.opponents.tbp.TBPAgent` can be exercised without the
external Cold Clear 2 binary:

    python -m tetrisrl.agents.opponents.mock_bot --mode drop

Modes
-----
``drop`` (default)
    Places the current piece at rotation 0 (north) in the first column where it
    fits, hard-dropped on the board received in ``start``.  The current piece is
    read using Cold Clear 2's queue convention (``queue[1]`` when ``hold`` is
    null, else ``queue[0]``).
``invalid``
    Returns a deliberately out-of-bounds placement so tests can verify the
    adapter's validation + heuristic fallback path.
``file``
    Replays the placements in ``--moves-file`` (a JSON list of TBP ``move``
    objects), cycling through them.  Use this for exact, scripted assertions.

The bot optionally writes every received ``start`` message to ``--telemetry``
as JSON lines, which is how tests verify board/queue/hold encoding.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# Reuse the engine's piece geometry constants only; no engine/process code.
from .tbp import CC_NORTH_CELLS, TBP_HEIGHT, TBP_WIDTH

MOCK_NAME = "Mock TBP Bot (test double, not a benchmark)"


class SBPMockBot:
    """Deterministic mock TBP bot: a test double, **not** a benchmark opponent.

    The name follows the project brief; the wire format it speaks is a small
    subset of TBP (not SBP), because that is what the Cold Clear 2 adapter uses.
    """

    def __init__(
        self,
        *,
        mode: str = "drop",
        moves: Optional[Sequence[Dict[str, Any]]] = None,
        telemetry: Optional[str] = None,
        delay_ms: float = 0.0,
        empty_first: bool = False,
        column: Optional[int] = None,
        crash_after: Optional[int] = None,
        out=None,
    ) -> None:
        self.mode = mode
        self.moves = list(moves or [])
        self.telemetry = Path(telemetry) if telemetry else None
        self.delay_ms = float(delay_ms)
        self.empty_first = bool(empty_first)
        self.column = column
        self.crash_after = crash_after
        self.out = out if out is not None else sys.stdout
        self.starts = 0
        self.suggests = 0
        self._empty_next = False
        self._last_start: Optional[Dict[str, Any]] = None
        self._stopped = False

    # -- io -------------------------------------------------------------
    def send(self, message: Dict[str, Any]) -> None:
        self.out.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.out.flush()

    def log(self, text: str) -> None:
        print(f"[mock-tbp] {text}", file=sys.stderr, flush=True)

    def record(self, message: Dict[str, Any]) -> None:
        if self.telemetry is None:
            return
        with self.telemetry.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message, separators=(",", ":")) + "\n")

    # -- protocol -------------------------------------------------------
    def handle(self, message: Dict[str, Any]) -> bool:
        kind = message.get("type")
        if kind == "rules":
            self.send({"type": "ready"})
        elif kind == "start":
            self.starts += 1
            self._last_start = message
            self._empty_next = False
            self.record({"event": "start", "index": self.starts, "message": message})
            if self.crash_after is not None and self.starts > self.crash_after:
                self.log(f"crashing after {self.crash_after} starts (test double)")
                return False
        elif kind == "stop":
            self._last_start = None
        elif kind == "suggest":
            self.suggests += 1
            if self.delay_ms:
                time.sleep(self.delay_ms / 1000.0)
            if self.empty_first and not self._empty_next:
                # Mimic Cold Clear 2 answering before it has expanded the root.
                self._empty_next = True
                moves: List[Dict[str, Any]] = []
            else:
                self._empty_next = False
                moves = self._suggestions()
            self.send(
                {
                    "type": "suggestion",
                    "moves": moves,
                    "move_info": {"nodes": 0, "nps": 0.0, "extra": "mock"},
                }
            )
        elif kind == "new_piece":
            pass
        elif kind == "play":
            pass
        elif kind == "quit":
            return False
        elif kind == "error":
            pass
        return True

    def run(self) -> int:
        self.send(
            {
                "type": "info",
                "name": MOCK_NAME,
                "version": "0.1-mock",
                "author": "tetrisrl test suite",
                "features": ["mock"],
            }
        )
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self.log(f"ignoring invalid JSON: {line[:200]}")
                continue
            if not isinstance(message, dict):
                continue
            if not self.handle(message):
                break
        return 0

    # -- suggestion generation -----------------------------------------
    def _current_piece(self) -> Optional[str]:
        start = self._last_start or {}
        queue = start.get("queue") or []
        hold = start.get("hold")
        if hold is not None:
            return str(queue[0]) if queue else None
        if len(queue) >= 2:
            return str(queue[1])
        return str(queue[0]) if queue else None

    def _suggestions(self) -> List[Dict[str, Any]]:
        if self.mode == "file":
            if not self.moves:
                return []
            index = (self.suggests - 1) % len(self.moves)
            return [self.moves[index]]
        if self.mode == "invalid":
            piece = self._current_piece() or "T"
            return [
                {
                    "location": {"type": piece, "orientation": "north", "x": -9, "y": 0},
                    "spin": "none",
                }
            ]
        piece = self._current_piece()
        if piece is None:
            return []
        board = (self._last_start or {}).get("board") or []
        return self._north_drop_moves(piece, board)

    def _north_drop_moves(self, piece: str, board: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
        cells = CC_NORTH_CELLS.get(piece)
        if not cells or len(board) != TBP_HEIGHT:
            return []
        min_dx = min(dx for dx, _ in cells)
        occupied = [
            [value is not None for value in (row + [None] * TBP_WIDTH)[:TBP_WIDTH]]
            for row in board
        ]

        def fits(x: int, y: int) -> bool:
            for dx, dy in cells:
                cx, cy = x + dx, y + dy
                if not (0 <= cx < TBP_WIDTH and 0 <= cy < TBP_HEIGHT):
                    return False
                if occupied[cy][cx]:
                    return False
            return True

        columns = [self.column] if self.column is not None else list(range(TBP_WIDTH))
        moves: List[Dict[str, Any]] = []
        for column in columns:
            if not 0 <= column < TBP_WIDTH:
                continue
            origin_x = column - min_dx
            placed = None
            # y=0 is the floor: a hard drop rests at the lowest reachable row.
            for y in range(TBP_HEIGHT):
                if fits(origin_x, y):
                    placed = y
                    break
            if placed is None:
                continue
            moves.append(
                {
                    "location": {
                        "type": piece,
                        "orientation": "north",
                        "x": origin_x,
                        "y": placed,
                    },
                    "spin": "none",
                }
            )
            if len(moves) >= 3:
                break
        return moves


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["drop", "invalid", "file"], default="drop")
    parser.add_argument("--moves-file", help="JSON list of TBP move objects (mode=file)")
    parser.add_argument("--telemetry", help="append received start messages as JSON lines")
    parser.add_argument("--delay-ms", type=float, default=0.0)
    parser.add_argument("--empty-first", action="store_true", help="answer the first suggest after each start with no moves")
    parser.add_argument("--column", type=int, default=None, help="force the hard-drop column")
    parser.add_argument("--crash-after", type=int, default=None, help="exit after N start messages")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    moves: List[Dict[str, Any]] = []
    if args.mode == "file":
        if not args.moves_file:
            print("--mode file requires --moves-file", file=sys.stderr)
            return 2
        moves = json.loads(Path(args.moves_file).read_text(encoding="utf-8"))
        if not isinstance(moves, list):
            print("--moves-file must contain a JSON list", file=sys.stderr)
            return 2
    bot = SBPMockBot(
        mode=args.mode,
        moves=moves,
        telemetry=args.telemetry,
        delay_ms=args.delay_ms,
        empty_first=args.empty_first,
        column=args.column,
        crash_after=args.crash_after,
    )
    return bot.run()


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())


#: Alias kept for callers that prefer the shorter name.
MockBot = SBPMockBot
