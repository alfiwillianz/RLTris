# Engine Audit — Group C

**Repositories audited:** `nullpomino/nullpomino`, `tetris-bot-protocol/tbp-spec`,
`tetris-bot-protocol/battletris`.

**Date:** 2026-11-20 · **Mode:** read-only source audit. No audited repository was
cloned, built, installed, or modified (only this report file was written). All evidence below comes from GitHub's tree API and
`raw.githubusercontent.com` (plus the `tbp` crate tarball from crates.io and two
public kick-table sources used to check SRS+ parity). `web_search` was not used
(it is broken with HTTP 401 in this environment); `web_fetch` was used for
<https://tetris.wiki/TETR.IO>.

**Confidence legend**

- `[VERIFIED]` — read directly in source/spec text at the cited location.
- `[INFERRED]` — follows from source but was not executed; includes build/run
  feasibility claims (nothing was built, per the task).
- `[UNKNOWN]` — not determinable from the files fetched (or fetch failed).

**Known audit limitations**

- The GitHub REST API returned **HTTP 403 rate-limit** after the three tree
  calls, so repo metadata (stars, releases, archived flag, licence API field)
  was **not** fetched. Licence conclusions below are from actual `LICENSE`
  files and source headers, which is stronger evidence anyway.
- No full per-file licence scan was possible without cloning. Spot checks found
  one non-OSI file (see NullpoMino), so the NullpoMino licence inventory is
  explicitly partial: `[UNKNOWN]` for files not sampled.
- All mechanics claims are from reading code/spec; no behaviour was executed.

---

## 1. One-line verdicts

| Repo | What it actually is | Verdict |
|---|---|---|
| `nullpomino/nullpomino` | Java 8 / Maven, GUI-first playable Tetris clone with many modes, in-engine heuristic AIs, Guideline SRS (+ a non-TETR.IO 180 table) | **Reference implementation, not an RL environment.** Richest mechanics cross-check, but GUI-only, 10×20+3 board, old VS attack model, mixed per-file licensing. Integration: **HIGH** effort, subprocess only. |
| `tetris-bot-protocol/tbp-spec` | 4 Markdown files defining a JSON-lines stdin/stdout bot protocol | **Protocol specification only — no engine, no code, no licence file.** Useful as an opponent-interop contract; cannot supply S2 state. Integration: **LOW** (client) / **MEDIUM** (host). |
| `tetris-bot-protocol/battletris` | Rust CLI referee/host that runs two TBP bot executables headless, PPT-style garbage table, SPRT/FT/count formats | **Headless match host/referee, not an engine and not a visualiser.** No licence, non-deterministic RNG, wall-clock timing. Integration: **MEDIUM** as external referee, **HIGH** as an RL env. |

---

## 2. NullpoMino

Repo: <https://github.com/nullpomino/nullpomino> · tree HEAD
`4de098dd0b48d991247313d8dba30b9721e6f9d9` (fetched via
`api.github.com/repos/nullpomino/nullpomino/git/trees/HEAD?recursive=1`,
714 blobs, not truncated) · last commit `2021-08-02T00:12:27Z` from
`commits/HEAD.atom`.

### 2.1 Licence — BSD-3-Clause at repo and file level, with non-OSI exceptions

| Artefact | Licence | Evidence |
|---|---|---|
| `LICENSE` (repo root) | **BSD 3-Clause** ("BSD 3-Clause License", Copyright (c) 2019, TSTman) | `LICENSE:1-3` `[VERIFIED]` |
| `nullpomino-run/LICENCE.txt` | **BSD 3-Clause** text, Copyright (c) 2010, NullNoname | file text `[VERIFIED]` |
| Most `mu/nu/nullpo/**` Java files | per-file **BSD 3-Clause** header, Copyright (c) 2010, NullNoname (identical 3-clause terms) | e.g. `StandardWallkick.java:1-23`, `AIPlayer.java:1-23` `[VERIFIED]` |
| `net/clarenceho/crypto/RC4.java` | **NON-OSI**: "Redistribution and use of this software for **non-profit, educational, or persoanl** [sic] purposes" | `RC4.java:1-9` `[VERIFIED]` |
| `net/omegaboshi/**` randomizers, `net/tetrisconcept/poochy/**` AIs, `com/centerkey/utils/BareBonesBrowserLaunch.java` | **No licence header at all** (default: all rights reserved, no grant) | e.g. `BagRandomizer.java:1`, `PoochyBot.java:1` `[VERIFIED]` |
| `biz/source_code/base64Coder/Base64Coder.java` | multi-licensed EPL / LGPL / Apache / **BSD** | file header `[VERIFIED]` |
| `org/cacas/java/gnu/tools/Crypt.java` | BSD (header says derivative of Eric Young BSD code) | file header `[VERIFIED]` |
| Vendored jars | sdljava **LGPL-2**, SDL **LGPL-2.1**, JOrbis/jogg **LGPL-2**, log4j **Apache-2.0**, LWJGL/Slick/IBXM **BSD** | `readme_en.txt:551-593` `[VERIFIED]` |
| Media assets (`res/se`, `res/graphics`, music) | third-party attributions with **no explicit licence** (TAM Music Factory, "The matchmakers", Yun Free Stock Photos, etc.) | `readme_en.txt:595-620` `[VERIFIED]` |

**Answer to "is it per-repo or per-file, and is any code non-OSI?"** Both:
the root licence is BSD-3-Clause (2019 fork maintainer), and the
`mu/nu/nullpo/**` files sampled carry the same BSD-3-Clause terms (2010
NullNoname), but the tree is *not* uniformly BSD. At least one code file (`RC4.java`) is under a **non-OSI,
non-commercial** licence, and several contributed source directories carry **no
licence grant**. So: "BSD-3-Clause with non-OSI and unlicensed patches" is the
accurate characterisation. `[VERIFIED]` for the cited files; full inventory
`[UNKNOWN]` (no clone).

Practical consequence: **do not copy any NullpoMino code into TetrisRL.**
Subprocess execution is the only clean mode, and even that would require
distributing the LGPL natives and non-free assets if we shipped it.

### 2.2 Language, build, dependencies, GPU, Linux

