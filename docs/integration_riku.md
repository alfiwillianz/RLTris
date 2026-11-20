# RIKU0804/tetris-ai as a real versus opponent

**Status: REAL INTEGRATION EXECUTED.** `RIKU0804/tetris-ai` was cloned at a
pinned commit into `third_party/`, built with `cargo build --release`, driven as
a subprocess over the Tetris Bot Protocol (TBP), validated against
`GameState.legal_actions()`, and used to play **20 real versus matches**
(10 vs the in-repo heuristic, 10 vs the random baseline) inside
`tetrisrl.environment.versus.VersusMatch` under the project's `tetrio_s2`
ruleset.

Verification date: **2026-11-20** · Host: Linux 7.3.4 (CachyOS), cargo/rustc
1.100.0, Python 3.12.15 (`/home/alfi/Active/tetrlio/.venv/bin/python`).

---

## 1. TL;DR

| Item | Value |
|---|---|
| Engine | [RIKU0804/tetris-ai](https://github.com/RIKU0804/tetris-ai) (`RIKU0804/tetris-ai`) |
| Pinned commit | `d3f92d289a24e09ec72679d8ce653bfd8a98679e` (2026-06-22, "feat: Tetris AI — Rust core, beam-search AI, versus training, TBP") |
| License | **MIT** (© 2026 riku); notice + licence text in `third_party/RIKU_NOTICE.md` |
| Build | `cargo build --release` in `core-rs/` → succeeded in **5.47 s** (1 warning, 0 errors, zero dependencies) |
| Binary | `third_party/riku-tetris-ai/core-rs/target/release/tetris-core`, 629,840 bytes, SHA-256 `bcee2640f8e1e07383ef64008b12835f1e4271dfbe2a6226c06f2156f2f17db3` |
| Engine self-report | `{"type":"info","name":"RikuBot","version":"0.1","author":"riku","features":[]}` |
| Protocol | TBP JSON lines over stdin/stdout, subcommand `tbp` (`start` → `suggest` → `suggestion`) |
| Adapter | `tetrisrl/agents/opponents/riku.py` (`RikuAgent(TBPAgent)`) |
| Tests | `tetrisrl/tests/test_opponents_riku.py` — **16 passed** in 0.70 s (4 engine tests skip when unbuilt) |
| Match runner | `scripts/run_riku_match.py` |
| Real match | **Yes** — 5–1–4 vs heuristic, 10–0–0 vs random (§6) |
| Engine's role | **Placement suggester only.** `tetrisrl` owns attack, garbage, cancellation, B2B charging, surge, top-out and the action space. |
| Search budget | beam width 16, depth 6 (RIKU defaults for `tbp`), ~4.1 ms per suggestion |
| Fallback rate | 12.65% vs heuristic, 15.74% vs random — all of them tuck-only placements our hard-drop action space cannot express (§7) |

**What this is not:** it is not a TETR.IO Season 2 benchmark. RIKU implements
guideline SRS, has no 180° rotation, no Season 2 attack/B2B-charge/surge model,
and only sees the board it is given. The 20 matches show that a real, unmodified
RIKU binary made most of one side's placement decisions under *our* ruleset; the
numbers are one recorded run against two simple baselines, not a strength claim.

---

## 2. Files

| File | Purpose |
|---|---|
| `tetrisrl/agents/opponents/riku.py` | `RikuAgent`, binary/weights resolution, RIKU-specific start message, TBP coordinate normalisation |
| `tetrisrl/tests/test_opponents_riku.py` | 16 tests: availability, geometry, normalisation, queue convention, real handshake, raw suggestion validity, action conversion, VersusMatch smoke |
| `scripts/run_riku_match.py` | Match runner used for §6 (JSON report + console table) |
| `third_party/RIKU_NOTICE.md` | Provenance, pinned commit, licence text, binary hash |
| `docs/integration_riku.md` | This document |
| `third_party/riku-tetris-ai/` | Local clone + build tree (**not** part of the package, must not be committed) |

`tetrisrl/agents/opponents/tbp.py` was **not modified**: `RikuAgent` subclasses
`TBPAgent` and reuses its `TBPSession` transport, counters, timeout handling,
pytest launch guard and heuristic-fallback accounting. The Python package does
not contain any upstream source: the engine always runs as a separate process.

> **Git caveat:** `.gitignore` lists `third_party/cold-clear-2/` only, not
> `third_party/riku-tetris-ai/`. The clone is currently untracked; add
> `third_party/riku-tetris-ai/` (or `third_party/`) to `.gitignore` before
> committing so the build tree is never staged.

---

## 3. Exact build steps and result

```bash
cd /home/alfi/Active/tetrlio
git clone https://github.com/RIKU0804/tetris-ai third_party/riku-tetris-ai
git -C third_party/riku-tetris-ai checkout d3f92d289a24e09ec72679d8ce653bfd8a98679e
(cd third_party/riku-tetris-ai/core-rs && cargo build --release)
```

`core-rs/Cargo.toml` declares `name = "tetris-core"`, edition 2021, an **empty
`[dependencies]`** table (the author hand-rolls JSON/PRNG/threading), and a
release profile with `lto = true`, `codegen-units = 1`, `panic = "abort"`.

Observed build tail (exit code 0):

```
warning: constant `VISIBLE_HEIGHT` is never used
  --> src/engine.rs:12:11
warning: `tetris-core` (bin "tetris-core") generated 1 warning
    Finished `release` profile [optimized] target(s) in 5.47s
```

Reproduce the exact binary identity:

```bash
sha256sum third_party/riku-tetris-ai/core-rs/target/release/tetris-core
# bcee2640f8e1e07383ef64008b12835f1e4271dfbe2a6226c06f2156f2f17db3
```

No source patches were needed. The crate is a **binary only** (no lib target),
so subprocess is the only sane integration path.

---

## 4. TBP protocol as actually implemented by RIKU

Verified against the built binary and `core-rs/src/{tbp.rs,main.rs,json.rs}`.

### 4.1 Lifecycle

```
engine → info                    {"type":"info","name":"RikuBot",...}   (once, at startup)
adapter → rules                  {"type":"rules"}
engine → ready                   {"type":"ready"}
adapter → start                  {board, queue, hold, combo, back_to_back}
adapter → suggest                {"type":"suggest"}
engine → suggestion              {"moves":[{"location":{...},"spin":"none"}]}
... repeat start/suggest for every piece ...
adapter → quit                   {"type":"quit"}   (then stdin close / kill)
```

`cmd_tbp` is a single-threaded loop that handles `rules`, `start`, `suggest`,
`play`, `new_piece`, `stop` (no-op) and `quit`; unknown message types are
ignored silently. The adapter sends a **fresh `start` for every piece** (the same
choice as the Cold Clear 2 adapter) because our fallback can diverge from the
engine's plan; RIKU's own `play`/`new_piece` board tracking is therefore unused.
`start` fully overwrites the bot's board, queue, hold, combo and B2B flag, so a
fresh start per piece cannot accumulate state.

### 4.2 Deviations from the TBP spec / from Cold Clear 2

| Topic | RIKU behaviour | Consequence in the adapter |
|---|---|---|
| **Suggestions** | Exactly **one** move per `suggest`; **no `move_info`** object, no node/NPS telemetry | Only `moves[0]` exists to try; `stats.last_move_info` stays `{}` and `stats.nodes_total` is always 0 |
| **Timing** | `suggest` is answered synchronously (no worker thread, no empty-move "thinking" phase) | `think_time=0.0`; the inherited retry loop is kept for safety |
| **`error` messages** | Never emitted; invalid input is ignored or treated as empty | Failures surface as empty `moves`, timeouts or process death |
| **Board rows** | Array of rows, **`board[0]` is the bottom row**, up to 40 rows are read; extra rows ignored; cells are "occupied" iff not `null` | Same wire encoding as Cold Clear 2 (`board_to_tbp_rows`, bottom-up, `"#"`) |
| **Queue** | **`queue[0]` is always the current piece**, whether or not `hold` is set (`best_move` starts at `qi = 0`) | `build_riku_start_message` sends `[current, *previews]`; `tbp.build_start_message` (Cold Clear 2 convention: `[preview0, current, ...]` when hold is empty) is **not** reused |
| **Hold** | `hold: null` or a piece letter; root can hold the current piece or the held piece | Suggestions whose piece differs from our current piece are matched to our **hold** actions |
| **`combo`** | Any `i32`, used as a consecutive-clear count in the evaluation | Adapter sends `max(0, combo + 1)` (TETR.IO `-1 = none` → TBP `0`) |
| **`back_to_back`** | Boolean, internally stored as `1`/`0`, used as a flat feature | Adapter sends `state.b2b_active`; RIKU has no charge/surge concept |
| **Coordinates** | `location.x/y` are produced as `(box_x + 1, 38 - box_y)` from the piece's **bounding-box origin**, not the TBP SRS rotation centre. Exact for J/L/T/S/Z; the file's own comment flags the I and O centre conventions as under-specified | The adapter decodes cells with RIKU's own `SHAPES` table (`riku_move_cells`) and rewrites the move into the SRS-centre convention (`normalise_riku_move`) before the inherited `action_for_tbp_move` maps it. Without this, I-piece suggestions are systematically off by one cell |
| **Orientation labels** | `north|east|south|west` = rotation states 0..3, matching SRS spawn/R/2/L | Labels are only used to index the shape table; placement matching is purely geometric (cell sets) |
| **`spin`** | `none|mini|full`, T-only 3-corner classification | Ignored for adjudication: our engine re-classifies every placement with SRS+/TETR.IO rules |
| **`play`/`new_piece`** | Supported and update the bot's private board/queue | Not used (fresh `start` per piece), so no desync is possible |
| **Determinism** | Beam ties are broken via hash-map iteration order (upstream README: "the beam currently breaks ties via hash order") | Two runs of the same match command can differ; replays of *our* matches are still deterministic because the chosen actions are recorded |

### 4.3 Coordinate normalisation (the one real bug-like quirk)

RIKU emits the TBP centre as if the SRS rotation centre were always
`(box_x + 1, box_y + 1)`. That holds for J/L/T/S/Z, but for the 4×4-box I piece
the centre is a different cell in the R/E/L states, and for O the box is 3 wide.
Example (verified live): the engine emits `{"type":"I","orientation":"south",
"x":5,"y":0}` intending the horizontal bar on the floor in columns 3–6. Decoded
with the usual TBP centre convention this is exactly columns 3–6, row 39 —
correct. But the inverse of RIKU's *own* encoding (which the adapter uses to
recover the intended cells unambiguously) gives columns 4–7, row 40 for the same
numbers. The adapter therefore:

