"""nightcrab/nana opponent adapter over TBP2.

`nana <https://github.com/nightcrab/nana>`_ is a parallel MCTS/TDS engine for
versus Tetris with an explicit opponent model.  It is driven over the
**TBP2** extension of the Tetris Bot Protocol (JSON lines, one object per
line, stdin/stdout), pinned here at commit
``3cb49c6cc680f07282382de2862f1aa656d9afa1``.

The subprocess plumbing, timeouts, counters and heuristic fallback are
inherited unchanged from :class:`tetrisrl.agents.opponents.tbp.TBPAgent`.
This module adds only what is engine-specific:

1. the launch command (``build/cpp/nana_tbp``, no argv arguments);
2. the TBP2 ``start`` message: ``queue[0]`` is the **current** piece and
   ``opponents[0]`` is **mandatory**;
3. a config helper for ``nana.json``, which nana reads **beside the
   executable** (there is no command-line config flag in TBP mode);
4. a nana-specific missing-binary error and defaults tuned for its MCTS
   (``think_time=0.15`` s, ``timeout=10`` s).

Source-verified protocol quirks (``cpp/tbp.cpp`` at the pinned commit)
-----------------------------------------------------------------------
* **``opponents[0]`` is mandatory in every ``start``.**  The code does
  ``CHECK_ERR(player_2 = message["opponents"][0])``.  A start without it makes
  the process die (observed: SIGSEGV after ``ready``), so this adapter always
  sends an opponent object, synthesising an empty board when the caller has
  no opponent state.
* **``queue[0]`` is the current piece.**  ``game.game.current_piece =
  queue.front(); queue.erase(queue.begin())``.  The next queue entry is the
  hold-swap candidate, so a suggestion may legitimately be for the next piece
  (the engine intends a hold); :func:`tbp.action_for_tbp_move` already handles
  that by matching the piece/hold geometry.
* **``combo`` and ``back_to_back`` are required.**  ``combo`` is an integer
  consecutive-clear count; ``back_to_back`` may be a JSON boolean or integer.
  This adapter sends the integer ``b2b_count`` (TBP2's native type).
* **``meter`` is read from the opponent object, not from player 1.**
  ``readOpponent()`` stores ``player_2["meter"]`` in ``SeenOpponent::meter``,
  which feeds ``Eval::opponentDirection`` (the ``METER`` opponent feature) and
  the HMM opponent model.  The top-level ``meter`` field emitted by
  :func:`tbp.build_start_message` is ignored by nana.  This adapter therefore
  also puts ``opponent_state.garbage.total()`` into ``opponents[0]["meter"]``
  — that is the pending-garbage signal nana actually consumes.
* **Whitespace matters.**  nana reads each message with ``std::cin >>``, so a
  pretty-printed JSON object is truncated at the first space.  ``TBPSession``
  already writes compact JSON (``separators=(",", ":")``); do not switch it to
  indented output.
* **Board is 32 rows internally.**  ``ShakTrisLib`` uses
  ``Board::height = 32`` and ``json_to_board`` reads only rows 0..31 of the
  40-row wire board (row 0 = bottom).  Our adapter sends the standard
  bottom-first 40-row board; a stack in the top 8 hidden rows is invisible to
  nana (documented limitation; mismatches become counted fallbacks).
* **No search telemetry.**  ``suggestion`` contains ``moves`` but no
  ``move_info`` (``inputs`` is empty in this version), so ``nodes_total``
  stays 0 and only wall-clock latency is measurable.

Compatibility scope (see ``docs/integration_nana.md``)
-------------------------------------------------------
* nana is a **placement suggester only**; ``tetrisrl`` owns attack, garbage,
  cancellation, B2B charging, surge, spin classification and top-out.
* ``nana.json`` selects nana's own ``tetrio`` rules, which the source maps to
  **TETR.IO Season 1** damage (``modes/TetrioS1.hpp``), not Season 2.
* SRS wall kicks only (**no 180°**, no SRS+ I-kick order), so placements that
  require our arena's SRS+ or 180° path are unreachable for nana.
* Because ``start`` is sent once per piece (no ``play``), nana rebuilds its
  emulation game each piece and continues its search tree.  This is the safe
  choice when the adapter may fall back to the heuristic.

No process is started at import time.  Under pytest the inherited guard
refuses to launch the engine unless ``allow_in_tests=True`` is passed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .tbp import (
    TBP_WIDTH,
    TBPAgent,
    TBPError,
    TBPProfile,
    TBPTimeout,
    build_start_message,
    parse_suggestion,
)
from ..base import BaseAgent
from ...environment.engine import GameState

#: Upstream commit this adapter was developed and verified against.
NANA_COMMIT = "3cb49c6cc680f07282382de2862f1aa656d9afa1"

_REPO_ROOT = Path(__file__).resolve().parents[3]
#: ``cmake --build build`` output of ``third_party/nana``.
DEFAULT_NANA_BINARY = _REPO_ROOT / "third_party" / "nana" / "build" / "cpp" / "nana_tbp"

#: nana expects a file literally named ``nana.json`` next to the executable.
NANA_CONFIG_FILENAME = "nana.json"
DEFAULT_NANA_THREADS = 2
DEFAULT_NANA_RULES = "tetrio"

#: Default timing for nana's MCTS.  150 ms of search per placement is roughly
#: the 50 ms time control the upstream README reports for its Cold Clear
#: series, scaled for a 1-2 thread local run; the 10 s suggestion deadline is
#: deliberately generous because MCTS can overshoot under load.
DEFAULT_THINK_TIME = 0.15
DEFAULT_TIMEOUT = 10.0

#: Per-engine TBP conventions for nana (all verified in ``cpp/tbp.cpp``).
NANA_PROFILE = TBPProfile(
    name="nana",
    queue_mode="current_first",  # queue[0] == current piece
    b2b_type="int",              # TBP2 native type; bool is also accepted
    combo_offset=1,              # TETR.IO -1 = no combo -> TBP 0
    board_rows=40,               # standard wire board; nana reads bottom 32
    tbp_version=2,               # emits ``meter`` and ``opponents``
    requires_opponents=True,     # every start MUST carry opponents[0]
)


# ---------------------------------------------------------------------------
# Availability / config
# ---------------------------------------------------------------------------
def nana_binary_path(binary: Optional[str | os.PathLike[str]] = None) -> Path:
    """Resolve the ``nana_tbp`` path (argument, env override, default)."""
    if binary is not None:
        return Path(binary).expanduser()
    env = os.environ.get("TETRISRL_NANA_BIN")
    if env:
        return Path(env).expanduser()
    return DEFAULT_NANA_BINARY


def nana_available(binary: Optional[str | os.PathLike[str]] = None) -> bool:
    """True when the resolved ``nana_tbp`` binary exists and is executable."""
    path = nana_binary_path(binary)
    return path.is_file() and os.access(path, os.X_OK)


def nana_config_path(
    binary: Optional[str | os.PathLike[str]] = None,
    config: Optional[str | os.PathLike[str]] = None,
) -> Path:
    """Resolve the ``nana.json`` path.

    nana's TBP mode unconditionally reads ``nana.json`` **beside the
    executable** (``Config.cpp::load()``: ``executableDirectory() /
    "nana.json"``); ``NANA_CONFIG`` and argv are ignored in that mode.  The
    resolved path is therefore informational unless it really is next to the
    binary.  ``$TETRISRL_NANA_CONFIG`` is accepted as an explicit override for
    callers that keep a template elsewhere and copy it into place.
    """
    if config is not None:
        return Path(config).expanduser()
    env = os.environ.get("TETRISRL_NANA_CONFIG")
    if env:
        return Path(env).expanduser()
    return nana_binary_path(binary).parent / NANA_CONFIG_FILENAME


def nana_config() -> Dict[str, Any]:
    """The minimal config nana needs: TETR.IO rules and 1-2 search threads."""
    return {"rules": DEFAULT_NANA_RULES, "threads": DEFAULT_NANA_THREADS}


def ensure_nana_config(
    path: Optional[str | os.PathLike[str]] = None,
    *,
    threads: int = DEFAULT_NANA_THREADS,
    rules: str = DEFAULT_NANA_RULES,
    overwrite: bool = False,
) -> Path:
    """Create the minimal ``nana.json`` if it is missing; return its path.

    nana rejects unknown keys (``unknown keys: ...``), so only ``rules`` and
    ``threads`` are written.  This is a build-time/config helper, not a
    protocol action: it never launches the engine and can be called safely
    from scripts (but not at import time).
    """
    threads = int(threads)
    if threads < 1:
        raise ValueError("nana threads must be >= 1")
    if rules not in ("tetrio", "botris"):
        raise ValueError("nana rules must be 'tetrio' or 'botris'")
    target = Path(path).expanduser() if path is not None else nana_config_path()
    if target.exists() and not overwrite:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"rules": rules, "threads": threads}, indent=2) + "\n")
    return target


# ---------------------------------------------------------------------------
# TBP2 start message
# ---------------------------------------------------------------------------
def _empty_tbp_board(board_rows: int = 40) -> List[List[Optional[str]]]:
    """An all-empty TBP board (wire order: bottom row first)."""
    return [[None] * TBP_WIDTH for _ in range(int(board_rows))]


def build_nana_start_message(
    state: GameState,
    opponent_state: Optional[GameState] = None,
    *,
    preview_count: Optional[int] = None,
    garbage_rows: Iterable[int] = (),
    profile: TBPProfile = NANA_PROFILE,
) -> Dict[str, Any]:
    """Build a TBP2 ``start`` message that nana accepts.

    Differences from :func:`tbp.build_start_message`:

    * ``opponents[0]`` is **always** present.  When ``opponent_state`` is
      ``None`` an all-empty opponent board is synthesised, because nana
      dereferences ``message["opponents"][0]`` unconditionally and dies
      without it.
    * ``opponents[0]["meter"]`` is set from the opponent's pending garbage.
      nana reads pending garbage only from the opponent object
      (``readOpponent``), not from the top-level ``meter`` field.
    """
    if profile.tbp_version < 2 or not profile.requires_opponents:
        raise TBPError("nana requires the TBP2 profile (tbp_version=2, requires_opponents=True)")
    message = build_start_message(
        state,
        preview_count=preview_count,
        garbage_rows=garbage_rows,
        profile=profile,
        opponent_state=opponent_state,
    )
    # The base builder already emits ``meter`` for player 1 (kept for spec
    # completeness); nana itself only consumes the opponent's meter.
    message["meter"] = int(state.garbage.total())
    opponents = message.get("opponents")
    if not opponents:
        opponents = [
            {
                "board": _empty_tbp_board(profile.board_rows),
                "combo": 0,
                "back_to_back": 0,
                "queue": [],
                "hold": None,
                "meter": 0,
            }
        ]
        message["opponents"] = opponents
    opponent = opponents[0]
    if opponent_state is not None:
        opponent["meter"] = int(opponent_state.garbage.total())
    else:
        opponent.setdefault("meter", 0)
    return message


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class NanaAgent(TBPAgent):
    """nightcrab/nana's parallel MCTS engine as a versus opponent.

    Parameters
    ----------
    binary:
        Path to ``nana_tbp``.  Defaults to ``$TETRISRL_NANA_BIN`` or
        ``third_party/nana/build/cpp/nana_tbp``.
    config_path:
        Path used to locate/verify ``nana.json``.  nana only reads
        ``nana.json`` beside the executable, so the default is derived from
        the binary.  If the file is missing the agent writes the minimal
        config (rules ``tetrio``, 2 threads) before starting the process.
    think_time:
        Seconds to wait after ``start`` before asking for a suggestion
        (default 0.15).  nana answers ``suggest`` immediately after stopping
        its search, so this is the search budget.
    timeout:
        Deadline for a suggestion (default 10 s).  MCTS can overshoot under
        load; a timeout closes the process, counts a timeout, and the move is
        played by the fallback.
    fallback:
        Agent used when nana is unavailable, times out, errors, or suggests a
        placement our hard-drop action space cannot express.  Defaults to the
        in-repo :class:`~tetrisrl.agents.heuristic_agent.HeuristicAgent`.
    command:
        Full command override (tests / alternate builds).  nana takes no argv
        arguments, so normally this is just ``[binary]``.
    allow_in_tests:
        Required to launch the engine under pytest (inherited guard).
    profile:
        Override the TBP2 profile (defaults to :data:`NANA_PROFILE`).
    """

    name = "nana"

    def __init__(
        self,
        binary: Optional[str | os.PathLike[str]] = None,
        *,
        config_path: Optional[str | os.PathLike[str]] = None,
        think_time: float = DEFAULT_THINK_TIME,
        timeout: float = DEFAULT_TIMEOUT,
        handshake_timeout: float = 10.0,
        fallback: Optional[BaseAgent] = None,
        command: Optional[Sequence[str]] = None,
        allow_in_tests: bool = False,
        name: Optional[str] = None,
        profile: Optional[TBPProfile] = None,
    ) -> None:
        resolved_binary = nana_binary_path(binary)
        super().__init__(
            binary=resolved_binary,
            think_time=think_time,
            timeout=timeout,
            handshake_timeout=handshake_timeout,
            fallback=fallback,
            command=command,
            allow_in_tests=allow_in_tests,
            name=name or type(self).name,
            profile=profile or NANA_PROFILE,
        )
        self.config_path = (
            Path(config_path).expanduser()
            if config_path is not None
            else nana_config_path(resolved_binary)
        )

    # -- launch -----------------------------------------------------------
    def _ensure_session(self):  # noqa: ANN201 - TBPSession
        if self.command is None:
            if not nana_available(self.binary):
                raise TBPError(
                    f"nana binary not found/executable at {self.binary}; build it with "
                    "`cmake -S third_party/nana -B third_party/nana/build "
                    "-DCMAKE_BUILD_TYPE=Release && cmake --build third_party/nana/build -j` "
                    "(or set TETRISRL_NANA_BIN)"
                )
            # nana reads nana.json beside the executable, so materialise the
            # minimal config if the build tree does not have it yet.
            if not self.config_path.is_file():
                ensure_nana_config(self.config_path)
        return super()._ensure_session()

    # -- transport --------------------------------------------------------
    def _request_suggestion(self, state: GameState) -> List[Dict[str, Any]]:
        """Send ``start``/``suggest`` and return nana's moves.

        Mirrors :meth:`TBPAgent._request_suggestion` (which cannot be reused
        because it builds the TBP1/CC queue convention) and uses the TBP2
        start builder above.
        """
        session = self._ensure_session()
        session.drain()  # drop any late reply from a previous timeout
        session.send(
            build_nana_start_message(
                state,
                self._last_opponent,
                profile=self.profile,
            )
        )
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
            # nana answers with one move; an empty list means it had no
            # expanded root action yet.  Ask again shortly.
            time.sleep(0.001)
        raise TBPTimeout(f"nana produced no suggestion within {self.timeout:.3f}s")


__all__ = [
    "DEFAULT_NANA_BINARY",
    "DEFAULT_NANA_RULES",
    "DEFAULT_NANA_THREADS",
    "DEFAULT_THINK_TIME",
    "DEFAULT_TIMEOUT",
    "NANA_COMMIT",
    "NANA_CONFIG_FILENAME",
    "NANA_PROFILE",
    "NanaAgent",
    "build_nana_start_message",
    "ensure_nana_config",
    "nana_available",
    "nana_binary_path",
    "nana_config",
    "nana_config_path",
]