| Item | Finding |
|---|---|
| Language | Java (source/target **1.8** in `nullpomino-parent/pom.xml:23-25`) `[VERIFIED]` |
| Build | Maven multi-module (`nullpomino-parent` → `nullpomino-core`, `nullpomino-run`); README says `cd nullpomino-parent && mvn package`, then `nullpomino-run/target/install/play_swing` (`README.md:21-30`) `[VERIFIED]` |
| Version | README documents stable **7.5.0**; poms are **7.6.0-SNAPSHOT** (`nullpomino-parent/pom.xml:6`) `[VERIFIED]` |
| Dependencies | 10 vendored jars under `nullpomino-core/lib/...LOCAL/` (sdljava, slick, lwjgl-LOCAL, log4j 1.2.15, jorbis, jogg, ibxm, jinput, swing-layout, swing-worker) **plus** `org.lwjgl.lwjgl:lwjgl:2.9.3` from Maven Central (`nullpomino-core/pom.xml`) `[VERIFIED]`; build therefore needs network for LWJGL unless already in `~/.m2` `[INFERRED]` |
| Native libs | `nullpomino-run/lib/libsdljava.so` is **ELF 32-bit LSB, Intel i386** (`file` on the raw blob) `[VERIFIED]`; the lib dir also ships `liblwjgl.so` **and** `liblwjgl64.so`, `libopenal.so`/`libopenal64.so`, `libjinput-linux(-64).so`, but **only a 32-bit `libsdljava.so`** — so the SDL renderer is the 32-bit-constrained path, not the Swing one |
| Linux feasibility | **Yes**, but with caveats: Swing path (`play_swing` → `mu.nu.nullpo.gui.swing.NullpoMinoSwing`) is pure Java and 64-bit-safe; the SDL path likely needs a 32-bit JVM + 32-bit SDL 1.2 stack in practice (Slick uses LWJGL, which has 64-bit natives) `[INFERRED]` from the bundled `.so` set |
| GPU | **Not required** (Java2D/Swing, or OpenGL 1.x via LWJGL for the Slick path) `[INFERRED]` |

### 2.3 Implemented mechanics (from source)

