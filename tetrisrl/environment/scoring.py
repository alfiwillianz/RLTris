"""Attack generation: Season 2 base table, combo multiplier, B2B charging, surge.

Implements the normative computation order from ``docs/RULESET.md`` §5.5::

    base = BASE_ATTACK[(lines, spin)]
    if difficult and b2b > 0: base += 1
    if combo > 0: base *= 1 + 0.25*combo  (with the ln(1+1.25*combo) floor)
    attack = floor(base * garbage_multiplier)
    events = [surge segments on a B2B break] + [attack] + [all-clear bonus]

TETR.IO sends garbage as *events*, each of which is cancelled independently
(FIFO, partial).  Surge is released as three events when the B2B streak breaks,
either on a non-difficult clear or on a lock that clears nothing.

All numbers are configuration; the defaults are the TETRA LEAGUE Season 2
values verified in docs/RULESET.md.  Modes:

``charging`` (Season 2)
    Surge accumulates while the streak is >= ``charge_at`` and is released on a
    break.
``classic``  (Season 1 / guideline)
    Flat +1 per difficult clear while a streak is alive; no surge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .ruleset import RulesetConfig


@dataclass
class ClearState:
    """Mutable competitive-scoring state owned by a :class:`GameState`."""

    #: Combo counter: -1 = no combo, 0 = first clear of a combo (TETR.IO).
    combo: int = -1
    b2b: int = 0
    surge: int = 0
    last_clear: Optional[Dict[str, object]] = None
    total_attack: int = 0
    total_lines: int = 0
    b2b_breaks: int = 0
    surges_released: int = 0
    tspins: int = 0
    mini_tspins: int = 0
    tetrises: int = 0
    perfect_clears: int = 0
    max_combo: int = 0
    difficult_clears: int = 0
    max_b2b: int = 0


@dataclass
class ClearComponents:
    lines: int = 0
    spin: bool = False
    mini: bool = False
    perfect_clear: bool = False
    difficult: bool = False
    base_attack: int = 0
    b2b_flat: int = 0
    combo_before: int = -1
    combo_after: int = -1
    combo_multiplier: float = 1.0
    pre_round_attack: float = 0.0
    attack: int = 0
    attack_events: List[int] = field(default_factory=list)
    surge_released: bool = False
    surge_value: int = 0
    surge_segments: List[int] = field(default_factory=list)
    b2b_before: int = 0
    b2b_after: int = 0
    surge_after: int = 0
    total_attack: int = 0
    garbage_special_bonus: int = 0

    # Backwards-compatible aliases used by rewards/dashboard code.
    @property
    def b2b_bonus(self) -> int:
        return self.b2b_flat

    @property
    def surge_bonus(self) -> int:
        return sum(self.surge_segments)

    @property
    def b2b_chain_before(self) -> int:
        return self.b2b_before

    @property
    def b2b_charge_before(self) -> float:
        return float(self.surge_value)

    @property
    def b2b_charge_after(self) -> float:
        return float(self.surge_after)

    @property
    def b2b_active_after(self) -> bool:
        return self.b2b_after > 0

    @property
    def combo_attack(self) -> int:
        return self.attack

    def as_dict(self) -> Dict[str, object]:
        return {
            "lines": self.lines,
            "spin": self.spin,
            "mini": self.mini,
            "perfect_clear": self.perfect_clear,
            "difficult": self.difficult,
            "base_attack": self.base_attack,
            "b2b_flat": self.b2b_flat,
            "b2b_before": self.b2b_before,
            "b2b_after": self.b2b_after,
            "combo_before": self.combo_before,
            "combo_after": self.combo_after,
            "combo_multiplier": self.combo_multiplier,
            "attack": self.attack,
            "attack_events": list(self.attack_events),
            "surge_released": self.surge_released,
            "surge_value": self.surge_value,
            "surge_segments": list(self.surge_segments),
            "surge_after": self.surge_after,
            "total_attack": self.total_attack,
        }


def split_surge(amount: int) -> List[int]:
    """Split a surge attack into three segments (TETR.IO formula)."""
    if amount <= 0:
        return []
    first = int(round(amount / 3))
    second = int(round(amount / 3))
    third = amount - first - second
    return [first, second, third]


def _round_attack(value: float, mode: str) -> int:
    if mode == "floor":
        return int(math.floor(value))
    if mode == "ceil":
        return int(math.ceil(value))
    return int(round(value))


def compute_attack(
    ruleset: RulesetConfig,
    state: ClearState,
    lines: int,
    spin: bool,
    mini: bool,
    perfect_clear: bool,
    garbage_cleared: int = 0,
) -> ClearComponents:
    """Apply one line clear to ``state`` (mutating it) and return its attack."""
    atk = ruleset.attack
    b2b_cfg = ruleset.b2b

    comp = ClearComponents(
        lines=lines,
        spin=spin,
        mini=mini,
        perfect_clear=perfect_clear,
        combo_before=state.combo,
        b2b_before=state.b2b,
    )

    difficult = (lines == 4) or (spin and lines >= 1) or (perfect_clear and lines > 0)
    comp.difficult = difficult

    # ---- combo -----------------------------------------------------------
    if lines > 0:
        state.combo += 1
        state.max_combo = max(state.max_combo, state.combo)
    comp.combo_after = state.combo

    # ---- base attack -----------------------------------------------------
    comp.base_attack = atk.base_attack(lines, spin, mini)

    if difficult and state.b2b > 0:
        comp.b2b_flat = atk.b2b_bonus

    attack_value = float(comp.base_attack + comp.b2b_flat)
    if state.combo > 0:
        comp.combo_multiplier = 1.0 + atk.combo_multiplier * state.combo
        attack_value *= comp.combo_multiplier
        if state.combo > 1:
            attack_value = max(math.log1p(atk.combo_log_base * state.combo), attack_value)
    comp.pre_round_attack = attack_value
    comp.attack = _round_attack(attack_value * b2b_cfg.garbage_multiplier, atk.round_mode)

    # ---- surge release on a B2B break -----------------------------------
    events: List[int] = []
    if not difficult and state.b2b > 0 and state.surge > 0 and b2b_cfg.mode == "charging":
        comp.surge_released = True
        comp.surge_value = state.surge
        comp.surge_segments = split_surge(state.surge)
        events.extend(comp.surge_segments)
        state.b2b = 0
        state.surge = 0
        state.surges_released += 1
        state.b2b_breaks += 1
    elif not difficult and state.b2b > 0:
        state.b2b = 0
        state.b2b_breaks += 1

    if comp.attack > 0:
        events.append(comp.attack)

    # ---- garbage-clearing quads / spins: flat +1 -------------------------
    if garbage_cleared > 0 and (lines == 4 or spin) and atk.garbage_special_bonus > 0:
        comp.garbage_special_bonus = atk.garbage_special_bonus
        events.append(atk.garbage_special_bonus)

    # ---- all clear -------------------------------------------------------
    if perfect_clear and lines > 0:
        events.append(_round_attack(atk.all_clear * b2b_cfg.garbage_multiplier, atk.round_mode))
        state.perfect_clears += 1

    # ---- B2B streak update ----------------------------------------------
    if difficult:
        state.b2b += 1
        state.max_b2b = max(state.max_b2b, state.b2b)
        state.difficult_clears += 1
        if b2b_cfg.mode == "charging" and state.b2b >= b2b_cfg.charge_at:
            raw = state.b2b - b2b_cfg.charge_at + b2b_cfg.charge_base + 1
            state.surge = max(0, int(math.floor(raw * b2b_cfg.garbage_multiplier)))
    elif lines > 0:
        state.b2b = 0
        state.surge = 0

    comp.attack_events = events
    comp.total_attack = sum(events)
    comp.b2b_after = state.b2b
    comp.surge_after = state.surge

    # ---- counters --------------------------------------------------------
    state.total_attack += comp.total_attack
    state.total_lines += lines
    if spin:
        state.tspins += 1
        if mini:
            state.mini_tspins += 1
    elif lines == 4:
        state.tetrises += 1
    state.last_clear = comp.as_dict()
    return comp


def on_no_clear(ruleset: RulesetConfig, state: ClearState) -> List[int]:
    """Handle a lock that clears nothing.

    Resets the combo and, if a B2B charging streak with surge is alive, releases
    the surge as three independent attacks.  Returns the attack events.
    """
    state.combo = -1
    state.last_clear = None
    events: List[int] = []
    if state.b2b > 0:
        if ruleset.b2b.mode == "charging" and state.surge > 0:
            events = split_surge(state.surge)
            state.surges_released += 1
        state.b2b = 0
        state.surge = 0
        state.b2b_breaks += 1
    return events


# Backwards-compatible name used by tests / external callers.
def compute_clear(ruleset, state, lines, spin, mini, perfect_clear, garbage_cleared: int = 0) -> ClearComponents:
    return compute_attack(ruleset, state, lines, spin, mini, perfect_clear, garbage_cleared)
