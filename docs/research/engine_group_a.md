# Engine Group A — source-level audit

Scope: three candidate engines/opponents for TetrisRL (TETR.IO Season 2, SRS+, 10×40 board).
Method: read-only inspection of repository trees via the GitHub API, then `raw.githubusercontent.com`
for README/LICENSE/Cargo/`src` files. **Nothing was cloned, built, installed, or run.** Any statement
about "builds on Linux" is therefore an inference from manifests, not an observed build.

Confidence labels used below:

- **[VERIFIED]** — I read the source (or the licence text) and the claim is what the code says.
- **[INFERRED]** — derived from README/metadata/manifest only.
- **[UNKNOWN]** — not determinable from what I could fetch (fetch failure, missing file, or the fact is
  only present in an image/diagram).

## Verification limits (read this before trusting a row)

1. **GitHub API rate limit was hit mid-audit.** The metadata call for
   `api.github.com/repos/MinusKelvin/cold-clear` returned **HTTP 403 "API rate limit exceeded"**.
   Consequences: star counts, `archived` flags and exact repo creation dates for Cold Clear 1 and 2 are
   **[UNKNOWN]**. I substituted commit Atom feeds (`/commits/<branch>.atom`), which do work unauthenticated,
   for activity dates.
2. `https://tetrio.wiki.gg/wiki/SRS%2B` returns **HTTP 404** (no such page); the SRS+/180/B2B/Season 2 content
   lives on `https://tetrio.wiki.gg/wiki/Mechanics`, which I fetched both rendered and as `?action=raw`.
3. The TETR.IO **180 kick table is published only as an image** on that wiki page. I can verify the
   *structure* of each implementation's 180 table, but **not** byte-equality with TETR.IO's table →
   those rows are marked **[UNKNOWN]**.