| Mechanic | Status / exact behaviour | Evidence |
|---|---|---|
| Board | Configurable; defaults **10 wide × 20 visible + 3 hidden = 23 rows** (not TETR.IO's 10×40) | `Field.java:51-57`, `RuleOptions.java:94-100`, `Standard.rul:252,275,324` `[VERIFIED]` |
| 7-bag | Framework has `BagRandomizer`, `BagRandomizerNoSZO`, `MemorylessRandomizer`, `History*Rolls`, Nintendo, etc. The shipped **`Standard.rul` selects `BagNoSZORandomizer`**, a 7-bag whose *first* bag is reshuffled while the first piece is O/S/Z | `Standard.rul:24`, `BagNoSZORandomizer.java:17-27` `[VERIFIED]` |
| SRS | **Guideline SRS.** `Standard.rul` selects `StandardWallkick`; JLSTZ rows carry the 4 post-`(0,0)` SRS offsets. `[VERIFIED]` | `Standard.rul:1`, `StandardWallkick.java:40-70` |
| SRS deviation (I, CCW) | I **CW** rows carry 4 offsets (5 tests incl. basic). I **CCW** rows carry only **3** offsets (4 tests) — one Guideline candidate omitted. So I-piece CCW is an SRS approximation, not exact Guideline SRS | `StandardWallkick.java:54-60`; counts verified per row `[VERIFIED]` for counts, `[INFERRED]` for effect |
| O piece | No dedicated table: O falls through to the JLSTZ table. The O occupies the same cells in all four orientations (`Piece.java:64-82`), so basic rotation always succeeds and O kicks are effectively unreachable — no O-spin support (TETR.IO SRS+ has a 7-test O table) | `StandardWallkick.java:131-160`, `Piece.java:64-82` `[VERIFIED]`; unavailability `[INFERRED]` |
| 180° rotation | **Yes**, enabled by default (`rotateButtonAllowDouble = true`), bound to `Controller.BUTTON_E`, passed as `move == 2`; used only when normal rotation fails | `RuleOptions.java:181,391`; `GameEngine.java:1462-1478,1480-1492`; `GameEngine.java:2230` `[VERIFIED]` |
| 180° kick table | **NullpoMino's own table**: **11 candidate offsets for JLSTZ**, **5 for I**, including ±2 and ±3 horizontal kicks. This is *not* TETR.IO's 6-test table | `StandardWallkick.java:112-124` (counts verified) `[VERIFIED]` |
| Upward kicks | Upward offsets are skipped only if `allowUpward == false`; default `rotateMaxUpwardWallkick = -1` means always allowed, so SRS upward kicks are not filtered | `BaseStandardWallkick.java:40-50`, `RuleOptions.java:388` `[VERIFIED]` |
| Spin detection | T-piece only (`if piece.id != PIECE_T return`). 4-point/3-corner (`count >= 3`), mini by rotate-check or kick flag, optional IMMOBILE detection and "EZ" spin; generic "all-spin bonus" changes scoring, **not** detection | `GameEngine.java:1245-1318` `[VERIFIED]` |
| Hold | Yes; `holdEnable`, `holdLimit = -1`, initial hold, reset direction | `RuleOptions.java:115-127,366-370` `[VERIFIED]` |
| Hard drop / previews | Yes; `nextDisplay = 3` default, `6` in `Standard.rul` | `RuleOptions.java:112,364`, `Standard.rul:56` `[VERIFIED]` |
| Garbage queue | `LinkedList<GarbageEntry>` per player, `garbageSent`, `garbage` counters; attack inserts an entry for the opponent; garbage is inserted **all at once** after a lock that does not clear lines when "blocking" is on (otherwise after any lock) | `VSBattleMode.java:101-105,178-180,1068-1092,1105-1170` `[VERIFIED]` |
| Garbage cancellation | Yes: "countering" subtracts attack points from the front of the incoming queue, leftover passes through; "blocking" prevents insertion on a line-clear lock | `VSBattleMode.java:1072-1084,1105` `[VERIFIED]` |
| Garbage holes | Single hole per row; three modes (change every line / per rise / per attack), `garbagePercent` chance to move the hole; no per-attack cap/split, no rise speed/timer | `VSBattleMode.java:71-93,1112-1166` `[VERIFIED]` |
| Combo | Yes; additive table `{0,0,1,1,2,2,3,3,4,4,4,5}` indexed by `combo-1` (capped) | `VSBattleMode.java:68,1028-1034` `[VERIFIED]` |
| B2B | **Flat +1 line** (+2 only for T-spin triple, version ≥ 1); `b2bType 2` sends it as a separate garbage entry ("separated"). No charging, no surge | `VSBattleMode.java:1011-1025,1091-1093` `[VERIFIED]` |
| All clear | +6 attack | `VSBattleMode.java:1037-1040` `[VERIFIED]` |
| Attack table (VS) | Single 0, Double 1, Triple 2, Quad 4, T-spin single 2, double 4, triple 6, mini 1, mini-double 3 (all-spin only), EZ 1. Classic NullpoMino/TDS-style, **not** TETR.IO S2 | `VSBattleMode.java:945-1040` `[VERIFIED]` |
| TETR.IO Season 2 | **Absent** (see §2.5) | no S2 terms anywhere in the files read `[VERIFIED]` for read files |

Two extra details worth knowing: `VSBattleMode` is versioned (`CURRENT_VERSION = 5`,
`VSBattleMode.java:50`), so old replays change garbage/B2B behaviour by version;
and the engine supports non-standard pieces (`I2`, `I3`, `L3`) used by other
modes, so piece tables are not purely the 7 tetrominoes.

### 2.4 SRS+ and TETR.IO-180 compatibility — **NO**

Cross-checked against two independent SRS+ implementations fetched for this
audit: `triangle` (`src/engine/utils/kicks/data.ts`, `"SRS+"` block and
`i_kicks`) and `cobra-movegen` (`src/gen.hpp`, `kicks180` and `I SRS+`).

| Check | NullpoMino | TETR.IO SRS+ / TETR.IO 180 | Verdict |
|---|---|---|---|
| JLSTZ kick table/order | Guideline SRS order: `0→R` tests `(0,0),(-1,0),(-1,+1),(0,-2),(-1,-2)` (y-up) | SRS+ JLSTZ **is identical to SRS** (triangle `"SRS+"` block; cobra reuses `LJSZT`) | Same `[VERIFIED]` |
| I-piece CW ordering (`0→R`) | `(0,0),(-2,0),(+1,0),(-2,-1),(+1,+2)` (y-up, from `I_R[0]`) | SRS+ `(0,0),(+1,0),(-2,0),(-2,-1),(+1,+2)` — tests 2/3 swapped (mirrored order) | **Differs** `[VERIFIED]` |
| I-piece CCW rows | 4 tests (one candidate missing) | SRS+ 5 tests | **Differs** `[VERIFIED]` |
| 180 table | **11 JLSTZ offsets / 5 I offsets** *after* the basic position (so 12/6 tests), incl. `(±2,0)`, `(±3,0)` | TETR.IO custom 180: **6 tests including the basic position**, e.g. JLSTZ `0→2` = `(0,0),(0,+1),(+1,+1),(-1,+1),(+1,0),(-1,0)` (cobra `kicks180`; TetrisWiki shows only a diagram) | **Different table** `[VERIFIED]` both sides |
| O kicks | O falls through to JLSTZ table | SRS+ has a 7-test O table (triangle `oo_kicks`) | **Differs** `[INFERRED]` |

**Conclusion:** NullpoMino implements **Guideline SRS (with a truncated
I-CCW table) plus a NullpoMino-specific 180 table**. It does **not** implement
TETR.IO SRS+ kick ordering and it does **not** implement the TETR.IO 180 table.
Do not cite it as an SRS+ authority.

### 2.5 TETR.IO Season 2 support — **ABSENT**

| S2 feature | NullpoMino status |
|---|---|
| B2B charging (streak adds attack) | **Absent.** Flat `+1` per B2B clear (`VSBattleMode.java:1011-1025`) |
| Surge accumulation/release | **Absent.** No surge state anywhere in `VSBattleMode`/`GameEngine` |
| Season 2 attack table | **Absent.** Uses the classic table above; combo is additive, not the S2 multiplier |
| Garbage speed / cap / roll-in | **Absent.** Garbage is inserted in one shot after the next non-clearing lock when blocking is on (`VSBattleMode.java:1105-1170`); no rise delay, no per-packet cap, no roll-in animation state |
| All-Mini+ | **Absent.** Spin detection is T-only; "all spin" is a scoring flag, not immobile detection for every piece (`GameEngine.java:1245-1318`) |

### 2.6 Headless local simulation — **NO**

- There is **no general headless match-runner/CLI**. Runnable entry points are
  GUIs: `scripts/play_swing` → `mu.nu.nullpo.gui.swing.NullpoMinoSwing`;
  `play_slick`/`play_sdl` → LWJGL/SDL GUIs with `-Djava.library.path=lib`.
  `scripts/netserver` starts `mu.nu.nullpo.game.net.NetServer`, a
  **lobby/relay server**, not a simulation. `scripts/airankstool` is a Swing
  tuning GUI. `[VERIFIED]` for entry points.
- The one genuinely headless `main` in the tree is
  `mu.nu.nullpo.tool.airankstool.AIRanksTester`: it runs 25 *fictitious* games
  against `RanksAI.playFictitiousMove(heights, pieces, hold, holdOK)` using a
  9-entry height array, `History4RollsRandomizer` and no `GameEngine`, board,
  garbage or versus interaction. It is a RanksAI-specific sanity tool, **not** a
  general simulator. `[VERIFIED]` (`AIRanksTester.java:1-77`).
- AIs are **in-engine plugins**: `AIPlayer` (`AIPlayer.java:33-100`) is called
  per frame and **writes button bits into the `Controller`** (`BasicAI.java:156-190`),
  not placements. `PoochyBot` is a heuristic search over placements
  (`MAX_THINK_DEPTH` loop at `PoochyBot.java:859`, twist handling around 514-600),
  still driving the controller. Selecting an AI is a GUI/config-menu action
  (`doc/airanks_readme_en.txt`: "config menu → AI setting").
- The game loop is driven by GUI state classes and modes call `EventReceiver`/
  `Renderer` methods (e.g. `VSBattleMode.java:39,694-735`), so even an in-process
  harness would have to supply a dummy renderer and replicate the state machine.
  `[INFERRED]` effort: **HIGH**; not a ready environment.

### 2.7 Role

**Playable reference implementation with in-engine heuristic AIs.** Not an RL
environment (no observation/action API, no reset/step, no headless loop), not a
protocol, not a placement-suggesting service. Best use: behavioural cross-check
for SRS/VS semantics and as a source of comparison ideas (PoochyBot/RanksAI).

### 2.8 Integration options

| Option | Feasibility | Notes |
|---|---|---|
| Protocol/API | **None** | No IPC/JSON/HTTP interface; `NetServer` speaks the game's own netplay protocol (undocumented here) — absence `[VERIFIED]` from the tree |
| Subprocess | **Only realistic mode**, and still hard: launch a GUI under Xvfb, or write a Java harness against `GameEngine`/`VSBattleMode` | GUI input automation is brittle; harness needs a renderer stub + mode/state machine `[INFERRED]` |
| Linking / copying | **Forbidden by project policy and risky here** | Mixed licences incl. non-OSI `RC4.java`, unlicensed AI/randomizer files, LGPL natives, non-free assets |

**Integration complexity: HIGH.** Java/Maven separate stack, GUI-coupled loop,
no placement API, 10×20+3 board and non-TETR.IO 180/SRS make rule parity work
non-trivial even if a headless harness existed.

### 2.9 Licence risk / safe integration mode

Safe mode: **reference only — do not vendor, link, port, or copy.** If we ever
run it, run it as an unmodified separate process and do not redistribute its
assets/natives. Note that even a reimplementation of its kick tables is better
sourced from TETR.IO-targeted references (triangle/cobra) than from this repo.

---

## 3. `tbp-spec` — Tetris Bot Protocol specification

Repo: <https://github.com/tetris-bot-protocol/tbp-spec> · tree HEAD
`31a589f4d1b53e4ce24c9fcc052865407d849457` · last commit `2021-08-08T03:34:17Z`.

Whole repo is **4 files**: `README.md`, `text/0000-mvp.md`,
`text/0001-randomizer.md`, `text/0003-move_info.md`. **No code, no engine, no
build system, no tests, no `LICENSE`** (`GET .../LICENSE` → 404;
`.../LICENSE.md` → 404). `[VERIFIED]`

### 3.1 Licence — **none / all rights reserved**

No `LICENSE`/`COPYING` file is in the tree (and the usual paths return 404),
and `README.md` has no licence section; GitHub's licence metadata could not be
queried because the REST API was rate-limited. Under default copyright, the **spec
text is not licensed for reuse**. The *protocol* (message names, JSON shape) is
a functional interface and can be implemented independently, but do not copy
prose, tables, or the README into TetrisRL docs; write our own description and
link to the spec. `[VERIFIED]` absence; legal characterisation `[INFERRED]`.

Related: the Rust `tbp` crate (separate repo `tbp-rs`, used by battletris) is
**MIT OR Apache-2.0** per crates.io metadata for 3.0.0. That crate, not
`tbp-spec`, is what a Rust integrator would link. `[VERIFIED]` crates.io API.

### 3.2 What it is — **protocol specification only**

README says it aims to be a common interface between a Tetris bot and a
frontend, "similar to how the Universal Chess Interface solves a similar
problem for Chess" (`README.md`). It defines message flow and JSON payloads;
it defines **no board mechanics, no attack tables, no garbage system, no
rotation kick tables** (only loose defaults: 10×40 board, spawn at x=4, ~y=19,
hold allowed, SRS). No language/build/GPU requirement exists because there is no
code: **GPU requirement N/A**. `[VERIFIED]`

### 3.3 Exact message fields

Transport: one JSON object per line over **stdin/stdout** (or Web Worker
`postMessage` on web). `type` discriminates; unknown types/attributes must be
ignored. Lifecycle: bot `info` → frontend `rules` → bot `ready` → frontend
`start` → (`suggest` → `suggestion` → `play` → `new_piece`)* → `stop` → next
game → `quit` (`0000-mvp.md:14-42`). `[VERIFIED]`

**Frontend → Bot**

| `type` | Fields | Meaning |
|---|---|---|
| `rules` | (MVP: **empty object**, plus optional `randomizer` from 0001) | Bot must reply `ready` or `error` |
| `start` | `hold` (piece or `null`), `queue` (list of pieces), `combo` (int), `back_to_back` (bool), `board` (40 × 10 cells), optional `randomizer` object | Full position; must precede `suggest` (`0000-mvp.md:57-72`) |
| `suggest` | none | Ask for a move |
| `play` | `move` (the move object that was actually played) | Host confirms advance; hold inferred from piece type |
| `new_piece` | `piece` | New piece appended to queue |
| `stop` | none | Stop calculating |
| `quit` | none | Exit |

**Bot → Frontend**

| `type` | Fields |
|---|---|
| `info` | `name`, `version`, `author`, `features` (list) — must be first message |
| `ready` | none |
| `suggestion` | `moves`: list of moves, best first; optional `move_info` |
| `error` | `reason` (`unsupported_rules`) |

**Move object** (`0000-mvp.md:141-172`; confirmed by `tbp` 3.0.0
`src/data.rs`):

```json
{
  "location": {"type": "T", "orientation": "north", "x": 4, "y": 19},
  "spin": "none"
}
```

- `location.type`: `"I" | "O" | "T" | "L" | "J" | "S" | "Z"`.
- `location.orientation`: `"north" | "east" | "south" | "west"` (spawn =
  north; cw = east). Serde uses `snake_case`, so lower-case JSON.
- `location.x`: **centre** of the piece, 0 = leftmost column.
- `location.y`: **centre** of the piece, 0 = **bottommost row** (y grows upward).
- Centres are **SRS true-rotation** centres: L/J/T/S/Z centre = stationary
  point of basic rotation; O centre = bottom-left mino (north) / top-left
  (east) / top-right (south) / bottom-right (west); I centre = middle-left mino
  (north) / middle-top (east) / middle-right (south) / middle-bottom (west).
- `spin`: `"none" | "mini" | "full"` — the bot *claims* the spin; the host is
  expected to validate.
- Hold decision is **implicit**: `location.type` equal to the hold piece means
  "use hold"; otherwise the current piece. There is no explicit `hold` boolean.
  If the next piece and the hold piece are the same type, the inference is
  ambiguous; battletris resolves it by preferring the next piece
  (`game.rs:130-148`). `[VERIFIED]` implementation, ambiguity `[INFERRED]` for
  other hosts.

**`board` representation** (`0000-mvp.md:57-72`): "a list of 40 lists of 10
board cells"; each cell is `null` (empty), a piece letter (`"I"…"Z"`), or
**`"G"` for garbage**. So garbage cells are represented but **not** as a
garbage packet/queue, only as settled blocks.

> **Row order is not stated in the spec text.** `[UNKNOWN]` in the spec;
> battletris serialises **index 0 = bottom row** (`src/battle/game/data.rs`,
> `Board::to_tbp`), and the `y = 0` bottommost convention is consistent with
> that `[INFERRED]`. Verify against the exact bot implementation before
> trusting it.

**Extensions present in the repo**

- `0001-randomizer.md`: adds `rules.randomizer` ∈ `"uniform" | "seven_bag" |
  "general_bag" | "unknown"`, and `start.randomizer` =
  `{"type": "seven_bag", "bag_state": ["S","L","T"]}` or
  `{"type": "general_bag", "current_bag": {...}, "filled_bag": {...}}`
  (per-piece counts), or `{"type": "uniform"}`. `[VERIFIED]` fields; note the
  spec's `general_bag` example omits the `type` key even though the prose says it
  must be present — a real spec inconsistency to allow for.
- `0003-move_info.md`: adds `suggestion.move_info` =
  `{"nodes": number, "nps": number, "depth": number, "extra": string}` (all
  optional). `[VERIFIED]`

### 3.4 What the protocol does **not** carry (relevant to versus/S2)

`[VERIFIED]` by absence from `0000-mvp.md`/`0001`/`0003` and from `tbp` 3.0.0
`Start` struct:

- **No incoming/pending garbage field at all.** Bots only see garbage after it
  has been inserted into `board` as `"G"`. There is no queue, no "incoming N
  lines", no activation timer.
- **No B2B count/charge** — only `back_to_back: bool`.
- **No Surge** state, no attack table, no line-clear event, no attack value.
- **No combo multiplier** — only the integer `combo`.
- **No hold-availability flag** (`hold` is the piece or `null`; whether hold was
  just used is not communicated).
- **No spin classification beyond the bot's own claim** (`none/mini/full`), no
  All-Mini/All-Mini+ semantics, no kick/180 information.
- **No rules parameters** beyond `randomizer` (no board height, no garbage
  delay/cap, no SRS/SRS+ selector, no 180 on/off).
- **No timing/gravity/DAS** model; pacing is entirely host-defined.
- `rules` in the MVP is literally described as "currently empty" with loose
  guideline defaults (`0000-mvp.md:46-55`).

### 3.5 Role

**Protocol/docs only.** Explicitly not an engine: no simulation, no rules
implementation, no executable. It is an *interface contract* for bot↔host
communication.

### 3.6 Integration options

| Option | Detail |
|---|---|
| Protocol (stdio JSON lines) | Implement a **TBP frontend/host** in Python: spawn bot processes, send `rules`/`start`/`suggest`/`play`/`new_piece`/`stop`/`quit`, read `info`/`ready`/`suggestion`/`error`. Use it to benchmark external TBP bots (Cold Clear, etc.) or to expose our policy as a TBP bot. `[VERIFIED]` schema |
| Fields to send | `start`: `hold`, `queue`, `combo`, `back_to_back`, `board[40][10]` (bottom-first `[INFERRED]`), optional `randomizer`; `suggest` empty; `play.move`; `new_piece.piece` |
| Fields to read | `suggestion.moves[].location.{type,orientation,x,y}`, `.spin`; `info.{name,version,author,features}` |
| Host obligations | Validate `location` (bounds/collision/reachability), apply hold inference, maintain queue and timing; the spec does not prescribe legality checks |

**Integration complexity: LOW** for consuming/emitting the schema (it is small
and stable), **MEDIUM** for a correct host (movegen + hold inference + timing +
board orientation). The protocol itself adds no engine logic.

### 3.7 Licence risk / safe mode

No licence → **do not copy the spec text into our repo**. Implement the message
schema from our own description; link to the upstream repo. Prefer the MIT/
Apache-2.0 `tbp` crate if a Rust component is ever needed.

---

## 4. `battletris`

Repo: <https://github.com/tetris-bot-protocol/battletris> · tree HEAD
`a9273ca71c4e341b4e2bc3dca111d8b943dbcf0b` · last commit `2022-01-13T06:26:39Z`.
Whole repo is **8 files**: `.gitignore`, `Cargo.toml`, `Cargo.lock`,
`src/main.rs`, `src/battle.rs`, `src/battle/game.rs`, `src/battle/game/data.rs`,
`src/bot.rs`. No README, no LICENSE, no CI. `[VERIFIED]`

### 4.1 What it is

A **headless Rust match host/referee for two TBP bots**. It launches the two bot
executables, speaks TBP over their stdin/stdout, simulates both boards, resolves
garbage/cancellation, and prints match scores with Wilson/Elo intervals or SPRT
(`src/main.rs:1-160`). It is **not** a visualiser (no rendering or graphics
dependency), **not** an engine with built-in AI, and **not** a library.

### 4.2 Licence — **none / all rights reserved**

No `LICENSE` in tree (`raw .../LICENSE` → 404), no licence field in
`Cargo.toml`, no README statement. Default copyright: **cannot copy, vendor,
link, or redistribute**. Dependencies are permissive (see below), but that does
not license battletris itself. `[VERIFIED]` absence; legal effect `[INFERRED]`.
Of the dependencies only `tbp`'s licence was verified (MIT OR Apache-2.0); the
rest are assumed permissive but were not individually audited.

### 4.3 Language, build, dependencies, GPU, Linux

| Item | Finding |
|---|---|
| Language | Rust, edition 2021 (`Cargo.toml:1-3`) `[VERIFIED]` |
| Build | `cargo build` (binary `battletris`); no build.rs, no native deps `[VERIFIED]` manifest |
| Dependencies | `anyhow 1.0.52`, `serde_json 1.0.74`, `structopt 0.3.25`, `wait-timeout 0.2.0`, `rand 0.8.4`, `serde 1.0.133`, `tbp 3.0.0`, `crossbeam-utils 0.8.6` (`Cargo.toml:8-17`); `tbp 3.0.0` locked in `Cargo.lock:346-349` and is **MIT OR Apache-2.0** on crates.io `[VERIFIED]` |
| Linux build | **Yes** — pure Rust/std, no GUI, no native libs `[INFERRED]` (not built) |
| GPU | **None** `[VERIFIED]` by dependency list |

### 4.4 Entry point and headless operation

```
battletris <bot_a> <bot_b> [-q/--quiet] [-f/--format <count|ftN|sprt[elo0,elo1]>]
            [-p/--parallelism N] [-c/--config <name|name@Nms|json>]
```

- `main.rs:20-33` (structopt options), `main.rs:164-230` (`run`),
  `main.rs:232-263` (`battle_thread`, spawns bots), `bot.rs:39-98`
  (pipe setup, `info` handshake).
- **Headless: yes.** It only reads/writes pipes and prints text; no display
  needed. `[VERIFIED]`
- Default bot handshake: launch → expect `info` → send `rules` with
  `randomizer = SevenBag` → expect `ready` (`main.rs:265-280`).
- Match formats: `N` games, `FTn`, `SPRT[a,b]`; Wilson score → Elo
  (`main.rs:54-160`); parallelism via `crossbeam_utils::thread::scope`
  (`main.rs:186`).
- Per-move timeout: if `(current - requested) * time_quanta_ms > 500`, the
  bot forfeits (`battle.rs:129`). `[VERIFIED]`

### 4.5 Implemented mechanics (from source)

| Mechanic | Behaviour | Evidence |
|---|---|---|
| Board | **Hardcoded 10 × 40** (`[[CellColor;10];40]`); index 0 = bottom row (gravity/compaction and `is_pc` assume it) | `data.rs:36-41`, `data.rs:173-221` `[VERIFIED]` |
| 7-bag | `BAG` of 7, drawn by random `swap_remove` until empty, then refilled; sends `SevenBag` randomizer state with the remainder | `game.rs:43-70`, `game.rs:476-483` `[VERIFIED]` |
| Rotation | 4 orientations, cw/ccw only. Kick candidates are encoded as 5 per-state offsets; from the `(0,0)`-implied first test the result matches **Guideline SRS** (JLSTZ order and I order), expressed in TBP's I/O centre convention | `data.rs:242-270`, `game.rs:283-330` `[VERIFIED]` tables; `[INFERRED]` SRS identification |
| 180 | **No 180 input/table.** South/west are reached by two 90° rotations in the search graph; kick path is not the TETR.IO 180 path | `game.rs:283-330` `[VERIFIED]` |
| Spin detection | **T-piece only**, 3-corner style: count mini-front corners vs normal corners; fewer than 2 mini corners **and** kick index ≠ 4 → `Mini`, else `Full`; `< 3` corners → `None`. No All-Spin/All-Mini/All-Mini+ | `game.rs:380-410` `[VERIFIED]` |
| Hold | Yes, with one-slot hold and swap/pop logic; hold inferred from suggested piece | `game.rs:150-160` `[VERIFIED]` |
| Garbage queue | `VecDeque<Garbage>{amount, add_time}` per player; attack scheduled with `delays.garbage` (30 quanta ≈ 480 ms in `ppt`); arbitrary amounts, **no cap, no rise speed** | `game.rs:20-30`, `battle.rs:170-180`, `battle.rs:289-314` `[VERIFIED]` |
| Cancellation | `counter_garbage` consumes the front of the incoming queue with outgoing attack before sending the remainder | `game.rs:72-84`, `battle.rs:170-180` `[VERIFIED]` |
| Garbage insertion | Adds full garbage rows with a single hole, `change_on_attack` and per-line `messiness` (0.3); hole RNG bug: `gen_range(0..9)` excludes column 9 except via the collision fallback | `game.rs:89-112` `[VERIFIED]` |
| Combo | Additive table `[0,0,1,1,2,2,3,3,4,4,4,5]`, indexed by combo before increment | `battle.rs:41`, `game.rs:160-185` `[VERIFIED]` |
| B2B | Flat `+1` when previous clear was "hard" and current is hard; no charging, no surge | `battle.rs:38`, `game.rs:166-183` `[VERIFIED]` |
| Attack table | Config `"ppt"`: clear `[0,1,2,4]`, mini `[0,1,2]`, spin `[2,4,6]`, B2B `1`, all-clear `10` (replaces attack; `pc_additive=false`), combo table above, messiness 0.3, countering on, blocking off | `battle.rs:289-314` `[VERIFIED]` |
| Top-out | Bot suggestion failure (no legal move / timeout / crash) ⇒ opponent wins; board never actually "tops out" through a checked spawn rule | `battle.rs:121-165` `[VERIFIED]` |
| Season 2 | **Absent.** Puyo Puyo Tetris-style attack/garbage, not TETR.IO S2 | no S2 state in the files read `[VERIFIED]` |

Determinism: **none.** All randomness uses `rand::thread_rng()`
(`game.rs:34,45,91,97,99`), board/scheduling uses wall-clock `Instant`
(`battle.rs:86-97`), and there is no seed CLI flag. Two runs of the same bots
differ. `[VERIFIED]`

### 4.6 SRS+ / 180 compatibility

- **Guideline SRS only** (5-test table, I-piece in normal SRS order, no mirrored
  SRS+ ordering). `[INFERRED]` from `data.rs` tables; no SRS+ identifier exists.
- **No TETR.IO 180 table and no 180 rotation action.** Reaching a "south"
  placement uses two cw rotations, so the kick candidates differ from a true
  180. `[VERIFIED]`
- The bot's `spin` claim is not trusted: the host regenerates legal moves with
  `movegen`/`check_spin` and only accepts a suggestion whose `spin` matches its
  own classification, otherwise it tries the next suggestion
  (`game.rs:114-148,380-410`). There is no all-piece spin support.

### 4.7 Season 2 support — **ABSENT**

| S2 feature | battletris status |
|---|---|
| B2B charging | Absent (flat `+1`) |
| Surge | Absent |
| Season 2 attack table | Absent (PPT config) |
| Garbage speed/cap | Absent (fixed `delays.garbage` timer, arbitrary packet size, single-hole rows) |
| All-Mini+ | Absent (T-only, no immobile all-piece detection) |

### 4.8 Role

**Protocol match host/referee** (an adapter/harness around external bots), not
an engine, not an RL environment, not a visualiser. Its value is as a reference
for how to schedule a two-bot versus match over TBP and how to validate
placements (`movegen` in `game.rs:199-378`).

### 4.9 Integration options

| Option | Detail |
|---|---|
| Subprocess (as referee) | Build the binary, provide two TBP-speaking bot executables; use its score/SPRT output. Requires implementing a TBP bot wrapper around our agent if we want our policy in it. `[VERIFIED]` interface |
| Subprocess (as opponent harness) | It is *not* an opponent; it only plays bots against each other. To use TBP bots as opponents in TetrisRL we would implement our own TBP host (see §3.6), not depend on battletris |
| Protocol/API | JSON lines to bots, CLI to user; no library API, no replay output, no machine-readable results beyond stdout `"W - L"` |
| Linking/copying | **No** — unlicensed, and non-deterministic |

**Integration complexity: MEDIUM** to build/run as an external referee;
**HIGH** to use as an RL environment (no seeding, wall-clock timing, PPT rules,
process-per-move protocol overhead, no observation of incoming garbage).

### 4.10 Licence risk / safe mode

No licence → do not vendor or redistribute. Safe mode at most:
run an unmodified separately-built binary for one-off cross-checks. Because
there is no licence grant, even that should be confirmed with the authors if the
results are published as a reproducible artifact.

---

## 5. Compatibility matrix

Legend: ✅ implemented / ⚠️ approximate or partial / ❌ absent / — not applicable.
Confidence tags apply to the cell.

| Feature | NullpoMino | tbp-spec | battletris |
|---|---|---|---|
| 10 × 40 board | ❌ 10×20 + 3 hidden `[VERIFIED]` | ⚠️ defaults "10x40" in prose only `[VERIFIED]` | ✅ 10×40 hardcoded `[VERIFIED]` |
| 7-bag | ✅ (bag variants; Standard = BagNoSZO) `[VERIFIED]` | ⚠️ extension only (`seven_bag` state) `[VERIFIED]` | ✅ `[VERIFIED]` |
| Guideline SRS | ✅ JLSTZ; ⚠️ I CCW truncated `[VERIFIED]` | — prose default only, no implementation `[VERIFIED]` | ✅/⚠️ 5-test SRS `[INFERRED]` |
| **TETR.IO SRS+ (I ordering)** | ❌ `[VERIFIED]` | ❌ `[VERIFIED]` | ❌ `[VERIFIED]` |
| 180° rotation action | ✅ `[VERIFIED]` | ❌ no field/action `[VERIFIED]` | ❌ `[VERIFIED]` |
| **TETR.IO 180 kick table** | ❌ (own 11/5-offset table) `[VERIFIED]` | ❌ no field `[VERIFIED]` | ❌ no table `[VERIFIED]` |
| Spin detection | ⚠️ T-only 3-corner + mini + immobile/EZ `[VERIFIED]` | ⚠️ bot-claimed `none/mini/full` only `[VERIFIED]` | ⚠️ T-only 3-corner `[VERIFIED]` |
| **All-Mini+** | ❌ `[VERIFIED]` | ❌ `[VERIFIED]` | ❌ `[VERIFIED]` |
| Hold | ✅ `[VERIFIED]` | ✅ `hold` field, implicit hold move `[VERIFIED]` | ✅ `[VERIFIED]` |
| Garbage queue | ✅ `[VERIFIED]` | ❌ only settled `"G"` cells `[VERIFIED]` | ✅ `[VERIFIED]` |
| Garbage cancellation | ✅ countering `[VERIFIED]` | ❌ no protocol notion `[VERIFIED]` | ✅ `[VERIFIED]` |
| Garbage speed / cap | ❌ instant on lock `[VERIFIED]` | ❌ not expressible `[VERIFIED]` | ❌ fixed timer, no cap `[VERIFIED]` |
| Combo | ✅ additive table `[VERIFIED]` | ⚠️ `combo` int only `[VERIFIED]` | ✅ additive table `[VERIFIED]` |
| **B2B charging** | ❌ flat +1 `[VERIFIED]` | ❌ bool only `[VERIFIED]` | ❌ flat +1 `[VERIFIED]` |
| **Surge** | ❌ `[VERIFIED]` | ❌ `[VERIFIED]` | ❌ `[VERIFIED]` |
| **S2 attack table** | ❌ classic VS table `[VERIFIED]` | ❌ none `[VERIFIED]` | ❌ PPT table `[VERIFIED]` |
| Headless simulation | ❌ general use; only a RanksAI-specific fictitious tester `[VERIFIED]` | — no code `[VERIFIED]` | ✅ CLI `[VERIFIED]` |
| Placement-suggestion API | ❌ controller-driven AIs `[VERIFIED]` | ✅ `suggestion.moves` `[VERIFIED]` | ⚠️ consumes suggestions, does not produce `[VERIFIED]` |
| RL environment | ❌ `[VERIFIED]` | ❌ `[VERIFIED]` | ❌ `[VERIFIED]` |
| Licence | ⚠️ BSD-3 + non-OSI/unlicensed files `[VERIFIED]` | ❌ none `[VERIFIED]` | ❌ none `[VERIFIED]` |

### 5.1 Season 2 support summary

| S2 feature | NullpoMino | tbp-spec | battletris |
|---|---|---|---|
| B2B charging | absent | absent (bool only) | absent |
| Surge | absent | absent | absent |
| Season 2 attack table | absent | absent | absent |
| Garbage speed/cap | absent | absent | absent |
| All-Mini+ | absent | absent | absent |
| **Overall** | **absent** | **not expressible** | **absent** |

---

## 6. What this means for TetrisRL

**None of the three repos can be the Season 2 engine, and none can be an RL
environment.** Two of them (NullpoMino, battletris) are real simulations, but
both implement pre-S2 versus rules: flat B2B, additive combos, no Surge, no
charging, no All-Mini+, garbage that lands on a timer or on the next lock rather
than a TETR.IO-style queue with speed/cap. tbp-spec is a message schema, not an
engine at all. The authoritative S2 ruleset for this project therefore remains
`docs/RULESET.md`, implemented in `tetrisrl/environment/`; these repos can only
be *cross-checks* and *interop surfaces*.

**NullpoMino is the best behavioural reference, but a bad dependency.** It is
the only audited repo with a complete playable engine: SRS, 180 support, spin
detection, hold, garbage cancellation, and in-engine AIs of several kinds
(PoochyBot heuristic search, RanksAI table-based, TSpinAI heuristic, BasicAI).
It is also BSD-3-Clause on its core files, which is permissive. But the licence is not uniform (non-OSI `RC4.java`, unlicensed
`net/omegaboshi` and `net/tetrisconcept` files, LGPL natives, non-free assets),
the engine is GUI-coupled, the board is 10×20+3, and its SRS is Guideline (I-CCW
even truncated) with a *non-TETR.IO* 180 table. Use it to sanity-check the
*semantics* of rotations, spins, hold and VS garbage; do not copy code, do not
link it, and do not treat its kick tables as TETR.IO parity. If we need a
one-off differential test, run it as an unmodified separate process; even that is
high effort for low payoff.

**The TBP protocol is the one genuinely reusable asset here.** It gives a small,
stable JSON-lines contract (`start`, `suggest`, `suggestion`, `play`,
`new_piece`, `rules`, `stop`, `quit`; board with `null`/piece/`"G"` cells;
placement as `location{type, orientation, x, y}` + `spin`) that maps almost
one-to-one onto our placement-based action space. Implementing a TBP
**frontend** in Python would let us benchmark against existing open-source TBP
bots without importing their code, and implementing a TBP **bot wrapper**
around our policy would let external hosts evaluate us. Two caveats must be
documented rather than hidden: (a) TBP has **no incoming-garbage state**, so TBP
opponents cannot play our S2 versus game faithfully — they only see garbage
after it lands; (b) TBP carries only a `back_to_back` bool, no charge/Surge, and
no all-mini classification. A TBP adapter is therefore an *approximate
compatibility mode*, exactly the kind of thing `docs/BENCHMARKS.md` must label.

**battletris is a useful design reference and a poor runtime dependency.** It
shows how to referee two TBP bots headlessly: event-queue scheduling, a
movegen-based legality check for suggested placements, garbage delay and
cancellation, hold inference, 500 ms forfeit. But it is unlicensed, uses
`thread_rng` and wall-clock timing (not reproducible), hardcodes a PPT attack
table, and has no 180/SRS+/S2. It must not be vendored, and its results must not
be presented as TETR.IO S2 evidence.

**Recommended integration posture**

| Target | Mode | Complexity | Rationale |
|---|---|---|---|
| NullpoMino | No integration; optional behavioural reference | HIGH (if ever attempted) | GUI-only, mixed licence, non-TETR.IO tables |
| TBP bots (via spec) | In-repo Python **TBP frontend** adapter + subprocess bots | LOW (client) / MEDIUM (host) | Small stable schema; placement-based; no code copying; must document S2 gaps |
| TetrisRL as TBP bot | Thin TBP **bot wrapper** around `choose_action()` | LOW | Useful for external evaluation; state is our own |
| battletris | Optional external referee for TBP-bot-vs-TBP-bot smoke tests | MEDIUM | Unlicensed; non-deterministic; PPT rules only |

**Licence-safe modes, explicitly:** subprocess/protocol only; no linking, no
vendoring, no copying. NullpoMino code must not be ported (non-OSI + unlicensed
files). TBP spec prose must not be pasted into our docs (no licence) — describe
the schema in our own words and cite the repo. battletris must not be
redistributed (no licence). Reimplementing TETR.IO SRS+/180/Season-2 tables
should be sourced from the project's existing RULESET research (triangle /
cobra-movegen / TetrisWiki), not from any of these three repos.