1. decodes the raw move with `riku_move_cells` using RIKU's box-origin
   convention (`box_x = x - 1`, `box_y = 38 - y`, then `SHAPES[p][rot]`), which
   reproduces the engine's intended board cells exactly;
2. finds the canonical TBP centre for the same piece/orientation/cells
   (`normalise_riku_move`), so `tbp.tbp_move_cells` yields the identical cell
   set;
3. lets the inherited `TBPAgent.choose_action` match those cells against
   `GameState.legal_actions()`.

Verification: the round-trip holds for every in-board piece/orientation/anchor
combination tested (0 mismatches), and a fuzz run of **120 random stacked
boards** produced 120 suggestions that all decoded to collision-free, resting
placements. Cell geometry — not the rotation label — is what gets matched.

---

## 5. Adapter behaviour (`RikuAgent`)

* **Launch**: `tetris-core tbp [--width 16] [--depth 6] [--weights <clone>/weights/champion-vs.json]`.
  The default weights file is the clone's pre-tuned `champion-vs.json` when it
  exists, otherwise the engine's built-in attack preset.
* **Lazy process launch**: importing `riku.py`, constructing `RikuAgent`, and
  collecting pytest tests never spawn a process. The engine starts on the first
  `choose_action()`.
* **Inherited guard**: under pytest the adapter refuses to launch unless
  `allow_in_tests=True`; `TETRISRL_TBP_DISABLE=1` also disables launching.
