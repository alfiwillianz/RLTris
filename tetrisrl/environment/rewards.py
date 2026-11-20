"""Configurable reward decomposition.

The reward is the sum of independently logged components, following the
project specification::

    R = R_clear + R_attack + R_defense + R_survival + R_terminal
        - R_board_penalty

Every component is returned in the ``components`` dict so training runs can log
them separately (dashboard + reward ablation experiments).  Weights are
configuration, not code: nothing here assumes the defaults are optimal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class RewardConfig:
    # -- clearing ----------------------------------------------------------
    per_line: float = 1.0
    #: Extra reward per line beyond the first in a single clear (rewards
    #: efficient multi-line clears).
    per_extra_line: float = 0.5
    tetris_bonus: float = 2.0
    spin_bonus: float = 1.0
    mini_spin_bonus: float = 0.5
    perfect_clear_bonus: float = 5.0

    # -- attacking ---------------------------------------------------------
    per_attack_line: float = 1.0
    #: Reward for garbage cancelled by our own attack (defense).
    per_cancelled_line: float = 1.0
    #: Penalty per line of garbage actually inserted on our board.
    per_received_line: float = -0.5

    # -- competitive mechanics --------------------------------------------
    b2b_maintained: float = 0.2
    combo_bonus_per_level: float = 0.05
    surge_bonus: float = 2.0

    # -- survival / termination -------------------------------------------
    per_piece: float = 0.01
    terminal_win: float = 10.0
    terminal_loss: float = -10.0
    terminal_draw: float = 0.0

    # -- board quality -----------------------------------------------------
    #: Penalty per cell of *increase* in aggregate height.
    height_increase: float = -0.05
    #: Reward per cell of height decrease (downstacking).
    height_decrease: float = 0.02
    #: Penalty per new hole.
    hole_created: float = -0.5
    #: Reward per hole removed.
    hole_removed: float = 0.2
    #: Penalty per unit of bumpiness increase.
    bumpiness_increase: float = -0.02
    bumpiness_decrease: float = 0.01
    #: Penalty per unit of max height above a threshold (e.g. 12 visible rows).
    max_height_threshold: int = 12
    max_height_penalty: float = -0.1

    # -- shaping options ---------------------------------------------------
    #: If True, board penalties are computed on absolute values every step
    #: (dense shaping).  Otherwise they are delta-based (default).
    absolute_board_penalty: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "RewardConfig":
        if not data:
            return cls()
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class BoardMetrics:
    aggregate_height: float = 0.0
    max_height: float = 0.0
    holes: float = 0.0
    bumpiness: float = 0.0
    lines: float = 0.0
    filled: float = 0.0


def board_metrics(state) -> BoardMetrics:  # type: ignore[no-untyped-def]
    board = state.board
    return BoardMetrics(
        aggregate_height=float(board.aggregate_height()),
        max_height=float(board.max_height()),
        holes=float(board.holes()),
        bumpiness=float(board.bumpiness()),
        lines=float(state.clear_state.total_lines),
        filled=float(board.filled_cells()),
    )


ZERO_COMPONENTS = {
    "clear": 0.0,
    "attack": 0.0,
    "defense": 0.0,
    "survival": 0.0,
    "terminal": 0.0,
    "board_penalty": 0.0,
    "b2b": 0.0,
    "combo": 0.0,
    "surge": 0.0,
}


def compute_reward(
    cfg: RewardConfig,
    before: BoardMetrics,
    after: BoardMetrics,
    result,
    terminal: bool = False,
    won: Optional[bool] = None,
) -> Tuple[float, Dict[str, float]]:
    """Compute the reward for one agent step.

    ``result`` is a :class:`~tetrisrl.environment.engine.StepResult` (or ``None``
    for synthetic steps).  ``won`` is ``True``/``False``/``None`` at terminal.
    """
    comp: Dict[str, float] = dict(ZERO_COMPONENTS)

    if result is not None and result.valid:
        lines = result.lines
        if lines > 0:
            comp["clear"] += cfg.per_line * lines + cfg.per_extra_line * max(0, lines - 1)
            if lines >= 4:
                comp["clear"] += cfg.tetris_bonus
            if result.spin:
                comp["clear"] += cfg.mini_spin_bonus if result.mini else cfg.spin_bonus
            if result.perfect_clear:
                comp["clear"] += cfg.perfect_clear_bonus
            if result.clear is not None:
                comp["combo"] += cfg.combo_bonus_per_level * max(0, result.clear.combo_after - 1)
                if result.clear.b2b_bonus:
                    comp["b2b"] += cfg.b2b_maintained
        comp["attack"] += cfg.per_attack_line * result.sent
        comp["defense"] += cfg.per_cancelled_line * result.cancelled
        comp["survival"] += cfg.per_piece
        if result.clear is not None and result.clear.surge_bonus:
            comp["surge"] += cfg.surge_bonus

    # Garbage that actually landed on our board.
    inserted = 0
    if result is not None:
        inserted = getattr(result, "garbage_inserted", 0)
    comp["defense"] += cfg.per_received_line * inserted

    # Board-quality shaping.
    if cfg.absolute_board_penalty:
        comp["board_penalty"] += cfg.max_height_penalty * max(0.0, after.max_height - cfg.max_height_threshold)
        comp["board_penalty"] += cfg.hole_created * 0.0
        comp["board_penalty"] += cfg.bumpiness_increase * 0.0
    else:
        dh = after.aggregate_height - before.aggregate_height
        if dh > 0:
            comp["board_penalty"] += cfg.height_increase * dh
        else:
            comp["board_penalty"] += cfg.height_decrease * (-dh)
        dholes = after.holes - before.holes
        if dholes > 0:
            comp["board_penalty"] += cfg.hole_created * dholes
        else:
            comp["board_penalty"] += cfg.hole_removed * (-dholes)
        dbump = after.bumpiness - before.bumpiness
        if dbump > 0:
            comp["board_penalty"] += cfg.bumpiness_increase * dbump
        else:
            comp["board_penalty"] += cfg.bumpiness_decrease * (-dbump)
        comp["board_penalty"] += cfg.max_height_penalty * max(0.0, after.max_height - cfg.max_height_threshold)

    if terminal:
        if won is True:
            comp["terminal"] = cfg.terminal_win
        elif won is False:
            comp["terminal"] = cfg.terminal_loss
        else:
            comp["terminal"] = cfg.terminal_draw

    total = (
        comp["clear"]
        + comp["attack"]
        + comp["defense"]
        + comp["survival"]
        + comp["terminal"]
        + comp["board_penalty"]
        + comp["b2b"]
        + comp["combo"]
        + comp["surge"]
    )
    comp["total"] = total
    return total, comp