---

## 7. Sources actually fetched

### NullpoMino

- Tree: `https://api.github.com/repos/nullpomino/nullpomino/git/trees/HEAD?recursive=1`
  (HEAD sha `4de098dd0b48d991247313d8dba30b9721e6f9d9`)
- `https://raw.githubusercontent.com/nullpomino/nullpomino/HEAD/LICENSE`
- `.../HEAD/nullpomino-run/LICENCE.txt`
- `.../HEAD/README.md`, `.../HEAD/readme_en.txt`
- `.../HEAD/nullpomino-parent/pom.xml`, `.../HEAD/nullpomino-core/pom.xml`,
  `.../HEAD/nullpomino-run/pom.xml`
- `.../HEAD/nullpomino-run/config/rule/Standard.rul`
- `.../HEAD/nullpomino-run/config/list/wallkick.lst`
- `.../HEAD/nullpomino-run/lib/libsdljava.so` (inspected with `file`, not run)
- `.../HEAD/nullpomino-run/scripts/play_swing`, `.../play_slick`, `.../netserver`,
  `.../airankstool`
- `.../HEAD/nullpomino-run/doc/airanks_readme_en.txt`
- `.../HEAD/nullpomino-core/src/main/java/mu/nu/nullpo/game/subsystem/wallkick/StandardWallkick.java`
- `.../mu/nu/nullpo/game/subsystem/wallkick/BaseStandardWallkick.java`
- `.../mu/nu/nullpo/game/component/Field.java`, `.../game/component/Piece.java`
- `.../mu/nu/nullpo/game/component/RuleOptions.java`
- `.../mu/nu/nullpo/game/play/GameEngine.java`
- `.../mu/nu/nullpo/game/subsystem/mode/VSBattleMode.java`
- `.../mu/nu/nullpo/game/subsystem/ai/AIPlayer.java`, `BasicAI.java`
- `.../mu/nu/nullpo/tool/airankstool/AIRanksTester.java`
- `.../net/tetrisconcept/poochy/nullpomino/ai/PoochyBot.java`,
  `.../PoochyBot Readme.txt`, `ComboRaceBot.java`
