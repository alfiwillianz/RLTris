"""Deterministic 1v1 versus arena.

Both players run independent :class:`GameState` instances with independent
seven-bag and garbage RNGs.  A tick is *simultaneous*: both agents choose an
action from the state at the start of the tick, both actions are applied, and
then the resulting attacks are delivered to the opponent's pending queue.

A match is fully deterministic given ``(ruleset, seed, agent behaviours,
max_pieces)``, which is what makes replay verification possible: the replay
stores the seeds and the per-tick actions, and re-applying them must reproduce
the identical final boards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

from .engine import GameState, StepResult
from .ruleset import RulesetConfig, load_ruleset


class MatchAgent(Protocol):
    name: str

    def reset(self, seed: Optional[int] = None) -> None: ...

    def choose_action(self, state: GameState, opponent_state: Optional[GameState] = None) -> int: ...


def _agent_name(agent: Any) -> str:
    return getattr(agent, "name", type(agent).__name__)


@dataclass
class PlayerStats:
    pieces: int = 0
    lines: int = 0
    attack: int = 0
    attack_sent: int = 0
    cancelled: int = 0
    garbage_received: int = 0
    garbage_inserted: int = 0
    four_lines: int = 0
    tspins: int = 0
    mini_tspins: int = 0
    perfect_clears: int = 0
    max_combo: int = 0
    max_b2b: int = 0
    surges: int = 0
    holds: int = 0
    top_out_reason: str = ""
    final_height: int = 0
    final_holes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pieces": self.pieces,
            "lines": self.lines,
            "attack": self.attack,
            "attack_sent": self.attack_sent,
            "cancelled": self.cancelled,
            "garbage_received": self.garbage_received,
            "garbage_inserted": self.garbage_inserted,
            "four_lines": self.four_lines,
            "tspins": self.tspins,
            "mini_tspins": self.mini_tspins,
            "perfect_clears": self.perfect_clears,
            "max_combo": self.max_combo,
            "max_b2b": self.max_b2b,
            "surges": self.surges,
            "holds": self.holds,
            "top_out_reason": self.top_out_reason,
            "final_height": self.final_height,
            "final_holes": self.final_holes,
        }


@dataclass
class MatchResult:
    winner: Optional[int]  # 0 = a, 1 = b, None = draw
    reason: str
    ticks: int
    stats: Tuple[PlayerStats, PlayerStats]
    replay: Dict[str, Any] = field(default_factory=dict)
    final_hashes: Tuple[int, int] = (0, 0)

    @property
    def winner_name(self) -> str:
        return {0: "a", 1: "b", None: "draw"}[self.winner]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "winner": self.winner,
            "reason": self.reason,
            "ticks": self.ticks,
            "stats": [s.to_dict() for s in self.stats],
            "final_hashes": list(self.final_hashes),
        }


def annotate_frame_colors(ticks: List[dict], frames: List[dict]) -> None:
    """Reconstruct per-cell piece colours for replay frames.

    The engine stores occupancy bitboards (no colour provenance), so the
    dashboard would otherwise render a grey stack.  Replays already record each
    placement's cells, cleared rows and garbage insertions, which is exactly
    enough to rebuild the colour layer deterministically:

    1. paint the locked piece's cells with its letter,
    2. remove cleared rows and shift the rest down,
    3. insert garbage rows (marked ``G``) at the bottom.

    Any remaining occupied but unpainted cell (e.g. a scripted test board) is
    rendered as garbage grey.
    """
    for side in ("a", "b"):
        colors = [[""] * 10 for _ in range(40)]
        for tick, frame in zip(ticks, frames):
            event = tick.get(side, {})
            for cell in event.get("cells", []):
                x, y = int(cell[0]), int(cell[1])
                if 0 <= x < 10 and 0 <= y < 40:
                    colors[y][x] = str(event.get("piece", ""))
            cleared = list(event.get("cleared_rows") or [])
            if cleared:
                cleared_set = set(cleared)
                kept = [row for i, row in enumerate(colors) if i not in cleared_set]
                colors = [[""] * 10 for _ in range(len(cleared))] + kept
            inserted = sum(int(ev.get("amount", 0)) for ev in (event.get("garbage_events") or []))
            if inserted:
                colors = colors[inserted:] + [["G"] * 10 for _ in range(inserted)]
            snapshot = frame.get(side, {})
            board_rows = snapshot.get("rows") or []
            lines = []
            for y in range(40):
                mask = int(board_rows[y]) if y < len(board_rows) else 0
                row_chars = []
                for x in range(10):
                    occupied = bool(mask >> x & 1)
                    if not occupied:
                        row_chars.append(".")
                    else:
                        row_chars.append(colors[y][x] or "G")
                lines.append("".join(row_chars))
            snapshot["colors"] = lines


def derive_seeds(seed: int) -> Tuple[int, int, int, int]:
    """Derive independent, well-separated seeds for both players."""
    base = int(seed) & 0x7FFFFFFF
    return (
        (base * 2654435761 + 1) & 0x7FFFFFFF,
        (base * 40503 + 7919) & 0x7FFFFFFF,
        (base * 2246822519 + 3266489917) & 0x7FFFFFFF,
        (base * 668265263 + 374761393) & 0x7FFFFFFF,
    )


class VersusMatch:
    def __init__(
        self,
        agent_a: MatchAgent,
        agent_b: MatchAgent,
        ruleset: RulesetConfig | str | Dict[str, Any] = "tetrio_s2",
        seed: int = 0,
        max_pieces: int = 1000,
        record_frames: bool = True,
        record_events: bool = True,
        match_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.ruleset = load_ruleset(ruleset)
        self.agent_a = agent_a
        self.agent_b = agent_b
        self.seed = int(seed)
        self.max_pieces = int(max_pieces)
        self.record_frames = record_frames
        self.record_events = record_events
        self.match_id = match_id
        self.metadata = metadata or {}
        self.sa_seed, self.sb_seed, self.ga_seed, self.gb_seed = derive_seeds(seed)
        self.state_a = GameState(self.ruleset, seed=self.sa_seed, garbage_seed=self.ga_seed, player_id=0, max_pieces=max_pieces)
        self.state_b = GameState(self.ruleset, seed=self.sb_seed, garbage_seed=self.gb_seed, player_id=1, max_pieces=max_pieces)
        self.invalid_actions = [0, 0]

    # ------------------------------------------------------------------
    def _choose(self, agent: MatchAgent, state: GameState, other: GameState) -> int:
        action = agent.choose_action(state, other)
        if not isinstance(action, int) or not (0 <= action < 80):
            action = -1
        if action < 0 or not state.action_mask()[action]:
            # Never let a buggy agent crash a match: fall back to the first
            # legal placement and count the failure (reported in the summary).
            mask = state.action_mask()
            fallback = next((i for i, ok in enumerate(mask) if ok), -1)
            self.invalid_actions[0 if agent is self.agent_a else 1] += 1
            return fallback
        return action

    def run(self) -> MatchResult:
        self.agent_a.reset(self.seed)
        self.agent_b.reset(self.seed + 1)
        stats_a = PlayerStats()
        stats_b = PlayerStats()
        ticks: List[dict] = []
        frames: List[dict] = []
        winner: Optional[int] = None
        reason = "max_pieces"
        t = 0
        ticks_played = 0

        for t in range(self.max_pieces):
            if self.state_a.finished or self.state_b.finished:
                break
            action_a = self._choose(self.agent_a, self.state_a, self.state_b)
            action_b = self._choose(self.agent_b, self.state_b, self.state_a)
            if action_a < 0 or action_b < 0:
                # One side cannot move at all (should have topped out already).
                if action_a < 0:
                    winner, reason = 1, "no_legal_action_a"
                elif action_b < 0:
                    winner, reason = 0, "no_legal_action_b"
                else:
                    winner, reason = None, "no_legal_actions"
                break

            res_a = self.state_a.apply_action(action_a)
            res_b = self.state_b.apply_action(action_b)

            if res_a.sent > 0 and not self.state_b.finished:
                self.state_b.receive_attack(res_a.sent)
                stats_b.garbage_received += res_a.sent
            if res_b.sent > 0 and not self.state_a.finished:
                self.state_a.receive_attack(res_b.sent)
                stats_a.garbage_received += res_b.sent
            if res_a.garbage_inserted:
                stats_a.garbage_inserted += res_a.garbage_inserted
            if res_b.garbage_inserted:
                stats_b.garbage_inserted += res_b.garbage_inserted

            if self.record_events:
                ticks.append(
                    {
                        "t": t,
                        "a": {"action": action_a, **res_a.to_event()},
                        "b": {"action": action_b, **res_b.to_event()},
                    }
                )
            if self.record_frames:
                frames.append({"a": self.state_a.snapshot(), "b": self.state_b.snapshot()})

            ticks_played = t + 1
            a_out, b_out = res_a.top_out or self.state_a.top_out, res_b.top_out or self.state_b.top_out
            if a_out and b_out:
                winner, reason = None, "double_top_out"
            elif a_out:
                winner, reason = 1, "top_out_a"
            elif b_out:
                winner, reason = 0, "top_out_b"
            if winner is not None:
                break
        else:
            ticks_played = t + 1

        # Final stats.
        for stats, st in ((stats_a, self.state_a), (stats_b, self.state_b)):
            cs = st.clear_state
            stats.pieces = st.pieces_placed
            stats.lines = cs.total_lines
            stats.attack = cs.total_attack
            stats.attack_sent = st.garbage_sent
            stats.cancelled = st.garbage.total_cancelled
            stats.four_lines = cs.tetrises
            stats.tspins = cs.tspins
            stats.mini_tspins = cs.mini_tspins
            stats.perfect_clears = cs.perfect_clears
            stats.max_combo = cs.max_combo
            stats.max_b2b = cs.max_b2b
            stats.surges = cs.surges_released
            stats.holds = st.hold_count
            stats.top_out_reason = st.topped_out_reason
            stats.final_height = st.board.max_height()
            stats.final_holes = st.board.holes()

        hashes = (self.state_a.board.state_hash(), self.state_b.board.state_hash())
        if self.record_frames and self.record_events and frames and ticks:
            annotate_frame_colors(ticks, frames)

        replay = {
            "version": 1,
            "match_id": self.match_id,
            "ruleset": self.ruleset.to_dict(),
            "seed": self.seed,
            "seeds": {"a_piece": self.sa_seed, "b_piece": self.sb_seed, "a_garbage": self.ga_seed, "b_garbage": self.gb_seed},
            "max_pieces": self.max_pieces,
            "agents": {"a": _agent_name(self.agent_a), "b": _agent_name(self.agent_b)},
            "metadata": self.metadata,
            "ticks": ticks,
            "frames": frames,
            "result": {
                "winner": winner,
                "reason": reason,
                "ticks": ticks_played,
                "stats": [stats_a.to_dict(), stats_b.to_dict()],
                "final_hashes": list(hashes),
                "invalid_actions": list(self.invalid_actions),
            },
        }
        return MatchResult(winner, reason, ticks_played, (stats_a, stats_b), replay, hashes)


def replay_actions(
    ruleset: RulesetConfig | str | Dict[str, Any],
    seed: int,
    actions_a: List[int],
    actions_b: List[int],
    max_pieces: int = 1000,
) -> Tuple[GameState, GameState]:
    """Re-apply recorded actions without any agent (replay verification)."""
    sa_seed, sb_seed, ga_seed, gb_seed = derive_seeds(seed)
    a = GameState(ruleset, seed=sa_seed, garbage_seed=ga_seed, player_id=0, max_pieces=max_pieces)
    b = GameState(ruleset, seed=sb_seed, garbage_seed=gb_seed, player_id=1, max_pieces=max_pieces)
    for action_a, action_b in zip(actions_a, actions_b):
        if a.finished or b.finished:
            break
        ra = a.apply_action(action_a)
        rb = b.apply_action(action_b)
        if ra.sent > 0:
            b.receive_attack(ra.sent)
        if rb.sent > 0:
            a.receive_attack(rb.sent)
    return a, b


def verify_replay(replay: Dict[str, Any]) -> bool:
    """Check that a replay's final board hashes are reproducible."""
    actions_a = [tick["a"]["action"] for tick in replay["ticks"]]
    actions_b = [tick["b"]["action"] for tick in replay["ticks"]]
    a, b = replay_actions(replay["ruleset"], replay["seed"], actions_a, actions_b, replay.get("max_pieces", 1000))
    hashes = [a.board.state_hash(), b.board.state_hash()]
    return hashes == list(replay["result"]["final_hashes"])
