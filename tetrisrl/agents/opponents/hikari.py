"""SoRA-X7/hikari_rei opponent adapter over the Tetris Bot Protocol (TBP).

This module wraps the MIT-licensed Rust reimplementation of **Hikari**
(``SoRA-X7/hikari_rei``, pinned at
``21b63c652f232d64016b2af72876d7a4b0e238fd``) so it can play as a real,
external opponent inside :class:`tetrisrl.environment.versus.VersusMatch`.

The binary is driven over TBP exactly like Cold Clear 2: one JSON message per
line on stdin/stdout, ``start`` → ``suggest`` → ``suggestion``.  Subprocess
plumbing, timeouts, lifecycle, the pytest launch guard and the fallback
counter are inherited unchanged from
:class:`tetrisrl.agents.opponents.tbp.TBPAgent`.  This module only adds what is
*engine-specific*:

1. the launch command (``hikari_rei tbp --threads 1``);
2. the per-engine TBP conventions, verified against the built binary
   (see ``docs/integration_hikari.md``):

   * ``queue[0]`` is the **current** piece (``current_first``);
   * ``back_to_back`` must be a JSON **boolean** (an integer is rejected with
     ``back_to_back must be a boolean``);
   * Hikari's board is **24 rows**, bottom-first.  It accepts up to 40 wire
     rows, but rejects any occupied row at index >= 24 with
     ``Hikari supports occupied rows 0 through 23``.  The adapter therefore
     sends our **bottom 24 rows** (our rows 39..16), which keeps a tall stack
     playable instead of erroring the whole position;
   * the wire ``combo`` field is written straight into Hikari's ``ren``, i.e.
     it is the number of consecutive clears already performed.  TETR.IO's
     ``combo`` counts from ``-1`` (no combo), so the adapter sends
     ``max(0, combo + 1)`` (``combo_offset = 1``).  Verified by reading the
     echoed ``suggestion.board.ren`` for ``combo = -1, 0, 5``;
   * suggested placements use the standard TBP true-rotation-centre
     convention (verified for all seven pieces against
     :func:`tbp.action_for_tbp_move`), so the inherited geometry matcher works
     without normalisation.

Compatibility scope (see ``docs/integration_hikari.md``)
-------------------------------------------------------
* Hikari is a **placement suggester only**.  ``tetrisrl`` owns the match:
  attack, garbage, cancellation, B2B charging, surge, top-out and the action
  space.
* Hikari implements **SRS**, not TETR.IO **SRS+**, and has **no 180° rotation**
  and no TETR.IO Season 2 mechanics.  Placements our engine rejects (or that
  only a tuck/slide could reach) are counted and played by the in-repo
  heuristic fallback; the rate is reported, never hidden.
* TBP has no pending-garbage or opponent-board message, so the engine cannot
  plan around garbage that has not landed yet.  The 24-row board also means a
  stack above our row 16 is invisible to it (documented handicap).
* Hikari's own versus rules (its 24-row arena, 60-frame garbage, its attack
  table) are **not** used; the engine only suggests placements.

No process is started at import time.  Under pytest the inherited guard
refuses to launch the engine unless ``allow_in_tests=True`` is passed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .tbp import TBPAgent, TBPError, TBPProfile, build_start_message
from ..base import BaseAgent
from ...environment.engine import GameState

#: Upstream commit the adapter was developed and verified against.
HIKARI_COMMIT = "21b63c652f232d64016b2af72876d7a4b0e238fd"

_REPO_ROOT = Path(__file__).resolve().parents[3]
#: ``cargo build --release`` output of ``third_party/hikari_rei``.
DEFAULT_HIKARI_BINARY = (
    _REPO_ROOT / "third_party" / "hikari_rei" / "target" / "release" / "hikari_rei"
)

#: Hikari's native board height (``src/board.rs``: ``HEIGHT = 24``).  Wire rows
#: are bottom-first, so this is the number of rows we send.
HIKARI_BOARD_ROWS = 24

#: TBP dialect of the pinned commit, verified against the live binary.
HIKARI_PROFILE = TBPProfile(
    name="hikari",
    queue_mode="current_first",  # queue[0] is the current piece
    b2b_type="bool",  # back_to_back must be a JSON boolean
    combo_offset=1,  # wire combo = TETR.IO combo + 1 (Hikari's `ren`)
    board_rows=HIKARI_BOARD_ROWS,  # send our bottom 24 rows
    tbp_version=1,
    requires_opponents=False,
)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
def hikari_binary_path(binary: Optional[str | os.PathLike[str]] = None) -> Path:
    """Resolve the ``hikari_rei`` binary path (argument, env override, default)."""
    if binary is not None:
        return Path(binary).expanduser()
    env = os.environ.get("TETRISRL_HIKARI_BIN")
    if env:
        return Path(env).expanduser()
    return DEFAULT_HIKARI_BINARY


def hikari_available(binary: Optional[str | os.PathLike[str]] = None) -> bool:
    """True when the resolved binary exists and is executable."""
    path = hikari_binary_path(binary)
    return path.is_file() and os.access(path, os.X_OK)


def build_hikari_start_message(
    state: GameState,
    *,
    preview_count: Optional[int] = None,
    garbage_rows: Sequence[int] = (),
    opponent_state: Optional[GameState] = None,
) -> Dict[str, Any]:
    """Build the TBP ``start`` message with the verified Hikari conventions.

    Delegates to :func:`tetrisrl.agents.opponents.tbp.build_start_message` with
    :data:`HIKARI_PROFILE`: ``queue[0]`` is the current piece, B2B is a boolean,
    the board is our bottom 24 rows (bottom-first) and the combo is shifted by
    one to match Hikari's ``ren``.  No ``randomizer``/``bag`` state is sent, so
    hidden bag information is never leaked to the opponent.
    """
    return build_start_message(
        state,
        preview_count=preview_count,
        garbage_rows=garbage_rows,
        profile=HIKARI_PROFILE,
        opponent_state=opponent_state,
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class HikariAgent(TBPAgent):
    """SoRA-X7/hikari_rei's Rust TBP engine as a versus opponent.

    Parameters
    ----------
    binary:
        Path to the ``hikari_rei`` release binary.  Defaults to
        ``$TETRISRL_HIKARI_BIN`` or the build under
        ``third_party/hikari_rei/target/release/``.
    threads:
        Search workers passed as ``--threads`` (the task pins ``1`` for
        reproducible, CPU-bounded matches).
    think_time:
        Seconds to let the engine ponder between ``start`` and ``suggest``.
        Hikari keeps searching between protocol messages, so this is the
        per-move budget (default 20 ms, matching its own versus harness).
    timeout, handshake_timeout:
        As in :class:`TBPAgent`.
    fallback:
        Agent used when the engine is unavailable, times out, errors, or
        suggests a placement our hard-drop action space cannot express.
        Defaults to the in-repo :class:`~tetrisrl.agents.heuristic_agent.HeuristicAgent`.
    command:
        Full command override (tests / alternate builds).  When given, no
        ``tbp``/``--threads`` flags are appended.
    max_nodes:
        Optional ``--max-nodes`` cap (Hikari's TBP default is 3,500,000).
    no_hold:
        Pass ``--no-hold`` (diagnostics; the default lets the engine use hold).
    profile:
        TBP conventions override; defaults to :data:`HIKARI_PROFILE`.
    allow_in_tests:
        Required to launch the engine under pytest (inherited guard).
    """

    name = "hikari"

    def __init__(
        self,
        binary: Optional[str | os.PathLike[str]] = None,
        *,
        threads: int = 1,
        think_time: float = 0.02,
        timeout: float = 5.0,
        handshake_timeout: float = 10.0,
        fallback: Optional[BaseAgent] = None,
        command: Optional[Sequence[str]] = None,
        max_nodes: Optional[int] = None,
        no_hold: bool = False,
        profile: Optional[TBPProfile] = None,
        allow_in_tests: bool = False,
        name: Optional[str] = None,
    ) -> None:
        self.threads = max(1, int(threads))
        self.max_nodes = int(max_nodes) if max_nodes is not None else None
        self.no_hold = bool(no_hold)
        super().__init__(
            binary=hikari_binary_path(binary),
            think_time=think_time,
            timeout=timeout,
            handshake_timeout=handshake_timeout,
            fallback=fallback,
            command=command,
            allow_in_tests=allow_in_tests,
            name=name or type(self).name,
            profile=profile or HIKARI_PROFILE,
        )

    # -- launch -----------------------------------------------------------
    def _launch_command(self) -> List[str]:
        if self.command is not None:
            return list(self.command)
        command = [str(self.binary), "tbp", "--threads", str(self.threads)]
        if self.max_nodes is not None:
            command += ["--max-nodes", str(self.max_nodes)]
        if self.no_hold:
            command += ["--no-hold"]
        return command

    def _ensure_session(self):  # noqa: ANN201 - TBPSession
        if self.command is None and not hikari_available(self.binary):
            raise TBPError(
                f"Hikari hikari_rei binary not found/executable at {self.binary}; "
                "build it with `cargo build --release` in third_party/hikari_rei "
                "(or set TETRISRL_HIKARI_BIN)"
            )
        return super()._ensure_session()

    # -- transport --------------------------------------------------------
    def _request_suggestion(self, state: GameState) -> List[Dict[str, Any]]:
        """Inherit the start/suggest loop and record Hikari's search telemetry.

        Hikari publishes ``move_info.search`` (graph node/edge counts) with each
        suggestion.  The inherited loop only understands Cold Clear 2's flat
        ``nodes`` field, so this override adds the nested count to
        ``stats.nodes_total``.  ``nodes`` is the retained graph size for the
        current position, not the number of nodes expanded for this move.
        """
        moves = super()._request_suggestion(state)
        search_stats = self.stats.last_move_info.get("search")
        if isinstance(search_stats, dict):
            try:
                self.stats.nodes_total += int(search_stats.get("nodes", 0) or 0)
            except (TypeError, ValueError):
                pass
        return moves


__all__ = [
    "DEFAULT_HIKARI_BINARY",
    "HIKARI_BOARD_ROWS",
    "HIKARI_COMMIT",
    "HIKARI_PROFILE",
    "HikariAgent",
    "build_hikari_start_message",
    "hikari_available",
    "hikari_binary_path",
]
