# TETR.IO Season 2 Multiplayer Ruleset (SRS+)

**Purpose.** This document is the normative ruleset reference for the simulator in this repository. It
describes TETR.IO *Tetra League Season 2* 1v1 versus mechanics: board geometry, spawn, 7-bag, hold,
SRS+ rotation with 180s, spin detection (All-Mini+), attack/line-clear values, combo multiplier,
B2B charging and Surge, garbage queueing/cancellation/insertion, lock delay, and top-out.

**Audience.** An engineer implementing `tetrisrl/environment/*`. Every non-obvious rule carries a
citation and a confidence label. Nothing here is invented: where a value could not be verified, it is
**explicitly flagged** and listed in [§13 Uncertainties and configurable approximations](#13-uncertainties-and-configurable-approximations).

**Version target.** Season 2 began with **Beta 1.2.0 (2024-08-16)** ("Welcome to Tetra League Season 2")
and is still the current ranked season in the changelog at the time of writing (latest entry Beta 1.7.8).
Season 2 mechanics changed *within* the season; this document targets the **current** state, i.e. it
includes Beta 1.3.0 (garbage-clearing quad/spin +1) and Beta 1.5.0 (All-Mini+ replaces All-Mini). Where a
rule changed mid-season, both versions are noted. See [§12](#12-season-1--season-2-delta-do-not-implement-the-left-column).

---

## 0. Confidence scheme

| Label | Meaning |
|---|---|
| **[VERIFIED]** | Explicitly documented by an authoritative source (official TETR.IO patch notes / wiki), **or** confirmed by two independent readable reference implementations that agree. |
| **[COMMUNITY]** | Community wiki / community tooling / single reference implementation. No primary documentation, but consistent with observed play. |
| **[UNKNOWN]** | Could not verify. Do **not** hardcode; expose as a config constant with the stated default/approximation. |

**Note on "authoritative".** TETR.IO is closed-source. Its official patch notes
(<https://tetr.io/about/patchnotes/>) and the community TetrisWiki TETR.IO page
(<https://tetris.wiki/TETR.IO>) are the primary documentation. For exact numeric tables we additionally
use two readable open-source implementations:

* **triangle** (`@haelp/teto`, <https://github.com/halp1/triangle>) — a TETR.IO client/engine library that
  models the real game's room presets, kick tables, garbage queue, and damage calc.
* **cobra-movegen** (<https://github.com/Kixenon/cobra-movegen>) — an independent C++ movegen with SRS,
  SRS+ and 180 kick tables.

Where these two agree, tables are marked [VERIFIED]. Where only one implements a table, it is
[COMMUNITY].

**Web-search availability note.** The `web_search` tool was unavailable in this session (HTTP 401 from the
search backend). All research was done with `web_fetch`/direct HTTP against the URLs cited in
[§14](#14-sources). This is a tooling limitation, not a documentation gap: the primary sources below were
retrieved successfully.

---

## 1. Coordinate conventions (read this first)

Two coordinate frames are in play; **never mix them**.

### 1.1 Board frame (cells)

* `x` increases **right**: `0 .. W-1`, `W = 10`.
* `y` increases **up**: `y = 0` is the **bottom row of the visible field**; `y = 19` is the top visible row.
* Rows `20 .. 39` exist but are **hidden** (the "buffer" / vanish zone above the visible field).
* Internal board is therefore `10 x 40`; exactly **20 rows are visible**.
  [VERIFIED] — TetrisWiki: "Playfield size 10 × 40 (default)", TETR.IO gives "10 × 40 (default)" and the
  engine hardcodes `buffer: 20 // there is always a buffer of 20 over the visible board`
  (<https://tetris.wiki/TETR.IO>, <https://github.com/halp1/triangle/blob/main/src/classes/game/index.ts>).

Implementation hint: store the board as `board[y][x]` with `y` bottom-up and `len(board) == 40`. All
spawn/kick math below assumes this.

### 1.2 Kick-offset frame (rotation tests)

* Offsets are `(dx, dy)` **relative to the piece position after basic rotation**, in cells.
* **`+x` = right, `+y` = up.** This is the TetrisWiki SRS convention ("a convention of positive x
  rightwards, positive y upwards is used, e.g. (-1,+2) indicates a kick of 1 cell left and 2 cells up")
  <https://tetris.wiki/Super_Rotation_System>.
* Test order matters. "Test 1" is `(0,0)` (basic rotation); tests 2..5 are tried in order; first legal
  position wins; if all fail the rotation is rejected.

> ⚠️ **Conversion warning.** The `triangle` engine stores offsets with `+y` meaning *down*
> (screen space) and applies them as `y_new = y - dy`; its tables additionally omit the implicit
> `(0,0)` test. The tables below have already been converted to `+y = up` and include `(0,0)` as Test 1.
> If you copy numbers straight out of `triangle`'s `kicks/data.ts`, **negate dy and prepend (0,0)**.

### 1.3 Rotation state names

`0` (spawn) → `R` (clockwise once) → `2` (twice) → `L` (counter-clockwise once). Also written `0,1,2,3`
in implementations.

---

## 2. Board, spawn, generation, previews, hold

### 2.1 Board

| Property | Value | Confidence | Source |
|---|---|---|---|
| Width | **10** | [VERIFIED] | room preset `options.boardwidth = 10`; wiki 10×40 |
| Visible height | **20** | [VERIFIED] | preset `options.boardheight = 20` |
| Hidden buffer rows | **20** (total 40) | [VERIFIED] | engine `buffer: 20` comment; wiki 10×40 |
| ARE (spawn delay) | **0** frames in TETRA LEAGUE | [VERIFIED] | preset `options.are = 0` |
| Line-clear ARE | **0** frames | [VERIFIED] | preset `options.lineclear_are = 0` |
| Gravity (start) | **0.02 G** | [VERIFIED] | preset `options.g = 0.02` |
| Gravity increase | **+0.0035 G/s** after a **7200-frame (120 s)** margin | [VERIFIED] | preset `gincrease=0.0035`, `gmargin=7200` |

(All preset values from `tetra league` preset,
<https://github.com/halp1/triangle/blob/main/src/classes/room/presets.ts>. `g` is in **cells per frame**,
so 0.02 G ≈ 1.2 cells/s; margin times are in **frames at 60 fps** (7200 → 120 s). Implement gravity as a
config float in cells/frame and treat the margin-time increase as optional-but-documented.)

### 2.2 Spawn position and orientation

* Spawn anchor (piece origin) in engine terms: `x = floor(W/2 - matrix_width/2)`, `y = boardHeight + 2.04`
  where `boardHeight` is the **visible** height (20). Cells therefore land in hidden rows ≈ 20–22, i.e.
  above the visible field. [COMMUNITY] (readable implementation)
  — <https://github.com/halp1/triangle/blob/main/src/engine/utils/tetromino/index.ts>
* Net effect matches Guideline: pieces spawn in rows 21–22 counting from the bottom (hidden).
  [VERIFIED] for the guideline rows (<https://tetris.wiki/Super_Rotation_System>), [COMMUNITY] for the
  exact TETR.IO offset.
* **Orientations at spawn** (Guideline/SRS, used unchanged by TETR.IO):
  * All tetrominoes spawn horizontal.
  * `I` and `O` spawn **centrally**; the 3-wide pieces (`J L S T Z`) spawn **rounded to the left**.
  * `J`, `L`, `T` spawn **flat-side first** (spawn state has the nub pointing up).
  * `I`, `S`, `Z` spawn in their upper horizontal orientation.
  * Columns (0-indexed, 10-wide): `JLSTZ` occupy x = 3..5, `I` occupies x = 3..6, `O` occupies x = 4..5.
  [VERIFIED] — <https://tetris.wiki/Super_Rotation_System>; column placement derived from "central /
  rounded to the left".
* **Spawn rotation override table** exists in the engine (`spawn_rotation`, empty for SRS/SRS+), so
  spawn state is always `0` for SRS+. [COMMUNITY]
  — <https://github.com/halp1/triangle/blob/main/src/engine/utils/kicks/data.ts>

### 2.3 Piece generation

* **7-bag**: each bag is a random permutation of `I O T S Z J L`.
  [VERIFIED] — preset `options.bagtype = "7-bag"`; wiki page lists 7-bag as the randomizer family
  (<https://tetris.wiki/TETR.IO>).
* Bag is generated ahead of consumption (engine keeps a queue with `minLength: 31`). [COMMUNITY]
* Other bag types exist in custom rooms (`7+1-bag`, `7+2-bag`, `7+X-bag`, `classic`) — **not** used in
  TETRA LEAGUE. [VERIFIED] — <https://tetr.io/about/patchnotes/> ALPHA 6.4.4.
* **No first-piece exclusion** in versus (the "first piece is never S/Z/O" rule applies only to solo mode
  Stride Mode). [VERIFIED] — <https://tetris.wiki/TETR.IO> ("prevents the first piece from being either
  S, Z, or O" is listed under *solo* Stride Mode).
* **Determinism**: seed the bag RNG per player; expose `rng_seed`. [design requirement of this project]

### 2.4 Preview and hold

| Property | Value | Confidence | Source |
|---|---|---|---|
| Next-piece preview count | **5** (configurable 1–6) | [VERIFIED] | preset `options.nextcount = 5`; wiki "1~6 (default 5)" |
| Hold enabled | **yes** | [VERIFIED] | preset `options.display_hold = true`; wiki "Hold piece: Yes (default)" |
| Hold lock after use | 1 hold per piece (lock until next lock) | [VERIFIED] | engine `holdLocked = false` on lock |
| Infinite hold | off in TETRA LEAGUE | [VERIFIED] | custom-room-only toggle (patchnotes BETA 1.5.0) |
| Hold swap behaviour | swapped piece **spawns at spawn position/state**; hold piece's rotation is not preserved | [COMMUNITY] | standard Guideline + engine `new Tetromino(...)` on hold |
| Hard drop | **yes** | [VERIFIED] | preset `options.allow_harddrop = true` |
| 180° rotation enabled | **yes** | [VERIFIED] | preset `options.allow180 = true` |

---

## 3. SRS+ rotation and kick tables

### 3.1 What SRS+ is

TETR.IO's default rotation system is **SRS+** (added in Alpha 5.0.0, 2020-09-28).

> "…a modified version of SRS as the default option, in which the *I* wall kicks are symmetrical along the
> y-axis, similarly to TGM3; however, the left-side kick tables are mirrored instead of the right side."

[VERIFIED] — <https://tetris.wiki/TETR.IO#SRS+> (citing
<https://tetr.io/about/patchnotes/#chlog_ALPHA_5_0_0>)

Consequences for a simulator:

1. **`J L S T Z` kicks in SRS+ are identical to Guideline SRS.** [VERIFIED] — confirmed by both
   implementations: `triangle`'s `SRS+` block repeats the `SRS` block for the non-`I` piece class, and
   `cobra-movegen`'s `SRS_PLUS` reuses the `LJSZT` table unchanged
   (<https://github.com/Kixenon/cobra-movegen/blob/main/src/gen.hpp>).
2. **`O` never kicks** under SRS. In SRS+ the implementation carries an `O` table with 7 candidate offsets
   (basic + 4 diagonals) — this is the "O-spin" support added by TETR.IO, not Guideline SRS.
   [COMMUNITY] — `oo_kicks` in
   <https://github.com/halp1/triangle/blob/main/src/engine/utils/kicks/data.ts>. See §3.5.
3. **180° rotations use TETR.IO's own table**, different from the Guideline (see §3.4).

### 3.2 JLSTZ kick table (SRS+ = SRS)

`(x, y)` with `+x` right, `+y` up; Test 1 `(0,0)` = basic rotation.
[VERIFIED] — matches TetrisWiki SRS exactly
(<https://tetris.wiki/Super_Rotation_System>) and both implementations.

| From→To | Test 1 | Test 2 | Test 3 | Test 4 | Test 5 |
|---|---|---|---|---|---|
| 0→R | (0, 0) | (-1, 0) | (-1, +1) | (0, -2) | (-1, -2) |
| R→0 | (0, 0) | (+1, 0) | (+1, -1) | (0, +2) | (+1, +2) |
| R→2 | (0, 0) | (+1, 0) | (+1, -1) | (0, +2) | (+1, +2) |
| 2→R | (0, 0) | (-1, 0) | (-1, +1) | (0, -2) | (-1, -2) |
| 2→L | (0, 0) | (+1, 0) | (+1, +1) | (0, -2) | (+1, -2) |
| L→2 | (0, 0) | (-1, 0) | (-1, -1) | (0, +2) | (-1, +2) |
| L→0 | (0, 0) | (-1, 0) | (-1, -1) | (0, +2) | (-1, +2) |
| 0→L | (0, 0) | (+1, 0) | (+1, +1) | (0, -2) | (+1, -2) |

### 3.3 I kick table (SRS+)

This is the table that actually differs from Guideline SRS. Derived from `triangle`'s `SRS+ → i_kicks`
(converted to `+y = up`, `(0,0)` restored). The distinguishing row (0→R) was cross-checked against
`cobra-movegen`'s `SRS_PLUS` table and matches exactly after that implementation's known 1-column I-piece
frame shift. [VERIFIED] for 0→R; [COMMUNITY] for the remaining seven rows (single implementation, but all
eight rows are internally consistent with the "mirrored left-side kicks" description).
[VERIFIED] — <https://github.com/halp1/triangle/blob/main/src/engine/utils/kicks/data.ts>,
<https://github.com/Kixenon/cobra-movegen/blob/main/src/gen.hpp>

| From→To | Test 1 | Test 2 | Test 3 | Test 4 | Test 5 |
|---|---|---|---|---|---|
| 0→R | (0, 0) | (+1, 0) | (-2, 0) | (-2, -1) | (+1, +2) |
| R→0 | (0, 0) | (-1, 0) | (+2, 0) | (-1, -2) | (+2, +1) |
| R→2 | (0, 0) | (-1, 0) | (+2, 0) | (-1, +2) | (+2, -1) |
| 2→R | (0, 0) | (-2, 0) | (+1, 0) | (-2, +1) | (+1, -2) |
| 2→L | (0, 0) | (+2, 0) | (-1, 0) | (+2, +1) | (-1, -2) |
| L→2 | (0, 0) | (+1, 0) | (-2, 0) | (+1, +2) | (-2, -1) |
| L→0 | (0, 0) | (+1, 0) | (-2, 0) | (+1, -2) | (-2, +1) |
| 0→L | (0, 0) | (-1, 0) | (+2, 0) | (+2, -1) | (-1, +2) |

**Difference from Guideline SRS** (important for a simulator): Guideline SRS is *asymmetric* for `I`:

| Transition | Guideline SRS | SRS+ |
|---|---|---|
| 0→L | (0,0), (-1,0), (+2,0), (-1,+2), (+2,-1) | (0,0), (-1,0), (+2,0), (+2,-1), (-1,+2) |
| L→0 | (0,0), (+1,0), (-2,0), (+1,-2), (-2,+1) | (0,0), (+1,0), (-2,0), (+1,-2), (-2,+1) *(same)* |
| R→0 | (0,0), (+2,0), (-1,0), (+2,+1), (-1,-2) | (0,0), (-1,0), (+2,0), (-1,-2), (+2,+1) |
| 2→R | (0,0), (+1,0), (-2,0), (+1,-2), (-2,+1) | (0,0), (-2,0), (+1,0), (-2,+1), (+1,-2) |

So the *set* of candidate positions is the same as SRS in most cases but the **test order changes**;
in SRS+ the mirrored (left-side) variants are tried in the mirrored order, which is what makes
"rotate clockwise or counter-clockwise" symmetric in the wiki's I-piece example
(<https://tetris.wiki/TETR.IO#SRS+>). If your simulator only checks "does *a* kick fit" and not the
order, you will still get *most* placements right but will diverge on the rare double-valid cases.

### 3.4 180° kick table (TETR.IO-specific)

TETR.IO added a custom 180° table in `0.6.0-pre0`; osk posted it as a diagram (no text table) —
<https://tetris.wiki/TETR.IO#180_Kicks>. The numeric table below comes from `cobra-movegen`
(`kicks180`), whose `LJSZT` rows reproduce the posted diagram exactly (same offsets, same order, `+y` up).
[COMMUNITY] for the table (no primary text doc), [VERIFIED] for the mechanism.

**JLSTZ 180°** (`0↔2`, `R↔L`), 6 tests; `+x` right, `+y` up:

| From→To | T1 | T2 | T3 | T4 | T5 | T6 |
|---|---|---|---|---|---|---|
| 0→2 | (0, 0) | (0, +1) | (+1, +1) | (-1, +1) | (+1, 0) | (-1, 0) |
| R→L | (0, 0) | (+1, 0) | (+1, +2) | (+1, +1) | (0, +2) | (0, +1) |
| 2→0 | (0, 0) | (0, -1) | (-1, -1) | (+1, -1) | (-1, 0) | (+1, 0) |
| L→R | (0, 0) | (-1, 0) | (-1, +2) | (-1, +1) | (0, +2) | (0, +1) |

**I 180°** — raw engine values from `cobra-movegen` (`kicks180` row 1, 6 tests, `+y` up, in that
implementation's I-piece frame):

| From→To | T1 | T2 | T3 | T4 | T5 | T6 |
|---|---|---|---|---|---|---|
| 0→2 | (+1, -1) | (+1, 0) | (+2, 0) | (0, 0) | (+2, -1) | (0, -1) |
| R→L | (-1, -1) | (0, -1) | (0, +1) | (0, 0) | (-1, +1) | (-1, 0) |
| 2→0 | (-1, +1) | (-1, 0) | (-2, 0) | (0, 0) | (-2, +1) | (0, +1) |
| L→R | (+1, +1) | (0, +1) | (0, +3) | (0, +2) | (+1, +3) | (+1, +2) |

> **⚠️ [UNKNOWN] — I 180 frame.** `cobra-movegen` stores `I` offsets in a frame shifted one column
> right relative to the canonical SRS `I` frame (verified: its `I SRS` 0→R row, after subtracting 1 from
> every `x`, becomes exactly Guideline SRS). Applying the same `x-1` correction to the table above yields
> `0→2`: `(0,-1), (0,0), (+1,0), (-1,0), (+1,-1), (-1,-1)`. **The correct interpretation of the first
> test is unresolved.** Treat the I-180 table as a *config constant* and validate empirically before
> claiming TETR.IO parity. JLSTZ 180s are safe.

### 3.5 O-piece "kicks" (O-spin support)

Guideline SRS has no O kicks. `triangle`'s SRS/SRS+ `oo_kicks` allow 7 tests: the basic position plus the
four diagonal neighbours and the horizontal neighbours, per rotation. This is what makes TETR.IO O-spins
possible. [COMMUNITY] — <https://github.com/halp1/triangle/blob/main/src/engine/utils/kicks/data.ts>.

Example (SRS+, 0→R), **raw** values as written in `triangle` (its y is screen-down, and the first test is
implicit): `(0,0)` then `(0,-1), (-1,-1), (0,+1), (-1,+1), (+1,0), (+1,-1), (+1,+1)`. Convert to the
board frame with `y → -y` (giving `(0,0), (0,+1), (-1,+1), (0,-1), (-1,-1), (+1,0), (+1,+1), (+1,-1)`).
If exact O-spin parity is out of scope, disable O kicks via config and note the divergence.

---

## 4. Spin detection

### 4.1 Three-corner rule (Guideline, used by TETR.IO)

A spin is awarded when **all** of the following hold
(<https://tetris.wiki/T-Spin>):

1. The **last successful movement of the piece was a rotation** (a translation or fall since the rotation
   cancels spin status).
2. The piece is **immobile** in its final position (cannot be moved/rotated further).
3. **At least 3 of the 4 corners** of the piece's 3×3 (T) bounding box are occupied.
4. Classification:
   * **Full spin**: both "front" corners (the two corners adjacent to the T's nub) are occupied, plus at
     least one back corner.
   * **Mini**: only one front corner occupied (with two back corners) — **except** if the last kick that
     placed the piece moved its centre by **2 rows × 1 column** (the SRS "TST kick", test 5), in which
     case it is a **full** T-spin.

[VERIFIED] for the general rule (<https://tetris.wiki/T-Spin>); [VERIFIED] for the engine's
implementation shape:

* Corner offsets relative to the T's centre are always
  `(-1,-1), (+1,-1), (+1,+1), (-1,+1)`; per rotation the engine marks which two of these are "front"
  corners; `front_corners == 2 → normal`, else `mini`.
  [VERIFIED] — `cornerTable.t` and `#detectSpinFromCorners`
  (<https://github.com/halp1/triangle/blob/main/src/engine/utils/kicks/data.ts>,
  <https://github.com/halp1/triangle/blob/main/src/engine/index.ts>).
* The "TST kick forces full spin" exception is implemented as a `finOrTst` boolean that overrides the
  classification to `normal`. [COMMUNITY] (engine only).

### 4.2 All-Mini+ (TETRA LEAGUE default since Beta 1.5.0)

Season 2 launched (Beta 1.2.0, 2024-08-16) with the spin rule **All-Mini**:

> "The spin rule has changed to All-Mini. All-Spins (immobile spins with pieces other than T) will be
> detected as a Mini. They do not send, but they do add (and keep) Back-to-Back."

[VERIFIED] — <https://tetr.io/about/patchnotes/> BETA 1.2.0.

Beta 1.5.0 (2025-01-18) replaced it with **All-Mini+**, now the default for all multiplayer modes and ZEN:

> "Immobile T-Spins that don't fulfill the three-corner-rule now count as Minis."

[VERIFIED] — <https://tetr.io/about/patchnotes/> BETA 1.5.0; <https://tetris.wiki/TETR.IO> ("It replaced
All-Mini as the default for all multiplayer gamemodes and ZEN").

**Operational definition for the simulator** (this is the rule to implement):

```
if piece is immobile at lock:                      # cannot move or rotate
    if corners_occupied >= 3 or piece_type in ALL_SPIN_TYPES:
        if piece_type is T:
            spin = FULL if front_corners == 2 else MINI     # 3-corner rule
            if last_kick is TST_KICK (|dy| == 2 and |dx| == 1): spin = FULL
        else:
            spin = MINI                            # All-Mini+: every non-T spin is Mini
    else:
        spin = MINI if immobile else NONE          # All-Mini+: immobile T without 3 corners = Mini
else:
    spin = NONE
```

* Under **All-Mini**, an immobile T that fails the 3-corner rule was **not** a spin.
* Under **All-Mini+** it is a **Mini**. [VERIFIED] (patchnotes above)
* Beta 1.5.1 added a **Mini-Only** rule (all T-spins are Minis) — available in custom rooms, *not* default.
  [VERIFIED]
* Only the `T` piece can produce a full spin under All-Mini+; every other piece caps at Mini.
  [VERIFIED] (All-Mini definition: non-T spins are Minis; `types_mini: ["t"]` in the engine's spin-bonus
  rules)

### 4.3 Spin rewards and B2B interaction

* Mini spin clears send **0 / 1 / 2** lines for 1 / 2 / 3 lines cleared (§5 table).
* All-Spins **add to and keep B2B** (they are "difficult clears" for B2B purposes) but their own attack is
  the Mini value (often 0). [VERIFIED] — BETA 1.2.0 notes.
* Spin with **0 lines cleared**: attack 0 (`tspinMini = 0`, `tspin = 0`), but it still counts as a
  "spin" for stats/achievements. [COMMUNITY] — `garbageData` in
  <https://github.com/halp1/triangle/blob/main/src/engine/utils/damageCalc/index.ts>.
* Beta 1.3.0 added: **"Quads and Spins (including All-Spins) that clear garbage now send a flat
  (not influenced by multipliers) +1 extra garbage."** [VERIFIED] — patchnotes BETA 1.3.0; preset flag
  `options.garbagespecialbonus = true` in the TETRA LEAGUE preset.

---

## 5. Attack table, combo, B2B charging, Surge, Perfect Clear

### 5.1 Base attack (garbage lines sent) per clear

[VERIFIED] — the values are identical in TETR.IO's damage calc and in the community attack calculator:
<https://github.com/halp1/triangle/blob/main/src/engine/utils/damageCalc/index.ts> and
<https://github.com/skysomorphic/tetrio-attack-calculator>.

| Clear | Base attack |
|---|---|
| Single (1 line, no spin) | **0** |
| Double | **1** |
| Triple | **2** |
| Quad (Tetris) | **4** |
| Spin, 0 lines | **0** |
| Mini spin single | **0** |
| Mini spin double | **1** |
| Mini spin triple | **2** |
| T-spin single (full) | **2** |
| T-spin double (full) | **4** |
| T-spin triple (full) | **6** |
| Spin quad (theoretical) | 10 |
| Spin penta (theoretical) | 12 |
| All Clear | **5** (Season 2; was 3/10 in earlier versions) |
| 5-line clear (penta, non-spin) | 5 (only possible with 5-wide clears; not standard) |

Notes:

* A **Single sends 0** — this is why 0-combo singles are inert in versus. (QUICK PLAY patches this to 1;
  **not** the case in TETRA LEAGUE.) [VERIFIED] — <https://tetris.wiki/TETR.IO> QUICK PLAY section.
* **All Clear = 5 lines + counts as B2B** in Season 2. [VERIFIED] — BETA 1.2.0 ("All Clears now send 5
  Garbage. However, they also count as Back-to-Back."); preset `allclear_garbage = 5`, `allclear_b2b = 1`.
* The list is applied *before* combo/B2B/multiplier adjustments (§5.2–§5.5).

### 5.2 Combo: the "Multiplier" table

TETRA LEAGUE uses `combotable = "multiplier"` (preset), not the Guideline combo table. [VERIFIED]

> "The exact value is `base*(1+0.25x)` where `x` is combo. If the base attack is 0, the function
> `ln(1+1.25x)` is used for 2-combo and above."

[VERIFIED] — <https://tetris.wiki/TETR.IO#Combo_System:_"Multiplier">

Exact implementation (from the engine's `garbageCalcV2`, which also encodes the minifier):

```python
if combo > 0:
    attack *= (1 + 0.25 * combo)
    if combo > 1:
        attack = max(log1p(1.0 * combo * 1.25), attack)   # ln(1 + 1.25*combo)
```

Equivalent to the wiki: the log form is a **floor** for zero-base attacks (a 2-combo of singles sends
`ln(1+2.5) ≈ 1.25 → 1` line after rounding) and cannot *reduce* a nonzero base.

* Combo counter semantics: starts at `-1`; increments on a piece that clears ≥1 line; resets to `-1` on a
  piece that clears nothing (<https://tetris.wiki/Combo>). So the first clear is combo 0.
* **Rounding** is a separate step applied to the *final* attack:
  * TETRA LEAGUE: `roundmode = "down"` → `floor()`. [VERIFIED] (preset)
  * QUICK PLAY: `"rng"` → weighted random floor/ceil by fractional part. [VERIFIED] — wiki; engine
    `GarbageQueue.round()`.

### 5.3 B2B Charging (Season 2 default; replaces B2B Chaining)

> "B2B sends 1 for every attack (like Guideline), but at B2Bx4, starts charging up a huge Surge Attack.
> Your Surge Attack starts at 4 (so at say, B2Bx8, you will have a Surge of 8 ready). When you break
> Back-to-Back, you will send out your Surge Attack. It is split into three separate attacks."

[VERIFIED] — <https://tetr.io/about/patchnotes/> BETA 1.2.0 (and pre-season BETA 1.1.0/1.1.2);
<https://tetris.wiki/TETR.IO#Back-to-Back_Charging>.

**Rules:**

1. **Difficult clears** = Quad, any **spin that clears ≥ 1 line** (T-spin full or mini, any All-Spin), and
   All Clear. [VERIFIED] — patchnotes 1.2.0 + All-Mini note ("they do add and keep B2B").
   * A spin that clears **no** lines does **not** increment B2B in normal play — the Warlock QUICK PLAY mod
     has to grant that explicitly ("Non-clear Spins increment B2B and send 2 lines"), which confirms the
     default is the opposite. [VERIFIED] — patchnotes BETA 1.7.0, Warlock mod description in
     <https://tetris.wiki/TETR.IO>.
2. Each difficult clear while a streak is alive adds **+1 flat line** to that attack ("like Guideline").
   [VERIFIED]
3. **Surge charge**: while the B2B streak is ≥ 4, a Surge counter accumulates. `surge = displayed B2B
   count` (i.e. no cap, +1 per additional difficult clear), with a floor of the base value 4.
   [VERIFIED] for the semantics/example (B2Bx8 → 8 lines), [COMMUNITY] for the exact displayed-count
   mapping used by the engine formula.
4. **Charge is not spent on normal attacks** — it only matters when the streak breaks. [VERIFIED]
5. **Release**: when the B2B streak breaks — i.e. on a non-difficult line clear **or** on a lock that
   clears nothing — the entire Surge is sent as **three separate attacks**. [VERIFIED] for line-clear
   breaks (wiki/notes); [COMMUNITY] for the no-clear-lock break (engine behaviour only):
   ```
   seg1 = round(surge / 3)
   seg2 = round(surge / 3)
   seg3 = surge - seg1 - seg2      # carries the remainder
   ```
   [VERIFIED] — wiki ("it splits into three segments, with the first and sometimes second segment carrying
   the remainder"), engine (`index.ts`, same formula).
6. Each segment is an **independent attack** and is subject to cancellation **in order** against the
   opponent's queue. Because segments are separate, an opponent with a partial cancel can absorb one
   segment and eat the rest. [VERIFIED] (structure) / [COMMUNITY] (per-segment cancellation is an
   emergent consequence of the event list).
7. Surge values scale with the **garbage multiplier** (time-based), not the combo multiplier.
   [COMMUNITY] — engine multiplies `surged` by `dynamic.garbageMultiplier`.

Engine formula (for exactness), where `btb` = B2B counter *before* the break, `at = 4`, `base = 4` are the
room options `b2bcharge_at` / `b2bcharge_base`:

```python
surge = floor((btb - at + base + 1) * garbage_multiplier)   # only if btb + 1 > at
```

With the TETRA LEAGUE presets this yields `surge == btb` for `btb >= 4` when `base = 3`; with `base = 4`
it yields `btb + 1`. **The exact `at`/`base` pair is [UNKNOWN]** (the values come from the server, not the
client preset) — see §13. Implement as config with `charge_at = 4`, `charge_base = 3`, which reproduces
the documented "B2Bx8 → Surge 8".

**Historical (Season 1) B2B Chaining** — *not* Season 2, included only to avoid confusion: streak→level
table with `+1..+8` bonus lines at ranges 2-3 / 4-8 / 9-24 / 25-67 / 68-185 / 186-504 / 505-1370 / 1371+.
[VERIFIED] — <https://tetris.wiki/TETR.IO#Back-to-Back_Chaining>. TETRA LEAGUE Season 2 has
`b2bchaining = false`, `b2bcharging = true`. [VERIFIED] (preset)

### 5.4 Perfect Clear

* **All Clear sends 5 lines** in Season 2. [VERIFIED] — patchnotes BETA 1.2.0; preset
  `allclear_garbage = 5`.
* All Clear **counts as a B2B** clear (`allclear_b2b = 1`), i.e. it upgrades a non-B2B clear to B2B and
  keeps an existing chain alive. [VERIFIED] — BETA 1.1.1 / 1.2.0 notes.
* The All Clear bonus is added **after** the clear's own attack and after multipliers, as its own garbage
  event (`pc.garbage` pushed separately in the engine). [COMMUNITY] — engine code.
* Only possible if `options.allclears = true` (TETRA LEAGUE: true). [VERIFIED]

### 5.5 Attack computation order (normative pseudocode)

```python
def compute_attack(lines, spin, piece, b2b, combo, garbage_cleared, is_pc):
    base = BASE_ATTACK[(lines, spin)]                    # table §5.1
    if lines > 0 and b2b > 0:
        base += 1                                        # charging rule (§5.3.2)
    if combo > 0:
        base *= 1 + 0.25 * combo
        if combo > 1:
            base = max(log1p(1.25 * combo), base)
    attack = round_mode(base * garbage_multiplier)       # round DOWN in TETRA LEAGUE
    events = [attack] if attack > 0 else []
    if garbage_cleared > 0 and (lines == 4 or spin is not None) and SPECIAL_BONUS:
        events.append(1)                                 # flat +1, not multiplied (§4.3)
    if surge_released:
        s = surge_value
        events = [round(s/3), round(s/3), s - 2*round(s/3)] + events
    if is_pc:
        events.append(round(5 * garbage_multiplier))     # All Clear
    return events
```

*(`round()` here is Python's banker's rounding vs the engine's `Math.round` — use half-up to match JS.)*

---

## 6. Garbage system

### 6.1 TETRA LEAGUE garbage parameters

All from the `tetra league` room preset (Season 2), which the client applies verbatim
[VERIFIED] — <https://github.com/halp1/triangle/blob/main/src/classes/room/presets.ts>:

| Option | Value | Meaning |
|---|---|---|
| `garbagemultiplier` | **1.0** | outgoing attack ×1 |
| `garbagemargin` | **10800** frames (180 s) | time before the multiplier starts rising |
| `garbageincrease` | **0.008** /s | multiplier growth after margin time |
| `garbagespeed` | **20** frames (0.333 s) | delay from *receipt* to *active/insertable* |
| `garbagecap` | **8** | max lines that may enter in one placement ("tank") |
| `garbagecapincrease` | **0** | no increase |
| `garbagecapmax` | **40** | hard ceiling of the per-tank cap |
| `garbageblocking` | **"combo blocking"** | garbage is held while the receiver is mid-combo |
| `passthrough` | **"zero"** | no passthrough (removed as default in Alpha 6.1.2) |
| `garbagespecialbonus` | **true** | +1 flat for garbage-clearing quads/spins (§4.3) |
| `openerphase` | **14** pieces | first-14-pieces double-cancel window |
| `roundmode` | **"down"** | attack rounding |
| garbage messiness | *not in preset* | see §6.4 / §13 |

Cleanliness note: the *absolute* queue cap (`garbageabsolutecap`) is unset in the preset → effectively
unbounded on the client; the server may impose its own. [UNKNOWN]

### 6.2 Queueing, becoming active, insertion

* Incoming attacks are appended to a FIFO queue of `(amount, sender, receive_frame, column)` entries.
  [VERIFIED] — engine `GarbageQueue.receive()`
* An entry becomes **active** only after `garbagespeed` (20) frames; the receiver sees it as "pending".
  [VERIFIED] — engine `tank()` (`item.frame + speed > frame` → not yet).
* **When does garbage enter?** On the next **lock that does not clear lines**:
  * if the lock clears ≥1 line → the attack **cancels** pending garbage instead (§6.3);
  * if the lock clears 0 lines → `tank()` runs and inserts up to `min(garbagecap, cap_max)` = **8** lines.
    [VERIFIED] — engine `#lock()` branch (`if lines>0 … else … garbageQueue.tank(...)`)
* Garbage rows are inserted at the **bottom** and push the existing stack **up**. A row has exactly **one
  hole** (hole size 1) at column `c`; a batch that enters together shares the column unless a reroll
  happens. [VERIFIED] (engine `insertGarbage` + `tank` column logic)
* If insertion pushes any cell above row 39 → **garbage-out / top-out** (§7).

### 6.3 Cancellation

* Cancellation is **FIFO** over the *pending* queue (oldest first). [VERIFIED] — engine
  `GarbageQueue.cancel()` decrements `queue[0]`, removes it at 0, and proceeds to the next entry.
* Cancellation is **partial**: only as many lines as the attack provides are removed; the remainder of the
  attack is **sent to the opponent** (`send = amount - cancelled`). [VERIFIED]
* Multiple attack events (Surge segments, PC bonus) cancel **sequentially**, in the order produced by
  §5.5. If a segment is fully absorbed, the next event still tries to cancel. [COMMUNITY] (emergent from
  the engine's `while res.garbage.length > 0` loop)
* Garbage cleared off the board (blocks removed by line clears) does **not** count as cancellation;
  cancellation is purely queue-based. [COMMUNITY]
* **Opener Phase** (first 14 pieces) [VERIFIED] — patchnotes BETA 1.1.0/1.2.0, wiki:
  > "if the amount of garbage pending in your queue is greater than the amount of garbage you have sent,
  > you will be able to cancel double the lines."

  Engine: `if pieces_placed + 1 <= openerphase and queue_size >= sent: cancel_capacity += attack`.
  Note it compares **pending queue size** vs **lines you have sent this round**, and doubles only the
  cancel capacity, not the outgoing attack.
* A subtlety worth encoding: in the engine, event order is `[surge_segments..., attack, pc]`, and the
  **cancel loop runs before** the leftover is turned into outgoing garbage. [COMMUNITY]
  (Beta 1.7.1 restored "cancelling while being tanked"; ignore for a clean simulator.)

### 6.4 Hole generation and messiness ("change on attack")

TETR.IO uses **"change on attack"** randomization: garbage is generated per *attack*, not per line, and
the hole column may be rerolled between batches. [VERIFIED] — <https://tetris.wiki/TETR.IO> ("notably
using 'change on attack' randomization rules").

Model from the engine (normative structure, values partly [UNKNOWN]):

```
on receipt of an attack:
    column = reroll()                    # uniform over 0..9, see nosame note
    entry = {amount, column}

per line inserted from that entry:
    if rng() < messiness_within and not has_changed_column:
        column = reroll(); has_changed_column = True
    insert row with hole at column

when an entry is exhausted (amount reaches 0):
    if rng() < messiness_change:
        column = reroll(); has_changed_column = True
```

* `messiness_change` — probability a *new* hole column is chosen when a queue entry is exhausted.
* `messiness_within` — probability of moving the hole *within* one attack's lines.
* `messiness_nosame` — never pick the same column twice in a row.
* `messiness_timeout` — reroll after N frames of no tanking.
* `messiness_center` — bias away from the outer columns.

All five are real TETR.IO room options (custom rooms, Alpha 6.4.3:
"You can tweak both change-on-attack messiness and in-attack messiness!"
<https://tetr.io/about/patchnotes/>), but **their TETRA LEAGUE default numeric values are not published**.
[UNKNOWN] — see §13. Sensible defaults for a simulator: `messiness_change = 0.3`,
`messiness_within = 0.0`, `nosame = False`, `timeout = None`, `center = False`. (The QUICK PLAY note
"Between separate attacks, this chance is multiplied by 2.5x" implies a base in the 0.3 ballpark if the
QUICK PLAY value is 0.75 — this is an *inference*, not documentation.)

### 6.5 Tab/priority and multiplayer targeting

* TETRA LEAGUE is 1v1: no targeting choice, all garbage goes to the single opponent.
  [VERIFIED] — targeting only exists for 3+ player rooms.
* Multi-opponent "target bonus" (`enemies` count → +1/+3/+5/+7/+9, applied when
  `garbagetargetbonus != "none"`) exists in the engine but is disabled in 1v1 (0 or 1 enemies → +0).
  [COMMUNITY] — engine `garbageCalcV2`.
* Passthrough is **off** (`"zero"`): garbage cannot cancel garbage already in flight.
  [VERIFIED] — <https://tetris.wiki/TETR.IO#Passthrough> (disabled by default since Alpha 6.1.2; the
  "0.333 s / 20 frames" travel time is exactly `garbagespeed = 20`).

### 6.6 Garbage blocking modes

`garbageblocking` ∈ {`"combo blocking"`, `"limited blocking"`, `"none"`}; TETRA LEAGUE uses
**"combo blocking"**. [VERIFIED] (preset) — the *exact* semantics are **[UNKNOWN]**:
community understanding is that while the receiver has an active combo, incoming garbage is held (not
inserted) until the combo ends, and "limited blocking" only holds small amounts. The `triangle` engine
accepts the option but does not implement the delay. Treat as a config flag with the conservative
implementation: *defer tank() while `combo > 0`* (default on).

---

## 7. Top-out and victory

* **Block out** (used): a new piece spawns overlapping existing blocks → round lost.
  [VERIFIED] — engine `#considerBlockout()`; <https://tetris.wiki/Top_out>.
* **Lock out**: **disabled** by default in TETR.IO multiplayer (`options.nolockout = true`).
  [VERIFIED] — preset; wiki: "This mechanic became redundant when lock out was disabled by default"
  (<https://tetris.wiki/TETR.IO#Clutch_Clear>).
* **Garbage out**: if garbage insertion pushes blocks above the top of the 40-row buffer → loss.
  [COMMUNITY] (standard; TETR.IO's exact check row is unverified).
* **Clutch Clear** (`options.clutch = true`): if a line clear would immediately top you out (block out),
  the next piece is pushed above the stack and play continues. [VERIFIED] — patch notes BETA 1.5.0:
  "If you clear line(s) and would immediately top out afterwards, your next piece will be pushed up to
  allow a final chance at survival." Implement as: after clear, if the spawn position is blocked, shift
  the spawn up by the required rows (≤ some cap) instead of losing.
* **Victory**: TETRA LEAGUE is **first-to-N round wins** (FT3 for ≤A+, FT5 for ≤SS, FT7 for U+), based on
  the *higher* of the two players' ranks. [VERIFIED] — <https://tetris.wiki/TETR.IO#TETRA_LEAGUE>.
  For a simulator, "match" = a single round (one board death); "match series" = FT-N. Both should be
  configurable (`rounds_to_win`).
* **Simultaneous double top-out** in one round: not documented. [UNKNOWN] — pick "round is a draw /
  replay" as a config policy.

---

## 8. Lock delay, movement resets, gravity

| Property | Value | Confidence | Source |
|---|---|---|---|
| Lock delay (`locktime`) | **30 frames = 0.5 s @ 60 fps** | [VERIFIED] | preset `options.locktime = 30` |
| Move/rotate resets (`lockresets`) | **15** | [VERIFIED] (value) / [COMMUNITY] (TETRA LEAGUE default; not in preset) | preset omits `lockresets`; Guideline standard is 15; engine cap `lockResets < 31` |
| Reset trigger | any successful **move or rotation** while grounded resets the 30-frame timer | [VERIFIED] | Guideline "move reset" (<https://tetris.wiki/Lock_delay>); engine increments `lockResets` on rotate/move |
| Rotation allowance | rotations are tracked separately (`rotResets`) and are allowed up to **`lockresets + 15`** | [COMMUNITY] | engine `#shouldFallFaster()` / `#kick()` use `lockResets + 15` |
| Infinite movement | off in TETRA LEAGUE | [VERIFIED] | custom-room-only toggle (patchnotes 1.5.0) |
| Soft drop factor | `sdf = 6` (room default handling; player-side setting in TETRA LEAGUE) | [COMMUNITY] | preset `room_handling_sdf = 6`, `room_handling = false` (player handling used) |
| DAS / ARR | player-side settings (default 10 / 2 frames in preset) | [COMMUNITY] | preset `room_handling_das = 10`, `arr = 2` |

Notes for the simulator:

* Because TETRA LEAGUE uses `are = 0`, there is no spawn delay; the lock timer starts when the piece
  becomes grounded.
* Implement `grounded` as "cannot move down", reset on any successful translation/rotation **and** on
  upward movement; cap resets at 15 (moves) and stop granting resets after 15 rotations.
  The 15-rotation allowance exists so T-spin attempts remain possible; dropping it changes spin-heavy play.
* Gravity: 0.02 G as configured; for a turn-based/placement RL simulator, gravity only affects timing,
  not outcomes — but lock delay & resets still matter for spin detection (spin requires the piece to be
  immobile and last action = rotation, which hard-drop placement trivially satisfies only if the last
  action before lock is a rotation; see §4.1).

---

## 9. Determinism, seeds, replay

* Two independent RNG streams per player: **piece bag** and **garbage**.
  [design requirement — AGENTS.md; engine uses `seed` for both queue and garbage]
* Garbage column choice must be drawn from the garbage RNG *at the moment of the event*, not precomputed,
  because rerolls depend on insertion timing. [COMMUNITY] (engine consumes RNG per reroll/tank)
* A replay must record: seed(s), per-player inputs or per-piece placements, all `garbage.receive`,
  `garbage.cancel`, `garbage.tank`, `lock`, `surge`, `topout` events with frames. [design requirement]

---

## 10. Reference algorithm: one lock, end to end

```
def on_lock(piece, cleared_lines, spin, garbage_cleared, is_pc):
    if cleared_lines > 0:
        combo += 1                          # combo starts at -1, so the first clear is combo 0
    else:
        broke = (b2b > 0)
        combo = -1

    difficult = is_pc or cleared_lines == 4 or (spin is not None and cleared_lines > 0)

    events = compute_attack(...)            # §5.5, uses current b2b/combo before update
    if broke and b2b + 1 > CHARGE_AT:
        s = surge_value(b2b)
        events = [round_half_up(s/3), round_half_up(s/3),
                  s - 2*round_half_up(s/3)] + events
        b2b, surge = 0, 0
    elif difficult:
        b2b += 1
        surge = max(0, b2b - CHARGE_AT + CHARGE_BASE) if b2b >= CHARGE_AT else 0
    else:
        b2b, surge = 0, 0

    if cleared_lines > 0:
        for amount in events:
            remaining = queue.cancel(amount)     # FIFO, partial
            if remaining > 0: opponent.queue.receive(remaining)
    else:
        rows = queue.tank(frame, CAP)            # ≤ 8 lines, active ≥ 20 frames old
        board.insert_garbage(rows)               # bottom-up, one hole each
        if board.overflow(): top_out()
```

---

## 11. Suggested unit-test vectors

1. **Bag**: 7 unique pieces per bag over 10k bags; deterministic under a fixed seed.
2. **Kicks**: for each of the 8 transitions × {JLSTZ, I}, assert the first legal test index matches the
   tables in §3.2/§3.3 for hand-built board fixtures (include a floor-kick and a 1-wide wall well case).
3. **180s**: `0→2` JLSTZ on an open board must land at `(0,0)` (no displacement).
4. **Spin detection**: T-spin double (full, +4), T-spin mini double (+1), immobile-T-without-3-corners
   under All-Mini+ (mini, +0 for single) and under All-Mini (no spin).
5. **Attack**: quad at combo 0 → 4; quad at combo 1 → 5; single at combo 0 → 0; quad with b2b 1 → 5;
   TSD with b2b 1 → 5.
6. **Surge**: reach B2Bx8 then clear a single → three attacks of 3/3/2 (sum 8) plus the single's attack.
7. **Cancel**: opponent 6 pending, attack 4 → cancels 4, sends 0; attack 9 → cancels 6, sends 3.
8. **Opener phase**: pieces 1..14, pending 5 > sent 0, attack 2 → cancels 4.
9. **Garbage insertion**: 8-line attack with cap 8 → 8 rows inserted in one lock; 12-line attack →
   8 rows now, 4 on the following non-clearing lock.
10. **Top-out**: block out on spawn after garbage out; clutch clear prevents the loss.

---

## 12. Season 1 → Season 2 delta (do not implement the left column)

| Mechanic | Season 1 / pre-1.0 | Season 2 (Beta 1.2.0+) |
|---|---|---|
| B2B | **Chaining** (streak→level, +1..+8) | **Charging** (+1 per attack; Surge at B2Bx4) |
| Spin rule | T-spins only | **All-Mini** → **All-Mini+** (Beta 1.5.0) |
| All Clear | 10 lines | **5 lines**, counts as B2B |
| Combo | multiplier (same) | multiplier (same) |
| Opener phase | none | **first 14 pieces double cancel** |
| Lock out | disabled (same) | disabled |
| Quads/spins clearing garbage | no bonus | **+1 flat** (Beta 1.3.0) |

Sources: <https://tetr.io/about/patchnotes/> (1.1.0, 1.1.1, 1.1.2, 1.2.0, 1.3.0, 1.5.0);
<https://tetris.wiki/TETR.IO>.

---

## 13. Uncertainties and configurable approximations

Every item below **must** be a config constant, because it could not be fully verified. Defaults are
chosen to match the most-likely real behaviour; each is tagged with a risk level.

| # | Constant | Default | Confidence / risk | Why it is uncertain |
|---|---|---|---|---|
| 1 | `board_visible_rows` | 20 (+20 buffer = 40) | [VERIFIED] | — (listed for completeness) |
| 2 | `spawn_y` (cells) | rows 20–22 hidden, anchor `y = 22.04` | [COMMUNITY] medium | Exact TETR.IO anchor offset (`.04`) is implementation detail; only affects IRS/block-out edge cases |
| 3 | `ospin_kicks` | enabled (7-position O table) | [COMMUNITY] medium | O-spin support exists in the reference engine; not in Guideline SRS; no official doc |
| 4 | `i180_kicks` | table §3.4, **needs empirical check** | [UNKNOWN] **high** | Frame origin for the I piece 180 table unresolved (x-1 ambiguity) |
| 5 | `b2b_charge_at` | **4** | [VERIFIED] (4) | Documented ("at B2Bx4") |
| 6 | `b2b_charge_base` | **3** (so surge == B2B count) | [UNKNOWN] **high** | Server-side option; wiki/notes only give examples, not the formula's constants |
| 7 | `surge_split` rounding | half-up thirds, last segment takes remainder | [VERIFIED] | — |
| 8 | `all_multi_spins_count_b2b` | true | [VERIFIED] | — |
| 9 | `garbage_messiness_change` | **0.3** | [UNKNOWN] **high** | Not published; custom-room-only knob exposed in Alpha 6.4.3 |
| 10 | `garbage_messiness_within` | **0.0** | [UNKNOWN] high | Same |
| 11 | `garbage_messiness_nosame` | false | [UNKNOWN] high | Same |
| 12 | `garbage_messiness_center` | false | [UNKNOWN] high | QUICK PLAY notes "clean wells only spawn in columns 3-8" (floor ≤5), implying a centre bias in QP; TETRA LEAGUE unverified |
| 13 | `garbage_absolute_cap` | unbounded | [UNKNOWN] medium | `garbageabsolutecap` not in preset; server may cap |
| 14 | `garbage_combo_blocking` | defer tank while `combo > 0` | [UNKNOWN] **high** | Mode is documented (`"combo blocking"`) but semantics/timing are not |
| 15 | `garbage_out_row` | `y >= 40` | [UNKNOWN] medium | Top-out check row for garbage overflow is not documented |
| 16 | `lock_resets` | **15** | [COMMUNITY] medium | Value not in the preset; Guideline standard assumed |
| 17 | `rotation_reset_allowance` | **+15** | [COMMUNITY] medium | Derived from engine `lockResets + 15` |
| 18 | `garbage_multiplier_margin` | 10800 frames / +0.008 per s | [VERIFIED] (preset) | But whether the server starts the clock at round start is unverified |
| 19 | `gravity_margin` | 7200 frames / +0.0035 per s | [VERIFIED] (preset) | Timing only |
| 20 | `double_topout_policy` | draw / replay round | [UNKNOWN] high | Not documented |
| 21 | `clutch_clear` | enabled, max shift 20 rows | [VERIFIED] (exists) / [UNKNOWN] (cap) | Patch notes describe behaviour, not the row cap |
| 22 | `line_clear_are` / `are` | 0 / 0 | [VERIFIED] | — |
| 23 | `penta_clears` | unreachable | [COMMUNITY] | 5-line clear values exist in the table but are normally impossible |
| 24 | `first_piece_exclusion` | disabled | [VERIFIED] | Solo-mode Stride only |

**Simulator isolation.** Put all 24 items in `RulesetConfig` (dataclass/TypedDict) with the defaults
above, and default the *behavioural* approximations (#6, #9–#12, #14, #16–#17) to the values listed. Any
experiment that depends on them must record the config hash.

---

## 14. Sources

Primary (official / authoritative):

1. TETR.IO official patch notes (JSON-backed changelog): <https://tetr.io/about/patchnotes/> — used for
   BETA 1.1.0/1.1.2/1.2.0/1.3.0/1.5.0/1.7.x mechanics.
2. TetrisWiki — TETR.IO: <https://tetris.wiki/TETR.IO> (board size, spin rules, combo multiplier,
   B2B charging/chaining, opener phase, passthrough, QUICK PLAY differences, SRS+, 180 kicks).
3. TetrisWiki — Super Rotation System: <https://tetris.wiki/Super_Rotation_System> (JLSTZ & I kick
   tables, coordinate convention, spawn orientation).
4. TetrisWiki — T-Spin: <https://tetris.wiki/T-Spin> (3-corner rule, mini rule, TST exception).
5. TetrisWiki — Garbage: <https://tetris.wiki/Garbage>; Top out: <https://tetris.wiki/Top_out>;
   Lock delay: <https://tetris.wiki/Lock_delay>; Combo: <https://tetris.wiki/Combo>;
   Playfield: <https://tetris.wiki/Playfield>.

Readable reference implementations:

6. `triangle` (TETR.IO client/engine library), MIT:
   * room presets & defaults: <https://github.com/halp1/triangle/blob/main/src/classes/room/presets.ts>
   * kick tables (SRS, SRS+, SRS-X, 180 ranges, O kicks): <https://github.com/halp1/triangle/blob/main/src/engine/utils/kicks/data.ts>
   * damage calc: <https://github.com/halp1/triangle/blob/main/src/engine/utils/damageCalc/index.ts>
   * garbage queue: <https://github.com/halp1/triangle/blob/main/src/engine/garbage/index.ts>
   * engine (lock/spin/surge): <https://github.com/halp1/triangle/blob/main/src/engine/index.ts>
7. `cobra-movegen` (independent C++ movegen, SRS / SRS+ / 180 tables):
   <https://github.com/Kixenon/cobra-movegen/blob/main/src/gen.hpp>
8. `tetrio-attack-calculator` (community attack/combo/B2B calculator):
   <https://github.com/skysomorphic/tetrio-attack-calculator>
9. `tetrio-bot-docs` (protocol/room option names & meanings):
   <https://github.com/lemoncove/tetrio-bot-docs/blob/main/Room_Config.md>

**Tooling caveat:** `web_search` was unavailable (backend HTTP 401) throughout this session; all sources
above were retrieved directly with HTTP fetches. No rule in this document is based on an unretrieved
claim.