- `.../net/omegaboshi/nullpomino/game/subsystem/randomizer/BagRandomizer.java`,
  `Randomizer.java`, `BagNoSZORandomizer.java`
- `.../net/clarenceho/crypto/RC4.java`
- `.../biz/source_code/base64Coder/Base64Coder.java`,
  `.../com/centerkey/utils/BareBonesBrowserLaunch.java`,
  `.../org/cacas/java/gnu/tools/Crypt.java`
- Activity: `https://github.com/nullpomino/nullpomino/commits/HEAD.atom`

### tbp-spec

- Tree: `https://api.github.com/repos/tetris-bot-protocol/tbp-spec/git/trees/HEAD?recursive=1`
  (HEAD `31a589f4d1b53e4ce24c9fcc052865407d849457`)
- `https://raw.githubusercontent.com/tetris-bot-protocol/tbp-spec/HEAD/README.md`
- `.../HEAD/text/0000-mvp.md`, `.../0001-randomizer.md`, `.../0003-move_info.md`
- `.../HEAD/LICENSE` and `.../LICENSE.md` → **404**
- `https://github.com/tetris-bot-protocol/tbp-spec/commits/HEAD.atom`
- `tbp` crate 3.0.0: `https://crates.io/api/v1/crates/tbp`,
  `https://crates.io/api/v1/crates/tbp/3.0.0/download` (source: `src/data.rs`,
  `src/frontend_msg.rs`, `src/bot_msg.rs`)