* **Missing binary**: a clear `TBPError` naming `third_party/riku-tetris-ai/core-rs`
  is raised inside `choose_action`, counted as `protocol_errors`, and the
  heuristic plays the move. Matches never crash on a broken engine.
* **Fallback**: the in-repo `HeuristicAgent` (same policy as the Cold Clear 2
  adapter), configurable via `fallback=`. Every fallback increments
  `stats.fallbacks` and `stats.invalid_suggestions`; the reason lands in
  `stats.last_error`.
* **Counters** (`agent.stats`): inherited `TBPStats` — `engine_starts`,
  `suggestions`, `accepted`, `invalid_suggestions`, `fallbacks`, `timeouts`,
  `protocol_errors`, `engine_restarts`, `answer_latency_ms`, `nodes_total`
  (always 0 for RIKU), `last_move_info`, `last_error`.
* **Path resolution**: `riku_binary_path(binary=None)` uses the argument, then
  `$TETRISRL_RIKU_BIN`, then the default build.

---

## 6. Actual match results (real RIKU binary)

Commands (exactly as required):

```bash
.venv/bin/python scripts/run_riku_match.py --games 10 --opponent heuristic
.venv/bin/python scripts/run_riku_match.py --games 10 --opponent random
```

Configuration: `tetrio_s2` ruleset, one engine process per game, seeds 0–9,
`--max-pieces 400`, beam `--width 16 --depth 6`, weights `weights/champion-vs.json`,
suggestion timeout 5 s, RIKU as agent A and the baseline as agent B. JSON reports
saved during verification: `results/riku_match_heuristic.json`,
`results/riku_match_random.json`.