4. `web_search` is unusable (HTTP 401 per the task brief), so no search-based corroboration was attempted.
5. No repository was executed, so runtime behaviour (throughput, actual piece sequences, whether the code
   even compiles on today's rustc) is not observed.

## Compatibility summary

| | nyctivoe/tetris-engine-in-rust | MinusKelvin/cold-clear-2 | MinusKelvin/cold-clear |
|---|---|---|---|
| Licence | **none present** (all rights reserved) | **MIT OR Apache-2.0** | **MPL-2.0** |
| Language / build | Rust 2024, Cargo + maturin | Rust 2021, Cargo | Rust workspace (11 crates), Cargo |
| Board | 10×40 (20 visible + 20 hidden) [VERIFIED] | 10×40 bitboards, no hidden-row concept [VERIFIED] | 10×40 (rows 0–19 visible) [VERIFIED] |
| 7-bag | yes, seeded [VERIFIED] | bag state supplied by frontend [VERIFIED] | yes, in `libtetris` [VERIFIED] |
| Guideline SRS kicks | yes [VERIFIED] | yes [VERIFIED] | yes [VERIFIED] |
| **SRS+ I-kick ordering** | **no — guideline table** [VERIFIED] | **no — guideline table** [VERIFIED] | **no — guideline table** [VERIFIED] |
| 180 rotations | yes, own 5-test table [VERIFIED]; TETR.IO equality **[UNKNOWN]** | **no** [VERIFIED] | **no** [VERIFIED] |
| T-spin mini/full | yes (3-corner + front corners + kick-4) [VERIFIED] | yes in movegen (3-corner + kick-5) [VERIFIED] | yes (3-corner + kick-5) [VERIFIED] |
| All-spin / All-Mini / All-Mini+ | all-spin for JLSTZ+I, always "mini"; T immobile fallback [VERIFIED] | none (T only) [VERIFIED] | none (T only) [VERIFIED] |
| Hold | yes [VERIFIED] | as a "reserve" piece, not a hold action [VERIFIED] | yes [VERIFIED] |
| Garbage queue + cancel | yes, timers + FIFO cancel [VERIFIED] | **none** [VERIFIED] | yes (battle crate + C API `incoming` count) [VERIFIED] |
| Combo | TETR.IO multiplier `base*(1+0.25x)` / `ln(1+1.25x)` [VERIFIED] | counter from frontend only [VERIFIED] | additive `COMBO_GARBAGE` table [VERIFIED] |
| B2B | chaining ladder **and** surge charging, mixed [VERIFIED] | single bool from frontend [VERIFIED] | single bool, +1 line (chaining) [VERIFIED] |
| Season 2 (B2B charging, Surge, All-Mini+, opener, clutch) | partial/hybrid [VERIFIED] | absent [VERIFIED] | absent [VERIFIED] |
| Headless | yes (library) [VERIFIED] | yes (stdin/stdout) [VERIFIED] | yes (C API / TBP) [VERIFIED] |
| C ABI | no | no | **yes**, `c-api/coldclear.h` |
| TBP JSON lines | no | yes | yes |
| Python | **yes** (PyO3 `tetrisEngine_rs`) | no | no |
| Best role | RL environment (after licence question is resolved) | opponent / placement oracle | opponent + reference versus sim |
| Integration cost | MEDIUM | LOW–MEDIUM | MEDIUM |
| Last commit | 2026-08-31 | 2022-06-29 | 2022-01-18 |

---

## 1. `nyctivoe/tetris-engine-in-rust`

URL: <https://github.com/nyctivoe/tetris-engine-in-rust>

### Snapshot

- Rust library + PyO3 extension; 12 `src/*.rs` modules (~180 KB of Rust, `engine.rs` alone is 73 KB).
  Single author, 14 commits between
  2026-04-07 and 2026-08-31, 2 stars, 0 forks, `archived: false` [VERIFIED: API metadata + commit Atom].
- README claims: *"replicates the Tetr.io game engine, including SRS+, all spin, combo, b2b charging,
  attack calculation"*; defaults `spin_mode = all_spin`, `b2b_mode = surge`, flat `[i8; 400]` board,
  module name `tetrisEngine_rs`.

### Licence — **no licence at all** [VERIFIED]

- The recursive tree lists `.gitignore`, `Cargo.lock`, `Cargo.toml`, `README.md`, `pyproject.toml`,
  `src/*` — **no `LICENSE`, `COPYING`, or `LICENCE` file**.
- `api.github.com/repos/nyctivoe/tetris-engine-in-rust` returns `"license": null`.
- `pyproject.toml` has no `license` field; `Cargo.toml` has no `license` key either.
- Under default copyright law this is **all rights reserved**: no grant to copy, modify, link or
  redistribute. It is **not OSI-approved** because there is no licence. This is the single most
  important finding in this report.

### Stack, build, dependencies, GPU

- `Cargo.toml`: `name = "tetrisEngine"`, `edition = "2024"`, `crate-type = ["rlib", "cdylib"]`,
  deps `rand 0.8`, `serde 1`, `serde_json 1`, optional `pyo3 0.22.6` (`abi3-py310`, `extension-module`)
  [VERIFIED].
- `pyproject.toml`: `maturin>=1.7,<2`, `bindings = "pyo3"`, `module-name = "tetrisEngine_rs"`,
  `requires-python = "==3.13.12"` [VERIFIED]. Note the odd combination: `abi3-py310` in the crate but an
  exact patch-version pin in the wheel metadata — any interpreter except 3.13.12 will refuse the wheel.
- Builds on Linux: **[INFERRED] yes** (pure Rust, no platform crates, no GUI, no FFI beyond PyO3).
  Edition 2024 requires rustc ≥ 1.85. I did not build it.
- GPU: **no** [VERIFIED: dependency list contains no CUDA/torch/build-time GPU code].

### Implemented mechanics (from source)

- Board: `BOARD_WIDTH = 10`, `BOARD_HEIGHT = 40`, `VISIBLE_HEIGHT = 20`, `HIDDEN_ROWS = 20`,
  `SPAWN_X = 3`, `SPAWN_Y = 18`, `GARBAGE_ID = -1`, row-major `[i8; 400]` with `y` increasing
  downward (`src/constants.rs`, `src/board.rs::board_index`) [VERIFIED].
- 7-bag: `TetrisEngine::generate_bag()` builds `[1..=7]` and `shuffle`s it, keeping >14 entries buffered;
  `EngineRng` wraps `rand::rngs::StdRng` seeded via `seed_from_u64` → deterministic per seed
  (`src/rng.rs`, `src/engine.rs`) [VERIFIED].
- Hold: `hold_current()` with `hold_locked` one-hold-per-piece flag [VERIFIED].
- Gravity / lock delay: **not in the Rust core**. They exist only in the Python wrapper
  `PyTetrisEngine::tick_runtime(dt_ms, gravity_ms, lock_delay_ms)` (`src/python.rs`), which resets the
  lock timer on *every* successful move/rotate with **no 15-move reset cap** [VERIFIED]. TETR.IO's
  lock-delay reset behaviour is therefore approximated, not matched.
- Placement API: `apply_placement(PlacementPayload { x, y, rotation, last_was_rot, last_rot_dir, last_kick_idx })`
  and `execute_placement(...)` accept absolute coordinates **without reachability checks** [VERIFIED] —
  fine for RL placement actions, but it means the engine will accept teleports unless you enumerate
  moves yourself (there is a BFS for that, see below).
- Spin detection (`src/engine.rs::detect_spin`, `detect_t_spin`, `detect_all_spin`,
  `occupied_3x3_corners`, `count_t_front_corners`) [VERIFIED]:
  - T: ≥3 of the 4 3×3 corners occupied ⇒ spin; classified **full** if the rotation was 180°, or
    `last_kick_index == 4` (the fifth test), or both "front" corners are filled; otherwise **mini**.
    If <3 corners but the piece is immobile, it is still reported as a mini T-spin.
  - Non-T (J, L, S, Z, I) under `SpinMode::AllSpin`: only if `is_piece_immobile()`, and then **always
    `is_mini: true`** (`"J-Spin Mini"` etc.).
- Combo: `combo_attack_down()` = `floor(base*(1+0.25*combo))` when `base > 0`, else
  `floor(ln(1+1.25*combo))` for `combo ≥ 2` (`src/scoring.rs`) [VERIFIED]. This matches the TETR.IO
  Multiplier combo formula documented on the wiki (including DOWN rounding).
- B2B: `B2BMode::{Surge, Chaining}`; `b2b_bonus_for_chain()` implements the **B2B-chaining ladder**
  (1,2,3,…,8 extra lines) and is applied in *both* modes, while `B2BMode::Surge` additionally maintains
  `surge_charge` and releases it on a B2B break (`src/scoring.rs::update_b2b_state`) [VERIFIED].
- Attack table (`base_attack_for_clear`): single 0, double 1, triple 2, quad 4, T-spin single 2,
  T-spin double 4, T-spin triple 6, mini single 0, mini double 1, perfect clear 5 [VERIFIED].
  Whether these are the current Season 2 values: **[UNKNOWN]** (the wiki mechanics page does not tabulate
  them; Cold Clear 1, a 2021-era TETR.IO bot, used perfect clear = 10 — see §3).
- Garbage (`src/garbage.rs`): `GarbageBatch { lines, timer, col }` queue; `cancel_garbage()` consumes
  FIFO; `resolve_outgoing_attack()` returns `{canceled, sent}`; `apply_garbage()` shifts the board up,
  fills whole rows with `GARBAGE_ID` and clears one hole column, tops out when blocks are pushed off the
  top. Hole column is chosen to **avoid the previous column** (`next_garbage_hole_column`). There is
  **no messiness/split-hole option, no per-attack cap, no garbage-clear accounting** (`garbage_cleared`
  and `immediate_garbage` are hard-coded to 0) and **no Garbage Special Bonus** [VERIFIED].
- Opener Phase: parameter exists but is explicitly discarded — `resolve_outgoing_attack()` does
  `let _ = opener_phase;` and always reports `used_opener_multiplier: false` [VERIFIED → **absent**].
- Clutch: `find_clutch_spawn()` walks upward from the spawn row when blocked, and `end_phase()` reports
  `clutch_clear` [VERIFIED]. This is structurally the Beta 1.5.0 "clutch clear" behaviour.
- Surge segmentation: `surge_segments(total)` = `[ceil(t/3), ceil((t-1)/3), floor(t/3)]`, i.e. the first
  two segments carry the remainder [VERIFIED]. The engine returns the vector but does **not** schedule
  the segments over time; a versus loop must do that.

### SRS+ and 180 — explicit verdict

**Guideline SRS only. SRS+ is not implemented, despite the README.** [VERIFIED]

- `src/piece.rs::JLSTZ_OFFSETS` is the guideline JLSTZ offset table verbatim, and
  `src/piece.rs::I_OFFSETS` is the guideline I offset table verbatim.
- `src/rotation.rs::rotation_candidates()` computes kicks as `offsets[old][k] - offsets[new][k]`.
  Its own unit test `rotation_candidates_match_reference_expectations` asserts the I 0→R sequence
  `[(0,0), (-2,0), (+1,0), (-2,-1), (+1,+2)]` — the textbook guideline SRS order.
- TETR.IO's SRS+ is defined as *"a modified version of SRS … in which the I wall kicks are symmetrical
  along the y-axis … the left-side kick tables are mirrored instead of the right side"*
  (<https://tetrio.wiki.gg/wiki/Mechanics>). The sequence above is exactly the asymmetric guideline
  sequence (`-2` then `+1`), so it is **not** SRS+. Any Season 2 replay containing an SRS+-only I kick
  will diverge here.
- 180: **implemented**. `RotationDirection::Half` (`delta() == 2`), tables
  `KICKS_180_NS = [(0,0),(0,1),(1,1),(-1,1),(0,-1)]` and
  `KICKS_180_EW = [(0,0),(1,0),(1,2),(1,1),(0,2)]`, selected by `old_state % 2` and applied for both
  `+2` and `-2` (the direction sign is normalised away by `rotation_delta_from_i8`) [VERIFIED].
  Two deviations to note: (a) the same table is reused for both 180 directions, and (b) the O piece
  takes 180 kicks too (the `O_OFFSETS` short-circuit is skipped when `delta.abs() == 2`), whereas O
  never kicks in TETR.IO. Whether the two tables equal osk's published 180 table: **[UNKNOWN]** —
  the wiki only ships a PNG.

### Season 2 support map

| Season 2 mechanic | Status | Evidence |
|---|---|---|
| B2B charging | **Approximated, but wrong shape** — charges `b2b_display = streak-1` once `streak ≥ 4`, *while still adding the chaining ladder bonus* | `scoring.rs::update_b2b_state` |
| Surge release + 3-segment split | **Present** (released on non-difficult clear; remainder in segments 1–2) but not scheduled over time; base power is `streak-1`, not "4 (1 in Quick Play) + 1 per level" | `scoring.rs::surge_segments`, wiki |
| All-Mini / All-Mini+ | **All-Mini yes** (non-T immobile ⇒ mini); **All-Mini+ partial** (T has an immobile fallback) | `engine.rs::detect_all_spin`, `detect_t_spin` |
| Clutch clear | **Present** (spawn pushed up; `clutch_clear` flag) | `engine.rs::find_clutch_spawn` |
| Opener phase | **Absent** (stub) | `garbage.rs::resolve_outgoing_attack` |
| Garbage speed / cap / messiness | **Partial** (batch timers in ticks; single hole; no messiness, no cap) | `garbage.rs` |
| Garbage special bonus | **Absent** | `scoring.rs` |
| SRS+ | **Absent** | see above |
| 180 | **Present**, table unverified | `rotation.rs`, `piece.rs` |

### Headless / entry points

Headless by construction — there is no renderer, window, or asset dependency. Two surfaces:

- Rust: `tetrisEngine::TetrisEngine` (`new`, `with_seed`, `spawn_next`, `hold_current`,
  `rotate_current`, `execute_placement`, `lock_and_spawn`, `add_incoming_garbage`, `tick_garbage`,
  `bfs_all_placements`, `simulate_lock`, `predict_post_lock_stats`).
- Python: `import tetrisEngine_rs; TetrisEngine(spin_mode="all_spin", b2b_mode="surge", seed=0)` with
  `board_with_active_piece()` → `Vec<Vec<i8>>` (40 rows × 10), `last_clear_stats` → dict,
  `get_queue_snapshot(next_slots=5)`, `tick_runtime(dt_ms, gravity_ms, lock_delay_ms)` [VERIFIED:
  `src/python.rs`].

There is no `main.rs`, no CLI, no server, no TBP.

### Role for TetrisRL

**RL environment candidate — and only that.** It is a rules engine, not a player: it has no evaluation
function, no search policy, and no way to choose a move (BFS enumerates legal placements and their
resulting stats, but nothing ranks them). If the licence were resolved, it is the closest thing in this
group to a drop-in TETR.IO-shaped environment: seeded 7-bag, placement-level `execute_placement`,
`last_clear_stats` for reward/observation, garbage queue with timers and cancellation, and a
`bfs_all_placements(include_180, include_no_place, dedupe_final)` action enumerator.

### Integration surface

| Option | Exact names |
|---|---|
| Rust crate | package `tetrisEngine`, `crate-type = ["rlib","cdylib"]`; `TetrisEngine`, `BfsInputs`, `BfsResult`, `PlacementRecord`, `AttackStats` |
| Python (PyO3) | module `tetrisEngine_rs`; classes `TetrisEngine`, `Piece`; constants `BOARD_WIDTH/HEIGHT`, `HIDDEN_ROWS`, `GARBAGE_ID`, `PIECE_ID_TO_KIND`, `PIECE_ROTATIONS` |
| Action enumeration | `TetrisEngine::bfs_all_placements()` (BFS over left/right/down/rotations, optional 180, dedupe by board+stats) |
| C ABI / TBP | **none** |

### Integration complexity: **MEDIUM**

Technically the shortest path is `maturin develop --release` and calling the PyO3 class from Python; all
of TetrisRL's engine-facing needs (board occupancy, 7-bag, spins, attack, garbage timers, cancellation)
are already exposed as dicts. But you would have to write: (a) your own versus loop and garbage
scheduling on top of `resolve_outgoing_attack`/`surge_segments`, because the engine has no clock and no
opponent; (b) your own lock-delay reset cap and gravity curve, because the only timing helper
(`tick_runtime`) resets indefinitely and lives in the Python layer; (c) an attack-table verification
layer, since the numbers are unverified against Season 2 and PC=5 differs from older references; (d) a
fix or workaround for guideline-vs-SRS+ I kicks and for the O-piece 180 kick, both of which cannot be
patched without editing the source — which the licence forbids. And none of that matters until the
licence problem is solved, which is a legal blocker, not an engineering one.

### Activity / licence risks

- **No licence ⇒ cannot be linked, embedded, vendored, or copied into an MIT project.** Not OSI. No
  archived flag, but it is a 2-star, single-author, four-month-old project (14 commits) — high bus-factor
  risk and no community review of the mechanics claims.
- README overclaims SRS+ (verified false) and "all spin" is narrower than TETR.IO's All-Mini+
  (every non-T spin is forced to mini). Treat documented claims as unverified marketing until tested.
- Exact Python pin `==3.13.12` will bite CI.

### What this means for TetrisRL

This is the most attractive *rules* engine in the group and the most legally dangerous artifact in it.
Its architecture (placement-level `execute_placement`, seeded bag, per-clear `AttackStats`, garbage
timers, BFS action enumeration, clutch clear) is close to what TetrisRL's `environment/` needs, which
makes it tempting to vendor — and that is precisely what must not happen: with no licence, copying even
a helper function into an MIT repository is a copyright problem, and a subprocess wrapper does not cure
it because you would still be redistributing the code. The realistic uses are (1) an external,
never-distributed oracle for *behavioural* comparison while developing our own ruleset (install it
locally, diff outputs, write down the deltas), and (2) a source of design ideas to re-implement
clean-room. If TetrisRL wants a Rust engine, the honest options are to write it ourselves or to build on
Cold Clear's `libtetris` (MPL-2.0, §3), whose tables are at least licensed. Note also that even a
perfect copy would not give us SRS+: the I-kick table here is guideline SRS, so any Season 2 claim built
on this engine would be wrong in exactly the situations the task cares about.

---

## 2. `MinusKelvin/cold-clear-2`

URL: <https://github.com/MinusKelvin/cold-clear-2>

### Snapshot

- "Cold Clear 2 is a modern Tetris versus bot and a complete rewrite and evolution of Cold Clear. It
  implements the Tetris Bot Protocol (TBP) for interaction with a frontend, such as Quadspace."
- Layout: `src/{lib,main,bot,dag,data,map,movegen,sync,tbp,default.json}`, `benches/movegen.rs`,
  `LICENSE-APACHE`, `LICENSE-MIT`. Last commit 2022-06-29 ("improve move generation performance")
  [VERIFIED: commit Atom].

### Licence — **MIT OR Apache-2.0** [VERIFIED]

- README: *"licensed under either Apache License Version 2.0 or MIT License, at your option."*
- `LICENSE-APACHE` and `LICENSE-MIT` are both present in the tree; `Cargo.toml` carries
  `license = "MIT OR Apache-2.0"`.
- I did **not** open the licence bodies (only confirmed presence and the manifest/README declaration).
  Both are OSI-approved and permissive; Apache-2.0 adds an express patent grant and a NOTICE obligation
  on redistribution of modified sources.

### Stack, build, dependencies, GPU

- `Cargo.toml`: `edition = "2021"`, `crate-type = ["rlib","cdylib"]`, deps `ahash 0.7`, `bumpalo-herd`,
  `enum-map 1.1`, `enum_dispatch`, `enumset 1.0`, `futures 0.3`, `nohash`, `once_cell`,
  `ordered-float`, `ouroboros 0.13`, `parking_lot 0.11`, `puffin`, `rand 0.8`, `serde`, `serde_json`,
  `structopt` (non-wasm only); `criterion` in dev [VERIFIED].
- Builds on Linux: **[INFERRED] yes** — pure Rust, stdin/stdout, no OS-specific crate in the dependency
  list, no GUI. Caveat: the pins are from 2021–2022 (e.g. `ouroboros 0.13`, `parking_lot 0.11`); a modern
  rustc/Cargo may need `cargo update` or a pinned toolchain, and `ouroboros` in particular has had
  breakage with newer compilers. Not built.
- GPU: **no** [VERIFIED: no GPU dependency].
- Threads: README advertises "Multithreaded search", but `src/lib.rs::spawn_workers()` currently spawns
  exactly **one** worker thread (`for _ in 0..1`), and the commit history contains "use 1 thread"
  [VERIFIED]. Search is a DAG/transposition tree (`src/dag.rs`, `src/dag/known.rs`,
  `src/dag/speculated.rs`) with MCTS-ish expansion per the README [INFERRED].

### Implemented mechanics (from source)

This repository is **not a game engine**. It contains the minimum bookkeeping needed to search
placements, and delegates the actual game to the frontend.

- Board: `Board { cols: [u64; 10] }`, 40 rows tall; `occupied()` treats `y ≥ 40` and out-of-range `x` as
  solid (`src/data.rs`). Board parsing from TBP is `Vec<[Option<char>; 10]>` with row index 0 → bit 0
  (bottom), i.e. **40 rows expected, bottom-first** [VERIFIED].
- Pieces: 7 kinds, 4 rotations; `PieceLocation { piece, rotation, x, y }`, `Placement { location, spin }`
  where `spin: {None, Mini, Full}` is **taken from the frontend** on `play` [VERIFIED: `src/tbp.rs`,
  `src/data.rs`].
- Line clears: `Board::line_clears`, `remove_lines`; `GameState::advance()` updates bag, reserve, board,
  line clear, `back_to_back` and `combo` internally so the search can roll forward [VERIFIED].
- 7-bag: **not generated**. The frontend sends `randomizer: { type: "seven_bag", bag_state: [...] }`;
  `create_bot()` reconstructs the bag from the queue, and `speculate` is enabled only for seven-bag
  [VERIFIED]. There is no piece RNG at all.
- Hold: modelled as a `reserve: Piece` — the piece that can be placed instead of the next queue piece.
  There is no distinct "hold action" in the output; a suggestion is a list of placements
  [VERIFIED].
- Kicks: guideline SRS only. `src/movegen.rs::offsets()` gives JLSTZ
  `[(0,0),(1,0),(1,-1),(0,2),(1,2)]` for East etc. and the guideline I table
  (`North = [(0,0),(-1,0),(2,0),(-1,0),(2,0)]`), and `kicks()` subtracts target from source offsets
  [VERIFIED]. Only `rotate_cw` and `rotate_ccw` exist → **no 180 search** [VERIFIED].
- Spin detection: T only, inside `movegen.rs::rotate()`: 3-corner rule, full if both mini-corners are
  filled or the 5th kick was used, else mini [VERIFIED]. This is used to label candidate placements and
  (via the evaluation) value them.
- Combo / B2B: `GameState { combo: u8, back_to_back: bool }`, supplied by the frontend and replayed by
  the bot; `advance()` sets `back_to_back = hard && previous` where `hard = 4 lines || spin != None`
  [VERIFIED]. No B2B level, no charge, no surge.
- Garbage: **none**. No garbage queue, no messiness, no cancellation, no attack table, no damage model
  [VERIFIED].
- Evaluation: freestyle weights in `src/default.json` — `holes -1.5`, `height -0.4`, `tslot [0.1,1.5,2.0,4.0]`,
  `has_back_to_back 0.5`, `normal_clears [0,-2,-1.5,-1,3.5]`, `spin_clears [0,1,4,6]`,
  `back_to_back_clear 1.0`, `combo_attack 1.5`, `perfect_clear 15.0` [VERIFIED].

### SRS+ and 180 — explicit verdict

**Guideline SRS only; no SRS+ and no 180 at all.** [VERIFIED]

- `src/movegen.rs::offsets()` returns the guideline I offsets (byte-for-byte the same values as Cold
  Clear 1's `rotation_points()`), and `kicks()` subtracts target from source. In this crate's cell frame
  `North→East` therefore tests `(+1,0), (-1,0), (2,0), (-1,-1), (2,2)`; the uniform `(+1,0)` is the
  anchor difference between the two rotation states (East cells live at `x = 0`, North spans `x = -1..2`),
  and removing it yields the guideline order `(0,0), (-2,0), (+1,0), (-2,-1), (+1,+2)` — the asymmetric
  guideline order, **not** TETR.IO's y-symmetric SRS+ order.
- O is explicitly non-rotatable (`rotate_cw`/`rotate_ccw` return `None` for `Piece::O`), and
  `movegen` only ever generates clockwise and counter-clockwise turns (the `Rotation::flip()` helper
  exists in `data.rs`, but no move-generation path emits a 180) → a TETR.IO 180 placement can never be
  proposed by this bot.

### Season 2 support map

| Season 2 mechanic | Status |
|---|---|
| B2B charging | **Absent** — one boolean `back_to_back`; cannot represent charge level |
| Surge | **Absent** |
| Season 2 attack table | **Absent** (no attack computation at all) |
| Garbage speed/cap | **Absent** |
| All-Mini / All-Mini+ | **Absent** (T-spin only; non-T spins are `Spin::None`) |
| SRS+ / 180 | **Absent** |
| Clutch clear, opener phase | **Absent** |

### Headless / entry points

Fully headless. `src/main.rs` reads one JSON object per line from stdin, deserialises into
`FrontendMessage`, and writes one JSON object per line to stdout (`BotMessage`). CLI: `cold-clear-2
[--config <json>] [--profile]` [VERIFIED].

Protocol (all `type`-tagged, `snake_case`) [VERIFIED: `src/tbp.rs`]:

- Frontend → bot: `rules`, `start {board, queue, hold, combo, back_to_back, randomizer}`, `play {move}`,
  `new_piece {piece}`, `suggest`, `stop`, `quit`.
- Bot → frontend: `info {name, version, author, features}`, `ready`, `suggestion {moves, move_info}` where
  `move_info = {nodes, nps, extra}` and `moves` is a **sequence of placements** for the upcoming queue
  (it is a plan, not just the next piece; the exact length semantics belong to the TBP spec, which I did
  not fetch — treat "how many moves" as [UNKNOWN] and take `moves[0]` if in doubt).
- `rules` is answered with `ready` (no rules payload is validated — the bot cannot be told "no 180" or
  "Season 2 attack").
- Handshake subtlety: `start` with empty `hold` and empty `queue` is buffered until the first
  `new_piece`.

### Role for TetrisRL

**Opponent / placement oracle only.** It is a genuine competitive search bot (DAG/transposition tree
over a 2–4 piece lookahead, hand-tuned weights) and it is trivially subprocess-ready. It is *not* an RL
environment: it has no clock, no gravity, no lock delay, no garbage, no attack, no episode boundary, and
it consumes state instead of producing it. It can also act as an opponent *planner* inside our arena if
we feed it the board after every piece and accept its first placement.

### Integration surface

| Option | Exact names |
|---|---|
| Subprocess (TBP) | binary `cold-clear-2`, stdin/stdout JSON lines; messages above |
| Rust crate | package `cold-clear-2` (`rlib` + `cdylib`), `run(incoming, outgoing, config)`, `movegen::find_moves(board, piece)`, `data::{Board, Piece, Placement}` |
| Config | `--config <path>` JSON matching `BotConfig { freestyle_weights, freestyle_exploitation }`; default embedded `src/default.json` |
| C ABI / Python | **none** (the `cdylib` exports no `#[no_mangle] extern "C"` functions; it exists for wasm) |

### Integration complexity: **LOW–MEDIUM**

The protocol is small, line-oriented, and needs no build integration beyond shipping a binary: our
Python arena can spawn it, send `start` with a 40×10 board (bottom-first), queue, hold, combo,
`back_to_back`, then `suggest`/`play`. The work is mostly on our side: translating our board and piece
queue into its JSON shape, mapping our placement coordinates back into move commands, deciding how to
represent a "hold" decision (it is implicit in `reserve`), and running it under a timeout because
`suggestion` blocks until the search finishes. What **cannot** be matched is everything Season 2: the
bot has no 180, no SRS+ kicks, no spin detection for non-T pieces, no B2B level or surge, and no garbage
awareness — so its play will be systematically blind to our headline mechanics. If we want a fair
"Season 2 opponent", we must supply those mechanics ourselves (e.g. detect the spin after the fact, then
score it with our own attack table), which is an approximation, not parity.

### Activity / licence risks

- Dormant since 2022-06-29 (~4.4 years). `archived` flag: **[UNKNOWN]** (API 403); the GitHub HTML page
  fetched did not show an archive banner in the visible portion. No recent releases.
- MIT/Apache-2.0: **no copyleft**, safe for linking/embedding/copying into an MIT project; keep the
  copyright notice and (if Apache-2.0 applies and you modify files) the NOTICE file.
- Stale dependency pins; wasm/`cdylib` build path is unmaintained.

### What this means for TetrisRL

The cheapest legitimate opponent we can have: MIT/Apache, no GPU, one JSON-lines subprocess, and a
search that is genuinely strong at stacking. It is also the clearest illustration of the compatibility
gap the project must document: a 2022 TBP bot knows only `back_to_back: bool` and `combo`, so it cannot
be told about charge, surge, All-Mini+ or 180 — meaning any match against it is "TETR.IO-shaped
stacking" rather than "Season 2 versus". The right way to use it is as a *baseline opponent in a
compatibility mode* (guideline kicks, no 180, B2B chaining, our attack table applied post hoc), clearly
labelled as approximate, plus as a donor of ideas for our own search baseline (movegen → DAG →
expectimax/scored expansion). Do not mistake its placement quality for ruleset parity.

---

## 3. `MinusKelvin/cold-clear`

URL: <https://github.com/MinusKelvin/cold-clear>

### Snapshot

- "Modern Tetris Versus bot", the original Cold Clear. Workspace with 11 members: `bot`, `libtetris`,
  `battle`, `cc-client`, `opening-book` (+ `book-builder`, `pc-gen`), `c-api`, `compare`, `optimizer`,
  `tbp`. Last commit 2022-01-18 ("don't count long moves that are part of tspin doubles")
  [VERIFIED: commit Atom].

### Licence — **Mozilla Public License 2.0 (MPL-2.0)** [VERIFIED]

I read the full `LICENSE` file: it is the MPL 2.0 text (Exhibits A and B included). README says
"licensed under MPLv2". MPL-2.0 is OSI-approved and is a **weak, file-scoped copyleft**: §3.1 requires
Source Code Form (including modifications) to stay under MPL, §3.3 explicitly permits distributing a
"Larger Work" under other terms. It is *not* GPL-style viral across files, and it is *not* a permissive
licence either.

### Stack, build, dependencies, GPU

- `Cargo.toml` is a plain `[workspace]` with the 11 members and `lto = true` for release [VERIFIED].
- Each crate has its own edition/manifest (e.g. `c-api`: `edition = "2018"`,
  `crate-type = ["cdylib","staticlib"]`, deps `cold-clear`, `libtetris`, `enumset`) [VERIFIED].
- README: build the C library with `cargo build --release -p c-api` → static and shared libraries in
  `target/release`, API in `c-api/coldclear.h`; use as a Rust dependency via
  `cold-clear = { git = "..." }` [VERIFIED].
- Builds on Linux: **[INFERRED] yes for `c-api`/`tbp`/`bot`** (no OS-specific dependency in those
  crates; CI has `c-api.yml` and `client.yml`). The desktop/web client (`cc-client`) is the GUI part and
  needs extra deps (GTK per the CI commit "add libgtk-3 to CI dependencies"), which we would not build.
  Not built here.
- GPU: **no** [VERIFIED]. CPU search, `CCOptions.threads` configurable [VERIFIED: `coldclear.h`].

### Implemented mechanics (from source)

`libtetris` is a real mini engine, and `battle` is a real versus simulator, so this repo covers more
mechanics than Cold Clear 2 — but it is a **2020–2022, pre-Season-2** model.

- Board: `Board<R>` with 40 rows × 10 columns, `column_heights[10]`; `occupied()` treats out-of-range as
  solid; `lock_piece` marks `locked_out` when every cell is at `y ≥ 20`, and `movegen::lock_check` drops
  placements entirely above row 20 → **20 visible rows, 20 hidden** (`libtetris/src/board.rs`,
  `moves.rs`) [VERIFIED].
- 7-bag: `bag: EnumSet<Piece>` starting `EnumSet::all()`; `generate_next_piece(&mut rng)` samples from
  the bag and `add_next_piece` removes it and refills when empty [VERIFIED].
- Hold: `hold_piece: Option<Piece>`, `hold()` swaps; the battle loop enforces one hold per piece with
  `did_hold` [VERIFIED].
- Rotation: guideline SRS only. `libtetris/src/piece.rs::rotation_points()` returns the guideline I and
  JLSTZ offsets, and `FallingPiece::rotate()` applies them in order. Movements are
  `{Left, Right, Cw, Ccw, SonicDrop}` — **no 180** [VERIFIED].
- Spin detection: T only, 3-corner rule with mini-corners and the `i == 4` kick rule, producing
  `TspinStatus::{None, Mini, Full}` inside `rotate()` [VERIFIED].
- Attack: `libtetris/src/lock_data.rs::PlacementKind::garbage()` — single 0, double 1, triple 2, quad 4,
  mini T-spin 0, mini single 0, mini double 1, T-spin 0, T-spin single 2, T-spin double 4, T-spin triple
  6; **perfect clear overwrites the attack to 10** (`board.rs::lock_piece`); `COMBO_GARBAGE` =
  `[0,0,1,1,2,2,3,3,4,4,4,5]` (additive); B2B is a **bool** that adds **+1** line and is set by quads and
  any spin [VERIFIED].
- Garbage (battle): `Game { garbage_queue: u32, attacking: u32 }`; `deal_garbage()` cancels
  `attacking` against `garbage_queue`, then inserts up to `config.max_garbage_add` rows, re-rolling the
  hole column with probability `garbage_messiness`, and can top out
  (`battle/src/game.rs`) [VERIFIED]. `Board::add_garbage(col)` inserts one row with a single hole
  [VERIFIED].
- Battle loop: gravity, 30-frame lock delay, 15-move lock rule (`move_lock_rule`), DAS/ARR, soft drop,
  spawn delay, line-clear delay, garbage blocking option [VERIFIED].
- C API: `cc_request_next_move(bot, incoming)` takes a *count* of expected incoming garbage; state is
  `(field[400], bag_remain bitmask, hold, b2b: bool, combo: u32)` — **no B2B level/charge, no surge,
  no garbage queue** [VERIFIED: `c-api/coldclear.h`].
- TBP: `tbp/src/lib.rs` maps TBP `Start {board, queue, hold, combo, back_to_back, randomizer}` into
  `libtetris::Board` and answers `suggest` with a **single** move (`block_next_move`, one placement)
  [VERIFIED].

### SRS+ and 180 — explicit verdict

**Guideline SRS only; no SRS+, no 180.** [VERIFIED]

- `libtetris/src/piece.rs::rotation_points()` is the guideline table: `(I, North) = [(0,0),(-1,0),(2,0),(-1,0),(2,0)]`,
  `(I, East) = [(-1,0),(0,0),(0,0),(0,1),(0,-2)]`, `(I, South) = [(-1,1),(1,1),(-2,1),(1,0),(-2,0)]`,
  `(I, West) = [(0,1),(0,1),(0,1),(0,-1),(0,2)]`.
- `FallingPiece::rotate()` tries `kicks[i] = from[i] - to[i]` in order, so `North→East` evaluates
  `(+1,0), (-1,0), (2,0), (-1,-1), (2,2)` in the crate's y-up frame. Those look exotic only because the
  two rotation states use different cell anchors (North cells span `x = -1..2`, East cells sit at
  `x = 0`), which contributes a constant `(+1,0)`; subtracting it recovers the textbook guideline order
  `(0,0), (-2,0), (+1,0), (-2,-1), (+1,+2)`. The attempt order is therefore the asymmetric guideline
  ordering, **not** TETR.IO's y-symmetric SRS+ ordering.
- There is no half-turn path at all: `PieceMovement` has five variants and `FallingPiece` exposes only
  `cw`/`ccw`. So it cannot produce TETR.IO 180 placements (and therefore cannot produce 180 spins or
  180-only tucks).
- Note for completeness: because `movegen` uses the same guideline table, the bot's *reachable
  placement set* will differ from TETR.IO's in exactly the SRS+-I-kick and 180 cases.

### Season 2 support map

| Season 2 mechanic | Status |
|---|---|
| B2B charging | **Absent** — `b2b_bonus: bool`, +1 line, reset by non-hard clear |
| Surge | **Absent** |
| Season 2 attack table | **Approximated 2021-era**: table above, PC = 10, additive combo, +1 B2B |
| Garbage speed/cap | **Partial** — queue cancels immediately; `max_garbage_add` cap; messiness option; no per-batch timers |
| All-Mini / All-Mini+ | **Absent** — T-spin only |
| SRS+ / 180 | **Absent** |
| Clutch clear | **Absent** — lockout instead |
| Opener phase / garbage special bonus | **Absent** |

### Headless / entry points

- Bot via C ABI (`libcold_clear.so` / `.a`) or via the `tbp` binary (stdin/stdout JSON lines)
  [VERIFIED].
- Simulator: `battle::Game` (headless `update(Controller, piece_rng, garbage_rng) -> Vec<Event>` with
  serde `Event` enum) — this is a usable headless versus model for studying garbage flow, though it is
  not an RL interface [VERIFIED].
- GUI: `cc-client` (desktop/web) — avoid for training.

### Role for TetrisRL

**Opponent (primary) and reference versus implementation (secondary); not an RL environment.** It is a
strong, genuinely competitive search bot with a C ABI, and it is the only one in this group with a
garbage/cancellation model in-tree that we can read to sanity-check our own. But the environment role is
out: the C API is a "give me a move" interface with an async thread, no observation vector, no episode
API, no reward, and no action masking.

### Integration surface

| Option | Exact names |
|---|---|
| C ABI (static/shared) | `c-api/coldclear.h`: `cc_launch_async`, `cc_launch_with_board_async`, `cc_reset_async`, `cc_add_next_piece_async`, `cc_request_next_move(bot, incoming)`, `cc_poll_next_move`, `cc_block_next_move`, `cc_default_options`, `cc_default_weights`, `cc_fast_weights`, `cc_load_book_from_file/_memory`, `cc_destroy_book`, `cc_destroy_async`; structs `CCOptions`, `CCWeights`, `CCMove` (hold, expected_x/y, movement path), `CCPlanPlacement` |
| Rust crate | `cold-clear` (bot crate) + `libtetris` (`Board`, `FallingPiece`, `PieceMovement`, `LockResult`, `MovementMode`, `SpawnRule`) |
| TBP | `tbp` binary; one move per `suggest`; no 180, no charge fields |
| Python | **none** — needs `ctypes`/`cffi` against the C ABI or a subprocess wrapper |

### Integration complexity: **MEDIUM**

The C API is well-documented and stable, but it is a *stateful async bot*, not a function call: we would
have to write (a) a `ctypes`/`cffi` binding including the 400-bool field with bottom-left origin,
`bag_remain` bitmask, and `CCMove.movements` decoding; (b) a driver loop that calls
`cc_request_next_move(incoming)` before the piece spawns and `cc_poll_next_move` until
`CC_MOVE_PROVIDED`, then feeds the resulting board back with `cc_reset_async` whenever garbage lands or
the placement fails; (c) a shim for the missing Season 2 surface — our engine must inject garbage and
re-sync the bot, because the bot only takes an integer `incoming` hint and has no surge/charge concept
(nor does it know about 180 or SRS+); (d) an options/weights mapping (`CCWeights` is a wide struct of
ints; `cc_fast_weights` exists for weaker/faster play); and (e) process-level isolation if we choose the
TBP path instead (then we lose the plan/`CCOptions.threads` control). What cannot be matched: SRS+ I
kicks, 180 rotations, B2B charging/surge, All-Mini+, and any Season 2 attack-table nuance — the bot's
internal model is boolean-B2B, additive-combo, guideline-kicks, 2021 attack values.

### Activity / licence risks

- Dormant since 2022-01-18 (~4.9 years). `archived` flag **[UNKNOWN]** (API 403). Old workspace
  (`rental` → `ouroboros`, `parking_lot 0.11`, edition 2018) will need care on a 2026 toolchain.
- **MPL-2.0 copyleft implications**: linking (static or dynamic) into an MIT project is permitted
  because MPL is file-scoped and §3.3 allows a Larger Work under other terms. But: any file you copy or
  modify from this repo must remain MPL-2.0, with its source made available and notices retained, and it
  cannot be relicensed as MIT. A single MIT `LICENSE` at the repo root would be incomplete/misleading if
  you vendor MPL files; you must keep the MPL file headers/notices and state which files are MPL.
- Opening books (`opening-book/`, `.ccbook`/`.ccdb`) are repo data assets and are presumably covered by
  the repo-wide MPL-2.0 [INFERRED — no separate licence file per directory]; `cc-client` bundles a font
  under the OFL (`cc-client/res/LICENSE_OFL.txt`) — irrelevant for engine use but easy to drag in by
  accident.

### What this means for TetrisRL

This is the best *opponent* in the group and the best *documentation of a versus loop* we can legally
read: `battle/src/game.rs` shows a complete gravity/lock-delay/15-move-rule/garbage-cancel/top-out
pipeline, and `libtetris/src/piece.rs` gives us a clean reference for guideline kicks and T-spin
classification to test our own implementation against. It is not a ruleset oracle for Season 2 — no 180,
no SRS+, boolean B2B, additive combo, PC=10 — so it belongs in a "compatibility baseline" bucket next to
Cold Clear 2, not in the "Season 2 parity" bucket. Legally it is usable: dynamic linking or a
subprocess wrapper is the low-friction path, and if we do link statically we must ship the MPL source
for the Cold Clear files we redistribute. Because it needs garbage fed back through `cc_reset_async`, our
arena should treat it as a black-box opponent adapter (reset/observe/choose_action/receive_result) rather
than as a component of the simulator.

---

## Licence analysis: can these be linked into an MIT project?

Short answer: **one of the three cannot be used at all; the other two can, with different obligations.**

| Repo | Licence | Forbid linking/embedding into MIT? | Forbid copying code into MIT? | Safe integration mode |
|---|---|---|---|---|
| `tetris-engine-in-rust` | **none** | **Yes** — no grant exists; "all rights reserved" | **Yes** | **None.** No linking, no embedding, no vendoring, no subprocess distribution. Use only as an unpublished local behavioural oracle, or re-implement clean-room, or obtain written permission from the author. |
| `cold-clear-2` | MIT OR Apache-2.0 | No | No (keep copyright/attribution; Apache NOTICE if applicable) | Anything: dynamic/static link, subprocess, vendored crate, copied file with notice. |
| `cold-clear` | MPL-2.0 | **No** — §3.3 explicitly allows a Larger Work under other terms | **Yes, in effect**: copied files stay MPL-2.0 and must not be relicensed as MIT | Link (dynamic preferred), or subprocess/TBP. If any MPL file is copied or modified, keep it MPL with notices and publish its source. Do **not** paste MPL code into MIT-licensed files. |

Practical rule for TetrisRL (MIT): treat `tetris-engine-in-rust` as **read-only, never-distributed
reference**; integrate `cold-clear-2` as an external subprocess or a properly-attributed dependency; and
integrate `cold-clear` as a **subprocess or dynamic library** with an MPL notice file, never by copying
its `piece.rs`/`game.rs` into our tree. A subprocess boundary is the safest default for both Cold Clears
and has the additional benefit that a crash or hang in a Rust bot cannot take down training.

## Sources actually fetched

Repository trees and metadata (GitHub API):

- <https://api.github.com/repos/nyctivoe/tetris-engine-in-rust/git/trees/HEAD?recursive=1> — 200
- <https://api.github.com/repos/nyctivoe/tetris-engine-in-rust> — 200 (license null, created/pushed dates, stars)
- <https://api.github.com/repos/MinusKelvin/cold-clear-2/git/trees/HEAD?recursive=1> — 200
- <https://api.github.com/repos/MinusKelvin/cold-clear/git/trees/HEAD?recursive=1> — 200
- <https://api.github.com/repos/MinusKelvin/cold-clear> — **403 rate limit exceeded** (metadata [UNKNOWN])

`nyctivoe/tetris-engine-in-rust` source:

- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/README.md> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/Cargo.toml> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/pyproject.toml> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/constants.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/lib.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/piece.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/rotation.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/scoring.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/garbage.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/engine.rs> — 200 (output
  truncated; the complete body was spilled to a local temp file and the missing span, including
  `try_rotate_piece`, `detect_t_spin`, `detect_all_spin`, `occupied_3x3_corners`, read from there)
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/python.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/board.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/rng.rs> — 200
- <https://raw.githubusercontent.com/nyctivoe/tetris-engine-in-rust/HEAD/src/bfs.rs> — 200
- <https://github.com/nyctivoe/tetris-engine-in-rust/commits/main.atom> — 200 (activity)

`MinusKelvin/cold-clear-2` source:

- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/README.md> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/Cargo.toml> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/src/lib.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/src/main.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/src/tbp.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/src/data.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/src/movegen.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/src/bot.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear-2/HEAD/src/default.json> — 200
- <https://github.com/MinusKelvin/cold-clear-2/commits/main.atom> — 200 (activity)
- <https://github.com/MinusKelvin/cold-clear-2/commits/master.atom> — **404** (branch is `main`)
- <https://github.com/MinusKelvin/cold-clear-2> — 200 (HTML, truncated; no archive banner seen)

`MinusKelvin/cold-clear` source:

- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/LICENSE> — 200 (MPL-2.0 full text)
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/README.md> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/Cargo.toml> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/libtetris/src/piece.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/libtetris/src/board.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/libtetris/src/moves.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/libtetris/src/lib.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/libtetris/src/lock_data.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/c-api/coldclear.h> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/c-api/Cargo.toml> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/c-api/src/lib.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/tbp/src/lib.rs> — 200
- <https://raw.githubusercontent.com/MinusKelvin/cold-clear/HEAD/battle/src/game.rs> — 200
- <https://github.com/MinusKelvin/cold-clear/commits/master.atom> — 200 (activity)

Ruleset references (for the SRS+/Season 2 comparisons, not repo sources):

- <https://tetrio.wiki.gg/wiki/Mechanics> — 200 (rendered; truncated before the B2B sections)
- <https://tetrio.wiki.gg/wiki/Mechanics?action=raw> — 200 (full wikitext: 180 kicks, SRS-X, SRS+,
  Combo Multiplier, B2B Charging, B2B Chaining, All-Mini/All-Mini+, Clutch Clear, Opener Phase, Garbage
  Special Bonus)
- <https://tetrio.wiki.gg/wiki/SRS%2B> — **404**
- <https://harddrop.com/wiki/TETR.IO> — 200 (SRS+ = "SRS with modified I piece kicks"; B2B charging default
  after Beta; garbage change-on-attack / full blocking)
- <https://harddrop.com/wiki/SRS> — 200 (guideline JLSTZ and I kick tables used above)