- `https://raw.githubusercontent.com/tetris-bot-protocol/tbp-rs/HEAD/README.md`,
  `.../Cargo.toml`; `.../LICENSE` → 404

### battletris

- Tree: `https://api.github.com/repos/tetris-bot-protocol/battletris/git/trees/HEAD?recursive=1`
  (HEAD `a9273ca71c4e341b4e2bc3dca111d8b943dbcf0b`)
- `https://raw.githubusercontent.com/tetris-bot-protocol/battletris/HEAD/Cargo.toml`
- `.../HEAD/Cargo.lock`
- `.../HEAD/src/main.rs`
- `.../HEAD/src/battle.rs`
- `.../HEAD/src/battle/game.rs`
- `.../HEAD/src/battle/game/data.rs`
- `.../HEAD/src/bot.rs`
- `.../HEAD/LICENSE` and `.../HEAD/README.md` → **404**
- `https://github.com/tetris-bot-protocol/battletris/commits/HEAD.atom`

### SRS+ / Season 2 comparison sources (external)

- `https://tetris.wiki/TETR.IO` (TetrisWiki: 10×40, SRS+ default, B2B Charging
  Beta 1.0.0, Surge start 1/4 lines, All-Mini+ Beta 1.5.0, 180 kicks custom)
- `https://raw.githubusercontent.com/halp1/triangle/main/src/engine/utils/kicks/data.ts`
  (`"SRS+"` block, `i_kicks`, `oo_kicks`)
- `https://raw.githubusercontent.com/Kixenon/cobra-movegen/main/src/gen.hpp`
  (`kicks180`, `I SRS+`)

### Failed / limited

- `https://api.github.com/repos/{owner}/{repo}` for all three repos → **HTTP 403
  rate limit** (60/h exhausted). Stars/releases/archived/licence API fields:
  `[UNKNOWN]`.
- No clone, no build, no execution of any repo.

---

## 8. Open questions (`[UNKNOWN]`)

1. Full NullpoMino per-file licence inventory (only ~12 files sampled; more
   non-OSI or unlicensed files may exist).
2. TBP `board` row ordering: spec text does not state it; battletris sends
   bottom-first, but this should be confirmed against the specific bot
   implementation before integration.
3. Whether `tbp-spec`'s open PR (1 open pull request shown on GitHub) adds
   garbage/versus fields; API rate limit prevented inspection.
4. Whether any TBP bot in the wild implements 180/SRS+ internally; TBP has no
   field to negotiate it.
5. Why NullpoMino's I-CCW rows carry only 3 post-basic offsets (and whether the
   sign handling of the left-rotation table matches Guideline SRS exactly) —
   needs execution, which was out of scope.