### 6.1 Score

| Series | Score (W–L–D) | Win rate | Games | Avg ticks | Wall time |
|---|---|---|---|---|---|
| RIKU vs heuristic | **5–1–4** | 50.0% | 10 | 311.5 | 33.6 s |
| RIKU vs random | **10–0–0** | 100.0% | 10 | 19.7 | 1.4 s |

Exact console summary:

```
--- RIKU (TBP subprocess) vs heuristic ---
  game  1 seed=0     draw  reason=max_pieces   ticks=400  accepted=352  fallbacks=48   invalid=48   topout=-          4.26s
  game  2 seed=1     win   reason=top_out_b    ticks=204  accepted=183  fallbacks=21   invalid=21   topout=block_out  2.16s
  game  3 seed=2     draw  reason=max_pieces   ticks=400  accepted=349  fallbacks=51   invalid=51   topout=-          4.36s
  game  4 seed=3     win   reason=top_out_b    ticks=356  accepted=321  fallbacks=35   invalid=35   topout=block_out  3.76s
  game  5 seed=4     win   reason=top_out_b    ticks=95   accepted=75   fallbacks=20   invalid=20   topout=block_out  1.05s
  game  6 seed=5     draw  reason=max_pieces   ticks=400  accepted=352  fallbacks=48   invalid=48   topout=-          4.41s
  game  7 seed=6     loss  reason=top_out_a    ticks=350  accepted=303  fallbacks=47   invalid=47   topout=-          3.79s
  game  8 seed=7     draw  reason=max_pieces   ticks=400  accepted=342  fallbacks=58   invalid=58   topout=-          4.33s
  game  9 seed=8     win   reason=top_out_b    ticks=274  accepted=241  fallbacks=33   invalid=33   topout=block_out  2.92s
  game 10 seed=9     win   reason=top_out_b    ticks=236  accepted=203  fallbacks=33   invalid=33   topout=block_out  2.56s
  SUMMARY vs heuristic: 5-1-4 (50.0% wins) over 10 games; engine suggestions 3115, accepted 2721, fallbacks 394 (rate 12.65%)

--- RIKU (TBP subprocess) vs random ---
  game  1 seed=0     win   reason=top_out_b    ticks=23   accepted=20   fallbacks=3    invalid=3    topout=block_out  0.15s
  ...
  game 10 seed=9     win   reason=top_out_b    ticks=23   accepted=20   fallbacks=3    invalid=3    topout=block_out  0.16s
  SUMMARY vs random: 10-0-0 (100.0% wins) over 10 games; engine suggestions 197, accepted 166, fallbacks 31 (rate 15.74%)
```

All 20 matches had `invalid_actions == [0, 0]` at the `VersusMatch` layer (no
action was ever rejected by the arena), no engine crash, no restart and no
timeout. The 5 draws vs the heuristic are 400-piece caps where neither side
topped out; RIKU's board was consistently lower and cleaner (§6.3).

