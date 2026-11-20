"""External opponent adapters.

* :mod:`tetrisrl.agents.opponents.tbp` — Cold Clear 2 over the Tetris Bot
  Protocol (a real external engine, built from ``third_party/cold-clear-2``).
* :mod:`tetrisrl.agents.opponents.mock_bot` — a deterministic mock TBP bot used
  only to test adapter plumbing; **not** a benchmark opponent.

No subprocess is started at import time.  See ``docs/BENCHMARKS_INTEGRATION.md``
for the pinned commit, build commands, protocol details, and the measured
results of any actual matches.
"""

from __future__ import annotations

from .mock_bot import SBPMockBot
from .tbp import (
    DEFAULT_BINARY,
    TBPAgent,
    TBPError,
    TBPProcessError,
    TBPSession,
    TBPStats,
    TBPTimeout,
    action_for_tbp_move,
    board_to_tbp_rows,
    build_start_message,
    coldclear_available,
    coldclear_binary_path,
    parse_suggestion,
    tbp_move_cells,
)

__all__ = [
    "DEFAULT_BINARY",
    "SBPMockBot",
    "TBPAgent",
    "TBPError",
    "TBPProcessError",
    "TBPSession",
    "TBPStats",
    "TBPTimeout",
    "action_for_tbp_move",
    "board_to_tbp_rows",
    "build_start_message",
    "coldclear_available",
    "coldclear_binary_path",
    "parse_suggestion",
    "tbp_move_cells",
]
