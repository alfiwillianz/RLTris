"""Rotation kick tables (SRS, SRS+ / TETR.IO, and TETR.IO 180-degree kicks).

Kick offsets in this module use the **SRS documentation convention**:

* ``(dx, dy)`` where ``dx > 0`` is right and ``dy > 0`` is **up**.
* The first entry ``(0, 0)`` is the no-kick test (rotation in place).
* Tests are applied in order; the first one that does not collide wins.

The engine converts ``dy`` to board coordinates (``board_y += -dy``).  Keeping
the table in SRS convention makes it directly comparable with published tables,
which is important for auditability.

Sources
-------
Standard SRS tables: tetris.wiki "Super Rotation System" (community-verified,
mirrored by many open-source engines).  SRS+ / TETR.IO-specific additions and
the 180-degree kick table: see ``docs/RULESET.md`` for the exact citations used
for the ``tetrio_s2`` preset and its confidence labels.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

Kick = Tuple[int, int]
KickList = Tuple[Kick, ...]

# ---------------------------------------------------------------------------
# Standard SRS
# ---------------------------------------------------------------------------

# JLSTZ (and, for SRS, the same pattern applies to O while O never visibly moves)
SRS_JLSTZ: Dict[Tuple[int, int], KickList] = {
    (0, 1): ((0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)),
    (1, 0): ((0, 0), (1, 0), (1, -1), (0, 2), (1, 2)),
    (1, 2): ((0, 0), (1, 0), (1, -1), (0, 2), (1, 2)),
    (2, 1): ((0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)),
    (2, 3): ((0, 0), (1, 0), (1, 1), (0, -2), (1, -2)),
    (3, 2): ((0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)),
    (3, 0): ((0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)),
    (0, 3): ((0, 0), (1, 0), (1, 1), (0, -2), (1, -2)),
}

SRS_I: Dict[Tuple[int, int], KickList] = {
    (0, 1): ((0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)),
    (1, 0): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (1, 2): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
    (2, 1): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (2, 3): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (3, 2): ((0, 0), (-2, 0), (1, 0), (-2, -1), (1, 2)),
    (3, 0): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (0, 3): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
}

SRS_O: Dict[Tuple[int, int], KickList] = {
    (0, 1): ((0, 0),),
    (1, 0): ((0, 0),),
    (1, 2): ((0, 0),),
    (2, 1): ((0, 0),),
    (2, 3): ((0, 0),),
    (3, 2): ((0, 0),),
    (3, 0): ((0, 0),),
    (0, 3): ((0, 0),),
}

# ---------------------------------------------------------------------------
# TETR.IO 180-degree rotation kick table
# ---------------------------------------------------------------------------
# 180-degree rotations are a TETR.IO extension (not part of guideline SRS).
# The table below is the commonly mirrored TETR.IO 180 table; every value is
# also settable through ``Ruleset.rotation.kick_overrides`` so it can be
# audited/corrected without touching engine code.  See docs/RULESET.md.

#: JLSTZ 180-degree kicks, keyed by transition (0->2, R->L, 2->0, L->R).
#: Source: cobra-movegen `kicks180` reproducing osk's TETR.IO diagram; see
#: docs/RULESET.md section 3.4.  Confidence: [COMMUNITY] for the table.
TETRIO_180_JLSTZ: Dict[Tuple[int, int], KickList] = {
    (0, 2): ((0, 0), (0, 1), (1, 1), (-1, 1), (1, 0), (-1, 0)),
    (2, 0): ((0, 0), (0, -1), (-1, -1), (1, -1), (-1, 0), (1, 0)),
    (1, 3): ((0, 0), (1, 0), (1, 2), (1, 1), (0, 2), (0, 1)),
    (3, 1): ((0, 0), (-1, 0), (-1, 2), (-1, 1), (0, 2), (0, 1)),
}

#: I-piece 180-degree kicks.  The source table uses a frame shifted one column
#: relative to canonical SRS; the values below apply that correction, but the
#: first test of 0->2 is explicitly [UNKNOWN] in docs/RULESET.md.  Exposed as a
#: ruleset constant so experiments can ablate it.
TETRIO_180_I: Dict[Tuple[int, int], KickList] = {
    (0, 2): ((0, -1), (0, 0), (1, 0), (-1, 0), (1, -1), (-1, -1)),
    (2, 0): ((0, 1), (0, 0), (-1, 0), (1, 0), (-1, 1), (1, 1)),
    (1, 3): ((-1, -1), (0, -1), (0, 1), (0, 0), (-1, 1), (-1, 0)),
    (3, 1): ((1, 1), (0, 1), (0, 3), (0, 2), (1, 3), (1, 2)),
}

TETRIO_180_O: Dict[Tuple[int, int], KickList] = {
    (0, 2): ((0, 0),),
    (2, 0): ((0, 0),),
    (1, 3): ((0, 0),),
    (3, 1): ((0, 0),),
}


# ---------------------------------------------------------------------------
# SRS+ extras (TETR.IO).  Documented in docs/RULESET.md; disabled by default
# unless the preset selects them.
# ---------------------------------------------------------------------------

#: Extra kick tests appended after the standard SRS tests by SRS+.  The
#: authoritative table audit lives in docs/RULESET.md; these are intentionally
#: conservative (they only add tests, never change existing SRS behaviour).
SRS_PLUS_JLSTZ_EXTRA: Tuple[Tuple[Tuple[int, int], KickList], ...] = (
    ((0, 1), ((1, 0), (2, 0))),
    ((1, 0), ((-1, 0), (-2, 0))),
    ((1, 2), ((-1, 0), (-2, 0))),
    ((2, 1), ((1, 0), (2, 0))),
    ((2, 3), ((1, 0), (2, 0))),
    ((3, 2), ((-1, 0), (-2, 0))),
    ((3, 0), ((-1, 0), (-2, 0))),
    ((0, 3), ((1, 0), (2, 0))),
)

SRS_PLUS_I_EXTRA: Tuple[Tuple[Tuple[int, int], KickList], ...] = (
    ((0, 1), ((2, 0),)),
    ((1, 0), ((-2, 0),)),
    ((1, 2), ((-2, 0),)),
    ((2, 1), ((2, 0),)),
    ((2, 3), ((2, 0),)),
    ((3, 2), ((-2, 0),)),
    ((3, 0), ((-2, 0),)),
    ((0, 3), ((-2, 0),)),
)


#: SRS+ I-piece kicks differ from Guideline SRS in *test order* (mirrored
#: left-side tests).  Source: triangle `SRS+ -> i_kicks`, cross-checked against
#: cobra-movegen's SRS_PLUS table after its I-frame correction.
SRS_PLUS_I: Dict[Tuple[int, int], KickList] = {
    (0, 1): ((0, 0), (1, 0), (-2, 0), (-2, -1), (1, 2)),
    (1, 0): ((0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)),
    (1, 2): ((0, 0), (-1, 0), (2, 0), (-1, 2), (2, -1)),
    (2, 1): ((0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)),
    (2, 3): ((0, 0), (2, 0), (-1, 0), (2, 1), (-1, -2)),
    (3, 2): ((0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)),
    (3, 0): ((0, 0), (1, 0), (-2, 0), (1, -2), (-2, 1)),
    (0, 3): ((0, 0), (-1, 0), (2, 0), (2, -1), (-1, 2)),
}


def _merge(base: Dict[Tuple[int, int], KickList], extras: Sequence[Tuple[Tuple[int, int], KickList]]) -> None:
    for key, extra in extras:
        base[key] = tuple(base[key]) + tuple(t for t in extra if t not in base[key])


def build_kick_tables(preset: str = "srs_plus") -> Dict[str, Dict[Tuple[int, int], KickList]]:
    """Return kick tables keyed by piece name.

    ``preset`` is ``"srs"`` (pure guideline SRS, no 180), ``"srs_plus"``
    (TETR.IO SRS+ with 180-degree kicks), or ``"srs_plus_plain180"``.
    """

    if preset not in KICK_TABLE_PRESETS:
        raise ValueError(f"unknown kick preset {preset!r}; expected {KICK_TABLE_PRESETS}")

    jlstz = {k: tuple(v) for k, v in SRS_JLSTZ.items()}
    i_piece = {k: tuple(v) for k, v in SRS_I.items()}
    o_piece = {k: tuple(v) for k, v in SRS_O.items()}

    if preset in ("srs_plus", "srs_plus_plain180"):
        jlstz = {k: tuple(v) for k, v in SRS_JLSTZ.items()}
        i_piece = {k: tuple(v) for k, v in SRS_PLUS_I.items()}

    tables: Dict[str, Dict[Tuple[int, int], KickList]] = {}
    for name in ("J", "L", "S", "T", "Z"):
        tables[name] = dict(jlstz)
    tables["I"] = dict(i_piece)
    tables["O"] = dict(o_piece)

    if preset != "srs":
        for name in tables:
            table = tables[name]
            # 180-degree transitions, keyed per direction (TETR.IO tables are
            # direction-specific, not symmetric).
            table180 = TETRIO_180_I if name == "I" else (TETRIO_180_O if name == "O" else TETRIO_180_JLSTZ)
            table.update(table180)
    else:
        for name in tables:
            for a, b in ((0, 2), (2, 0), (1, 3), (3, 1)):
                tables[name][(a, b)] = ((0, 0),)

    return tables


KICK_TABLE_PRESETS: Tuple[str, ...] = ("srs", "srs_plus", "srs_plus_plain180")


def targets(from_state: int, direction: int) -> int:
    """Rotation direction is ``+1`` (clockwise), ``-1`` (counter-clockwise),
    ``2`` (180 degrees)."""
    if direction == 2:
        return (from_state + 2) % 4
    return (from_state + direction) % 4


def kick_tests(table: Dict[Tuple[int, int], KickList], from_state: int, direction: int) -> KickList:
    """Return the ordered kick tests for a rotation, in SRS (x, y-up) space."""
    if direction == 2:
        to_state = (from_state + 2) % 4
    else:
        to_state = (from_state + direction) % 4
    return table.get((from_state, to_state), ((0, 0),))


def apply_kick(cells: Sequence[Tuple[int, int]], dx: int, dy_up: int) -> List[Tuple[int, int]]:
    """Translate piece cells by a kick given in SRS convention (y up positive)."""
    return [(x + dx, y - dy_up) for x, y in cells]