**Nondeterminism warning:** RIKU's beam breaks ties through hash-map order, so
*repeat runs of the same command are not identical*. An earlier run of the same
heuristic command (same seeds, same build) produced 5–0–5 with different
per-game outcomes. The numbers above are the recorded JSON run; treat them as
one sample, not a fixed constant.

### 6.2 Engine telemetry

| Metric | vs heuristic | vs random |
|---|---|---|
| Engine suggestions | 3,115 | 197 |
| Accepted placements | 2,721 | 166 |
| Tuck-only suggestions → heuristic fallback | 394 | 31 |
| Fallback rate | **12.65%** | **15.74%** |
| Mean answer latency | 4.11 ms | 4.18 ms |
| Engine starts (processes) | 10 | 10 |
| Protocol errors / timeouts / restarts | 0 / 0 / 0 | 0 / 0 / 0 |
| Node telemetry | none — RIKU has no `move_info` | none |

### 6.3 Per-player averages (10 games each)

**vs heuristic**

| Player | Pieces | Lines | Attack | Sent | Recv | Inserted | T-spins | Tetrises | B2B max | Holds | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RIKU | 311.5 | 149.8 | 105.9 | 91.3 | 47.4 | 32.8 | 9.3 | 1.4 | 1.2 | 134.6 | 6.2 | 3.3 |
| Heuristic | 311.5 | 177.6 | 66.3 | 47.4 | 91.1 | 72.2 | 5.9 | 1.5 | 1.0 | 112.8 | 14.5 | 10.9 |

RIKU cleared fewer lines but generated ~1.6× the attack (more T-spins, better
B2B/combo timing), sent ~1.9× the garbage, and kept a much lower/cleaner board
(final height 6.2 vs 14.5, holes 3.3 vs 10.9). The heuristic survived to the
400-piece cap in 4 games by downstacking; RIKU won 5 by topping it out and lost
1 game (seed 6) by topping out itself.

**vs random**

| Player | Pieces | Lines | Attack | Sent | Recv | Inserted | T-spins | Holds | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|---|---|
| RIKU | 19.7 | 5.3 | 3.2 | 3.2 | 0.0 | 0.0 | 0.5 | 6.9 | 4.2 | 1.4 |
| Random | 19.7 | 0.1 | 0.0 | 0.0 | 2.9 | 2.9 | 0.0 | 6.4 | 21.7 | 63.9 |

Random cleared essentially nothing and topped out after ~20 pieces; RIKU never
received garbage, which is the expected sanity-check result for a real opponent
under our garbage rules.

### 6.4 Fallback diagnosis (separate 300-piece run)

A diagnostic run (seed 5, same adapter, no match) classified every fallback of a
300-piece game:

| Outcome | Count |
|---|---|
| Engine suggestion accepted (mapped to a legal action) | 229 |
| Fallback — placement exists only as a **tuck/slide**, unreachable by a hard drop | 71 |
| Fallback — hold-flag mismatch | 0 |
| Fallback — no legal placement for the suggested piece at all | 0 |

So the fallback rate is **not** a coordinate-mapping bug: it is the structural
gap between RIKU's BFS placement generator (which enumerates tucks, spins and
slides) and our `(rotation, column, hold)` hard-drop action space. RIKU's
evaluation frequently prefers those shapes once the board has an overhang, which
is why its fallback rate is much higher than Cold Clear 2's 0.42%. The engine
still made **87.4%** of its moves (2,721 / 3,115) in the heuristic series.

---

## 7. Reproduction

```bash
# 0. Clone + build the pinned engine (once); see §3.
cd /home/alfi/Active/tetrlio
git clone https://github.com/RIKU0804/tetris-ai third_party/riku-tetris-ai
git -C third_party/riku-tetris-ai checkout d3f92d289a24e09ec72679d8ce653bfd8a98679e
(cd third_party/riku-tetris-ai/core-rs && cargo build --release)

# 1. Adapter tests (engine tests skip automatically when the binary is absent)
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_riku.py -q
# observed: 16 passed in 0.70s

# 2. Preflight: import + handshake only
.venv/bin/python - <<'PY'
from tetrisrl.agents.opponents.riku import RikuAgent, riku_available
print("available:", riku_available())
a = RikuAgent()
print(a._launch_command())
a.terminate()
PY

# 3. Real matches (these produced §6)
.venv/bin/python scripts/run_riku_match.py --games 10 --opponent heuristic
.venv/bin/python scripts/run_riku_match.py --games 10 --opponent random

# 4. Quick smoke (2 games each, 120-piece cap)
.venv/bin/python scripts/run_riku_match.py --games 2 --max-pieces 120 --opponent heuristic random

# 5. The whole test suite must stay green
.venv/bin/python -m pytest
# observed: 194 passed in 13.02s
```

