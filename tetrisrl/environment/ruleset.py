"""Ruleset configuration.

Every mechanic that could differ between TETR.IO seasons, modes, or our
simplifications is a constant on :class:`RulesetConfig` so experiments can
ablate it and so uncertain values are isolated and auditable (see
``docs/RULESET.md`` for sources and confidence labels).

Two presets ship with the project:

``tetrio_s2``
    TETR.IO Season 2 multiplayer defaults (SRS+, 180 rotations, b2b charging +
    surge, TETR.IO attack table).  Values marked ``[UNCERTAIN]`` in
    docs/RULESET.md are approximations and are configurable.
``guideline``
    Classic guideline SRS with the older (pre-charging) b2b bonus, used for
    contrast experiments and for benchmark compatibility.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple

from .rotation import KICK_TABLE_PRESETS


@dataclass(frozen=True)
class BoardConfig:
    width: int = 10
    height: int = 40
    visible_height: int = 20
    preview: int = 5
    spawn_x: int = 3
    spawn_y: int = 18
    buffer_rows: int = 20


@dataclass(frozen=True)
class RotationConfig:
    preset: str = "srs_plus"
    allow_180: bool = True
    #: Rotation direction the engine uses when it rotates a placement into
    #: place.  ``"cw"``/``"ccw"`` are used only for spawn-space kicks.
    spawn_rotation: str = "cw"

    def validate(self) -> None:
        if self.preset not in KICK_TABLE_PRESETS:
            raise ValueError(f"unknown kick preset {self.preset!r}; expected {KICK_TABLE_PRESETS}")


@dataclass(frozen=True)
class LockConfig:
    #: Lock delay in milliseconds.  Placement-based agents hard-drop, so this
    #: only matters for gravity-driven (human/scripted) play.
    lock_delay_ms: int = 500
    max_lock_resets: int = 15
    reset_on_move: bool = True
    reset_on_rotate: bool = True
    #: TETR.IO uses a 0.5 s lock delay with 15 movement resets.
    gravity_cells_per_second: float = 0.0


@dataclass(frozen=True)
class AttackTable:
    """Base attack (garbage lines) per clear type."""

    single: int = 0
    double: int = 1
    triple: int = 2
    tetris: int = 4
    #: Mini spins send 0 / 1 / 2 for 1 / 2 / 3 lines (Season 2 table).
    tspin_mini_single: int = 0
    tspin_mini_double: int = 1
    tspin_mini_triple: int = 2
    tspin_single: int = 2
    tspin_double: int = 4
    tspin_triple: int = 6
    spin_quad: int = 10
    spin_penta: int = 12
    penta: int = 5
    #: Flat +1 added to a difficult clear while a B2B streak is alive.
    b2b_bonus: int = 1
    #: Combo is multiplicative in TETRA LEAGUE: base * (1 + 0.25 * combo).
    combo_multiplier: float = 0.25
    #: Floor for zero-base attacks: max(ln(1 + 1.25 * combo), attack).
    combo_log_base: float = 1.25
    #: All Clear attack (Season 2) and whether it counts as a B2B clear.
    all_clear: int = 5
    all_clear_counts_as_b2b: bool = True
    #: Flat bonus for quads/spins that clear garbage (Beta 1.3.0).
    garbage_special_bonus: int = 1
    #: Attack rounding: "floor" in TETRA LEAGUE.
    round_mode: str = "floor"
    #: Kept for the legacy GUIDELINE preset (additive combo table).
    perfect_clear: int = 10
    combo_table: Tuple[int, ...] = (0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 5)
    b2b_difficult_only: bool = True

    def base_attack(self, lines: int, spin: bool, mini: bool) -> int:
        if spin:
            if mini:
                return {1: self.tspin_mini_single, 2: self.tspin_mini_double, 3: self.tspin_mini_triple}.get(lines, 0)
            return {1: self.tspin_single, 2: self.tspin_double, 3: self.tspin_triple, 4: self.spin_quad, 5: self.spin_penta}.get(lines, 0)
        return {1: self.single, 2: self.double, 3: self.triple, 4: self.tetris, 5: self.penta}.get(lines, 0)

    def combo_attack(self, combo: int) -> int:
        if combo <= 0:
            return 0
        idx = min(combo, len(self.combo_table) - 1)
        return self.combo_table[idx]


@dataclass(frozen=True)
class B2BConfig:
    """Back-to-back behaviour.

    ``mode="classic"``: a difficult clear after another difficult clear gains
    ``attack_table.b2b_bonus``.  ``mode="charging"``: TETR.IO Season 2 style
    charging - each b2b clear also accumulates charge; when the charge reaches
    ``surge_threshold`` it is released as a "surge" that boosts the next attack
    (and resets the charge).
    """

    mode: str = "charging"
    #: The surge starts charging once the B2B streak reaches this count.
    charge_at: int = 4
    #: Server-side formula constant (see docs/RULESET.md §5.3); charge_base=3
    #: with charge_at=4 reproduces the documented "B2Bx8 -> Surge 8".
    charge_base: int = 3
    #: Time-based garbage multiplier (1.0 in TETRA LEAGUE before 180 s).
    garbage_multiplier: float = 1.0
    #: Release surge when a lock clears nothing (engine behaviour).
    surge_on_no_clear: bool = True


@dataclass(frozen=True)
class GarbageConfig:
    #: Garbagespeed is 20 frames (~0.333 s) in TETRA LEAGUE; in our piece-based
    #: clock one piece is the closest configurable approximation.
    insertion_delay_pieces: int = 1
    #: Maximum pending garbage (lines) that can sit in the queue.
    queue_cap: int = 40
    #: Garbage cap per placement ("tank"): at most 8 lines enter per lock.
    tank_cap: int = 8
    tank_cap_max: int = 40
    #: ``per_row``: every garbage row gets its own hole.
    #: ``per_batch``: one hole per entry (TETR.IO "change on attack").
    hole_mode: str = "per_batch"
    #: Change-on-attack messiness probabilities (TETRA LEAGUE values [UNKNOWN]).
    messiness_change: float = 0.3
    messiness_within: float = 0.0
    messiness_nosame: bool = False
    #: Defer tanking while the receiver has an active combo.
    combo_blocking: bool = True
    #: Cancel incoming garbage with outgoing attack at attack generation time.
    cancel_incoming: bool = True
    #: Garbage applied in chunks (each attack event is one entry).
    max_chunk: int = 8
    #: Rows are inserted from the bottom (standard) - kept explicit for clarity.
    insert_from_bottom: bool = True


@dataclass(frozen=True)
class SpinConfig:
    #: ``corner``: T-spin if 3 of 4 T corners are occupied.
    #: ``corner_spin_in``: additionally require that a rotation could have been
    #: the last action (piece resting, rotation into the final state legal).
    #: ``strict``: require the agent's placement to have used a rotation and
    #: pass the corner rule.
    detection: str = "corner_spin_in"
    #: All-Mini+ (Season 2 default since Beta 1.5.0): non-T immobile spins are
    #: mini, and an immobile T without the 3-corner rule is also mini.
    all_mini: bool = True
    all_mini_plus: bool = True
    #: Award spin credit for non-T pieces (I-spins) if their mini/full corners
    #: test passes.  TETR.IO has dedicated spin handling; disabled by default.
    non_t_spins: bool = False


@dataclass(frozen=True)
class RulesetConfig:
    name: str = "tetrio_s2"
    board: BoardConfig = field(default_factory=BoardConfig)
    rotation: RotationConfig = field(default_factory=RotationConfig)
    lock: LockConfig = field(default_factory=LockConfig)
    attack: AttackTable = field(default_factory=AttackTable)
    b2b: B2BConfig = field(default_factory=B2BConfig)
    garbage: GarbageConfig = field(default_factory=GarbageConfig)
    spin: SpinConfig = field(default_factory=SpinConfig)
    #: Lock out is disabled in TETR.IO multiplayer (options.nolockout = true).
    lock_out: bool = False
    #: Clutch clear (Beta 1.5.0): survive a would-be block out after a clear.
    clutch_clear: bool = False
    #: If True garbage that forces a block above the ceiling is a top-out.
    garbage_top_out: bool = True

    def validate(self) -> None:
        self.rotation.validate()
        if self.b2b.mode not in ("classic", "charging"):
            raise ValueError(f"unknown b2b mode {self.b2b.mode!r}")
        if self.garbage.hole_mode not in ("per_row", "per_batch"):
            raise ValueError(f"unknown garbage hole_mode {self.garbage.hole_mode!r}")
        if self.spin.detection not in ("corner", "corner_spin_in", "strict"):
            raise ValueError(f"unknown spin detection {self.spin.detection!r}")
        if self.board.height < self.board.visible_height:
            raise ValueError("board height must be >= visible_height")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RulesetConfig":
        data = dict(data or {})
        nested = {
            "board": BoardConfig,
            "rotation": RotationConfig,
            "lock": LockConfig,
            "attack": AttackTable,
            "b2b": B2BConfig,
            "garbage": GarbageConfig,
            "spin": SpinConfig,
        }
        kwargs: Dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            if f.name in nested:
                sub = nested[f.name]
                allowed = {sf.name for sf in fields(sub)}
                kwargs[f.name] = sub(**{k: v for k, v in value.items() if k in allowed})
            else:
                kwargs[f.name] = value
        obj = cls(**kwargs)
        obj.validate()
        return obj


def guideline_ruleset() -> RulesetConfig:
    return RulesetConfig(
        name="guideline",
        rotation=RotationConfig(preset="srs", allow_180=False),
        attack=AttackTable(),
        b2b=B2BConfig(mode="classic"),
        garbage=GarbageConfig(hole_mode="per_row", messiness_change=0.2, insertion_delay_pieces=0),
        spin=SpinConfig(detection="corner_spin_in", all_mini=False, all_mini_plus=False),
        lock_out=True,
    )


def tetrio_s2_ruleset() -> RulesetConfig:
    cfg = RulesetConfig(
        name="tetrio_s2",
        rotation=RotationConfig(preset="srs_plus", allow_180=True),
        attack=AttackTable(),
        b2b=B2BConfig(mode="charging"),
        garbage=GarbageConfig(hole_mode="per_batch"),
        spin=SpinConfig(detection="corner_spin_in", all_mini=True, all_mini_plus=True),
        lock_out=False,
    )
    cfg.validate()
    return cfg


def tetrio_s1_ruleset() -> RulesetConfig:
    """Season 1-style ruleset (classic b2b, no charging) for ablation."""
    cfg = tetrio_s2_ruleset()
    cfg = RulesetConfig.from_dict(
        {
            **cfg.to_dict(),
            "name": "tetrio_s1",
            "b2b": {**cfg.to_dict()["b2b"], "mode": "classic"},
        }
    )
    return cfg


PRESETS = {
    "tetrio_s2": tetrio_s2_ruleset,
    "tetrio_s1": tetrio_s1_ruleset,
    "guideline": guideline_ruleset,
}


def load_ruleset(name_or_config: Any) -> RulesetConfig:
    if isinstance(name_or_config, RulesetConfig):
        return name_or_config
    if isinstance(name_or_config, dict):
        return RulesetConfig.from_dict(name_or_config)
    if isinstance(name_or_config, str):
        if name_or_config in PRESETS:
            return PRESETS[name_or_config]()
        raise ValueError(f"unknown ruleset preset {name_or_config!r}; expected one of {tuple(PRESETS)}")
    raise TypeError(f"cannot load ruleset from {type(name_or_config)!r}")