Environment override: `TETRISRL_RIKU_BIN=/path/to/tetris-core`. Optional
weights: `--weights /path/to/weights.json` (the runner passes the clone's
`weights/champion-vs.json` by default when present; the engine falls back to its
built-in attack preset otherwise).

---

## 8. Compatibility limitations (explicit)

1. **Placement suggester, not a simulator.** RIKU receives board, hold, queue,
   combo and B2B flag; it returns one placement. It never sees our opponent, our
   attack tables, garbage queues, surge or top-out. `tetrisrl` remains the only
   authority for every competitive rule.
2. **Guideline SRS, not TETR.IO SRS+.** RIKU's kick tables are the guideline
   tables; SRS+ (TETR.IO) tries the mirrored I kick first and is not modelled.
   Placements requiring SRS+-only kicks are simply not proposed, and our engine
   still validates every placement with SRS+.
3. **No 180° rotation.** `try_rotate` only takes ±1 and the TBP surface only
   exposes `north/east/south/west`, so placements that require a 180° spin are
   unavailable to the engine.
4. **No TETR.IO Season 2 mechanics.** RIKU's own versus rules (unused here) have
   a custom attack table resembling an older TETR.IO season, flat `+1` B2B
   chaining (no charge), a combo table and a 10-attack perfect-clear bonus; it
   has no surge, no S2 cancellation and a simple 1-turn/8-per-turn garbage model.
   None of that is imported: B2B **charging**, **surge**, S2 cancellation and
   garbage insertion live exclusively in
   `tetrisrl/{scoring,garbage,engine,versus}.py`.
5. **Tuck-only placements are unreachable.** Our action space is
   `(rotation, column, hold)` hard drops. RIKU's BFS includes tucks/slides/spin
   slots; 12.65% (vs heuristic) and 15.74% (vs random) of its suggestions had no
   legal hard-drop equivalent and were played by the heuristic fallback. This is
   measured and reported, not silently patched.
6. **No incoming-garbage planning.** TBP has no pending-garbage or
   incoming-attack message, so RIKU only sees garbage after it lands on the
   board.
7. **Hold is inferred from the placed piece.** TBP `suggestion` does not say
   whether to hold; the adapter treats `piece != current` as a hold move, which
   is exact for our engine because a suggested piece can only be the current,
   the held, or the next piece.
8. **Single suggestion, no telemetry.** No alternative moves to shop from, no
   node counts (`stats.nodes_total` stays 0), so no search-depth reporting is
   possible.
9. **Engine nondeterminism.** Beam ties break via hash order, so repeated
   matches are not bit-identical even with identical seeds. Our replays record
   the chosen *actions*, so replay verification of a completed match is still
   deterministic.
10. **Weights are optional.** `weights/champion-vs.json` is used when the clone
    is present; without it the engine uses its built-in attack preset, which is
    a different (weaker) policy. The match numbers in §6 used the weights.
11. **No claim about RIKU vs. Season 2.** These matches say only that the binary
    produced legal placements and won/lost under *our* ruleset against two simple
    baselines. 5–1–4 over 10 games has a Wilson 95% interval of roughly
    [23.7%, 76.3%], and 10–0 over 10 a lower bound around 72%; neither is a
    strength estimate.

---

## 9. Non-claims

* We did **not** modify the RIKU source; the clone is at the pinned commit and
  the adapter speaks its stock `tbp` subcommand.
* We did **not** use RIKU's own versus/attack logic; every competitive rule was
  enforced by `tetrisrl`.
* We did **not** benchmark RIKU's `bench`/`vs` modes or its Python reference
  implementation; only `tetris-core tbp` was exercised.
* The `RikuAgent` fallback is the in-repo heuristic, so a minority of RIKU's
  moves are not engine decisions. The split is reported per series.
