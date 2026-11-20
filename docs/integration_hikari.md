# SoRA-X7/hikari_rei as a real versus opponent

**Status: REAL INTEGRATION EXECUTED.** `SoRA-X7/hikari_rei` — the MIT-licensed
Rust reimplementation of Hikari — was cloned at a pinned commit into
`third_party/`, built with `cargo build --release`, driven as a subprocess over
the Tetris Bot Protocol (TBP), its wire conventions were verified against the
live binary, and it played **20 real versus matches** (10 vs the in-repo
heuristic, 10 vs the random baseline) inside
`tetrisrl.environment.versus.VersusMatch` under the project's `tetrio_s2`
ruleset.

Verification date: **2026-11-20** (Asia/Jakarta) · Host: Linux, rustc/cargo
1.100.0, Python 3.12.15 (`/home/alfi/Active/tetrlio/.venv/bin/python`).

---

## 1. TL;DR

| Item | Value |
|---|---|
| Engine | [SoRA-X7/hikari_rei](https://github.com/SoRA-X7/hikari_rei) (Hikari Rust) |
| Pinned commit | `21b63c652f232d64016b2af72876d7a4b0e238fd` (2026-11-21 00:32 +0900, "Merge pull request #22 from SoRA-X7/feature/targeted-physical-path-search") |
| Port origin | GitLab `SoRA_X7/hikari` commit `90aef085a53d6048cbd19de7f4c9c53a6f3c8960` (upstream README + binary `info.reference_commit`) |
| License | **MIT** (© 2026 Hikari Rei contributors); notice + full licence text in `third_party/HIKARI_NOTICE.md` |
| Build | `cargo build --release` → succeeded in **12.25 s** (0 errors, 0 warnings) |
| Binary | `third_party/hikari_rei/target/release/hikari_rei`, 1,830,968 bytes, SHA-256 `2f746bf37872cf13b63b9780dc4bfd171d08f3e32af296a3a59723704afde51d` |
| Engine self-report | `{"type":"info","name":"Hikari Rust","version":"0.2.0","author":"SoRA_X7","features":["randomizer","move_info"],"reference_commit":"90aef085a53d6048cbd19de7f4c9c53a6f3c8960"}` |
| Protocol | TBP JSON lines over stdin/stdout, subcommand `tbp` (`start` → `suggest` → `suggestion`) |
| Adapter | `tetrisrl/agents/opponents/hikari.py` (`HikariAgent(TBPAgent)`) |
| Tests | `tetrisrl/tests/test_opponents_hikari.py` — **19 passed** in 0.95 s (engine tests skip when unbuilt) |
| Match runner | `scripts/run_hikari_match.py` |
| Real match | **Yes** — 6–4–0 vs heuristic, 10–0–0 vs random (§7) |
| Engine's role | **Placement suggester only.** `tetrisrl` owns attack, garbage, cancellation, B2B charging, surge, top-out and the action space. |
| Search budget | 1 worker, 20 ms ponder per move (`--think-ms 20`), no node cap override (engine default 3.5 M) |
| Wire board | **24 rows, bottom-first** = our rows **39…16** (§4.2) |
| Fallback rate | **1.25%** vs heuristic (10/797), **1.08%** vs random (2/186); all verified as tuck/slide placements our hard-drop action space cannot express (§8) |

**What this is not:** it is not a TETR.IO Season 2 benchmark. Hikari implements
**SRS** (not TETR.IO SRS+), has **no 180° rotation**, no Season 2 attack / B2B
charge / surge model, and cannot see pending garbage. The 20 matches show that
a real, unmodified Hikari binary made the large majority of one side's placement
decisions under *our* ruleset; the numbers are one recorded run against two
simple baselines, not a strength claim.

---

## 2. Files

| File | Purpose |
|---|---|
| `tetrisrl/agents/opponents/hikari.py` | `HikariAgent`, binary resolution, `HIKARI_PROFILE`, verified start message helper |
| `tetrisrl/tests/test_opponents_hikari.py` | 19 tests: availability, wire board shape/slice, queue/combo/B2B conventions, geometry, hold mapping, real handshake/echo/row-rejection, VersusMatch smoke |
| `scripts/run_hikari_match.py` | Match runner used for §7 (JSON report + console table) |
| `third_party/HIKARI_NOTICE.md` | Provenance, pinned commit, MIT text, binary hash |
| `docs/integration_hikari.md` | This document |
| `third_party/hikari_rei/` | Local clone + build tree (gitignored; **not** part of the package) |

`tetrisrl/agents/opponents/tbp.py` was **not modified**: `HikariAgent`
subclasses `TBPAgent` and reuses its `TBPSession` transport, counters, timeout
handling, pytest launch guard and heuristic-fallback accounting. The only
engine-specific pieces are the launch command, `TBPProfile`, and a nested
`move_info.search.nodes` telemetry hook.

---

## 3. Exact build steps and result

```bash
cd /home/alfi/Active/tetrlio
git clone https://github.com/SoRA-X7/hikari_rei third_party/hikari_rei
git -C third_party/hikari_rei checkout 21b63c652f232d64016b2af72876d7a4b0e238fd
(cd third_party/hikari_rei && cargo build --release)
```

`Cargo.toml`: `hikari_rei` 0.2.0, edition 2024, dependencies `clap`, `rayon`,
`serde`, `serde_json` (crates.io, pinned by `Cargo.lock`), release profile with
`lto = "thin"`, `codegen-units = 1`; default feature `fast-registration`.
No system libraries, no submodules, no GPU.

Observed build tail (exit code 0):

```
   Compiling hikari_rei v0.2.0 (/home/alfi/Active/tetrlio/third_party/hikari_rei)
    Finished `release` profile [optimized] target(s) in 12.25s
```

Reproduce the binary identity:

```bash
sha256sum third_party/hikari_rei/target/release/hikari_rei
# 2f746bf37872cf13b63b9780dc4bfd171d08f3e32af296a3a59723704afde51d
```

---

## 4. TBP protocol, as actually implemented by the pinned commit

Everything below was verified against **this** binary (source in
`third_party/hikari_rei/src/{protocol.rs,board.rs,search.rs}` plus live probes),
not only against the TBP MVP spec.

### 4.1 Lifecycle used by the adapter

```
engine → info                     {"type":"info", ...}            (on launch)
adapter → rules                   {"type":"rules"}
engine → ready                    {"type":"ready"}
adapter → start                   {board, queue, hold, combo, back_to_back}
adapter → suggest                 {"type":"suggest"}
engine → suggestion               {"moves":[...], "move_info":{...}, "board":{...}, "queue":[...]}
... repeat start/suggest for every piece ...
adapter → quit                    {"type":"quit"}
```

* A **valid `start` has no reply**. The worker starts pondering and publishes
  its snapshot only when `suggest` arrives; the adapter therefore treats the
  first line after `suggest` as the reply.
* An invalid message emits `{"type":"error","reason":...}` instead. Because a
  rejected `start` produces no acknowledgement, its error line is consumed by
  the following `wait_for(("suggestion","error"))` and the adapter falls back
  for that move — the engine remains alive and is retried on the next piece.
* The adapter sends a fresh `start` for **every piece** (no `play`/`new_piece`
  session). That restarts Hikari's DAG each move (a strength handicap), but it is
  robust against our fallback path, which may not play the engine's move.
* The engine accepts `rules` with no fields (`randomizer` defaults to
  `seven_bag`) and also `{"randomizer":"unknown"}`.

### 4.2 Board: 24 rows, bottom-first — we send our bottom 24 rows

Source (`protocol.rs::parse_position`): wire row index `y` is copied to Hikari's
bottom-up row `rows[y]` for `y < HEIGHT = 24`; for `y >= 24` a non-empty row is
rejected with `"Hikari supports occupied rows 0 through 23"` (empty rows above
23 are accepted and ignored). Cells are JSON `null`/`false`/`0` for empty;
anything else is occupied.

Live evidence from the probe:

| Wire board sent | Result |
|---|---|
| 24 bottom-first rows, all empty | accepted; engine echoes a 24-row board |
| 40 bottom-first rows, all empty (our top 16 empty) | accepted |
| 40 rows with one cell at wire row 23 (our row 16) | accepted; echo `rows[23]` has that bit |
| 40 rows with one cell at wire row 24 (our row 15) | `{"type":"error","reason":"Hikari supports occupied rows 0 through 23"}` |

The suggestion coordinates are in the same 24-row bottom-up frame, so a wire
row `y` is our top-down row `39 - y` (the two boards share the floor row). A
piece placed on Hikari's top row (wire 23) lands on our row 16 — still inside
our 40-row board — so the inherited `tbp.tbp_move_cells(move, 40)` decode is
correct for every suggestion and needs no normalisation (unlike RIKU).

**Adapter choice:** send **our rows 39…16** (bottom-first). This is
`TBPProfile.board_rows = 24` in `build_start_message`, which slices the bottom
24 rows of the 40-row board. Sending 40 rows would error whenever our stack
reaches our row 15 or above, turning the whole move into a fallback; sending 24
rows keeps the engine playing with a **documented handicap**: occupancy above
our row 16 is invisible to Hikari and is not represented on its board.

### 4.3 Queue: `queue[0]` is the current piece (`current_first`)

`Search::start` stores the sent queue as the search queue and `best_move()` /
`play` treat `queue.first()` as the active piece. Empirically, launching with
`--no-hold` and `queue = ["S","I","O",...]` produces a suggestion of type **S**;
a queue beginning with `T` never produces an S first placement by accident.
The adapter therefore sends `[current, *previews]` (`queue_mode="current_first"`,
the opposite of the Cold Clear 2 `reserve_first` workaround).

Hold semantics are consistent with our arena in both directions:

* empty hold → Hikari's *empty-hold* move holds the current piece and places
  `queue[1]`; our hold action with `hold=None` places `preview(1)[0]` (=`queue[1]`).
* non-empty hold → Hikari places the held piece and stores the current one; our
  hold action places `state.hold`.

The suggested `location.type` is the **physical** piece to place; when it
differs from `state.current.name`, the adapter requires the hold variant of that
placement (the inherited geometry matcher does this).

### 4.4 Combo (`ren`) — `combo_offset = 1`

`parse_position` does `board.ren = combo.max(0)`, and Hikari's `Board.ren` is
the number of **already completed consecutive clears** (its lock increments
`ren`; attack uses `REN_ATTACKS[ren]`). TETR.IO's `state.combo` is `-1` when no
combo is active and `0` after the first clear, so the correct wire value is
`combo + 1` clamped at 0.

The engine echoes its parsed board in every `suggestion`, which makes the mapping
directly checkable. Live probe (same position, only `combo` changed):

| TETR.IO `state.combo` | wire `combo` sent | `suggestion.board.ren` echoed |
|---|---|---|
| `-1` | `0` | `0` |
| `0` | `1` | `1` |
| `2` | `3` | `3` |
| `5` | `6` | `6` |
| (raw) `-1` | `-1` | `0` (clamped by the engine) |

This matches `TBPProfile(combo_offset=1)` — the same conversion Cold Clear 2
needs. The match runner and tests assert the echo, not just the request.

### 4.5 Back-to-back: JSON boolean required

`parse_position` calls `back_to_back.as_bool()`. Sending `1` produces
`{"type":"error","reason":"back_to_back must be a boolean"}`; sending `true` /
`false` is echoed as `suggestion.board.back_to_back`. The adapter sends
`bool(state.b2b_active)` (`TBPProfile.b2b_type="bool"`).

### 4.6 Suggestion format and geometry

```json
{"type":"suggestion",
 "position_id": 7,
 "moves":[{"location":{"type":"T","orientation":"north","x":1,"y":0},"spin":"none"}],
 "move_info":{"search":{"nodes":184075,"edges":188532,"expanded":2724,...},
              "chosen":{...},"plan":[...],"path":{...}},
 "board":{"rows":[0,...24],"back_to_back":false,"hold":null,"bag":0,"ren":0},
 "queue":["T","I","O","S","Z"]}
```

* `x`/`y` are the **TBP true-rotation centre**, `y = 0` at the floor, exactly
  the convention `tbp.tbp_move_cells` decodes. Verified for all seven pieces on
  an empty board (our top-down cells):

  | Piece | Wire move | Our cells | Action |
  |---|---|---|---|
  | T | north, x=1, y=0 | `(0,39),(1,38),(1,39),(2,39)` | 0 |
  | I | north, x=4, y=0 | `(3,39),(4,39),(5,39),(6,39)` | 6 |
  | O | north, x=8, y=0 | `(8,38),(9,38),(8,39),(9,39)` | 16 |
  | S | north, x=5, y=0 | `(4,39),(5,38),(5,39),(6,38)` | 8 |
  | Z | north, x=8, y=0 | `(7,38),(8,38),(8,39),(9,39)` | 14 |
  | J | north, x=1, y=0 | `(0,38),(0,39),(1,39),(2,39)` | 0 |
  | L | north, x=7, y=0 | `(6,39),(7,39),(8,38),(8,39)` | 12 |

  Every one mapped to a legal action with an exact four-cell match. The engine
  may emit `spin: "mini"|"full"`; the adapter ignores it (our engine
  re-classifies spins with SRS+/TETR.IO rules).
* `move_info.search.nodes` is the **retained graph size for the current
  position**, not the number of nodes expanded for this move. The adapter adds
  it to `stats.nodes_total` and keeps the full `move_info` in
  `stats.last_move_info`; docs/tables label it accordingly.
* `board`/`queue` are the engine's own view and are used by the tests to verify
  the board slice and the queue/combo/b2b conventions live.
* No `randomizer`/`bag` state is sent, so Hikari starts from an unknown bag
  (`bag = 0`) and speculates future pieces itself; hidden bag information is
  never leaked to the opponent.

---

## 5. Adapter behaviour (`HikariAgent`)

* **Lazy process launch**: importing `hikari.py`, creating `HikariAgent`, and
  collecting pytest tests never spawn a process. The engine starts on the first
  `choose_action()` that needs it.
* **Command**: `/path/to/hikari_rei tbp --threads 1` (plus optional
  `--max-nodes`, `--no-hold`). `think_time` defaults to **20 ms**: after sending
  `start` the adapter sleeps, letting Hikari's continuous search expand the
  graph, then asks for a suggestion.
* **Pytest guard**: inherited — launching is refused under pytest unless
  `allow_in_tests=True` is passed; `TETRISRL_TBP_DISABLE=1` is an opt-out.
* **Clean shutdown**: `terminate()` sends `quit`, closes stdin, waits 2 s, then
  kills if needed; reader threads are daemonised.
* **Timeouts / errors**: configurable suggestion deadline (default 5 s) and
  handshake deadline (10 s). On timeout or protocol error the session is closed,
  the counter is incremented, and the move is played by the heuristic.
* **Validation**: `moves[0]` is converted by absolute four-cell geometry and must
  be a legal action; if it is not expressible (tuck/slide-only), the heuristic
  plays and `invalid_suggestions`/`fallbacks` are incremented. Alternative moves
  are not shopped for; Hikari emits at most one.
* **Counters** (`agent.stats`): the inherited set plus `nodes_total` from
  `move_info.search.nodes`. Missing binary → `protocol_errors += 1` and fallback,
  never a crashed match.
* **Environment override** for the binary: `TETRISRL_HIKARI_BIN`.

---

## 6. Tests

```bash
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_hikari.py -v
# 19 passed in 0.95s
```

Pure-Python tests (always run): pinned commit, path/env resolution, profile
values, launch command, start-message queue/board/combo/B2B encoding, 24-row
slice (a block on our row 15 is never transmitted), all seven live wire moves
decoding to the expected cells and legal actions, hold and empty-hold mapping,
missing-binary fallback.

Engine tests (auto-skip when the binary is absent):

* handshake reports `Hikari Rust` 0.2.0 / SoRA_X7 / reference commit;
* live `start` → `suggest` echoes `board.ren == combo+1`, `back_to_back`, a
  24-row board with our row 39 at wire row 0 and our row 16 at wire row 23,
  `queue[0] == current`, and a non-empty move;
* a 40-row `start` with an occupied wire row 24 is rejected with
  `Hikari supports occupied rows 0 through 23`;
* 6 sequential `choose_action` calls are legal, with no protocol error/timeout
  and non-zero search telemetry;
* the inherited pytest guard refuses to launch without `allow_in_tests=True`;
* a 40-piece `VersusMatch` vs the heuristic completes with
  `invalid_actions == [0, 0]`.

Full suite at the final run of this work: **247 passed** in 20.79 s
(`.venv/bin/python -m pytest`; the count includes the other opponent adapters
present in the tree).

---

## 7. Actual match results

Command (exactly as required):

```bash
.venv/bin/python scripts/run_hikari_match.py \
    --games 10 --opponent heuristic random \
    --max-pieces 300 --think-ms 20 --threads 1 \
    --json results/hikari_match_1795192607.json
```

Configuration: `tetrio_s2` ruleset, one engine process per game, paired seeds
`0..9`, `max_pieces=300`, 20 ms/move, 1 search worker, JSON report
`results/hikari_match_1795192607.json` (gitignored).

### 7.1 Result summary

| Series | Score (W–L–D) | Win rate | Wilson 95% CI | Games | Avg ticks | Wall time |
|---|---|---|---|---|---|---|
| Hikari vs heuristic | **6–4–0** | **60%** | [31.3%, 83.2%] | 10 | 79.7 | 21.9 s |
| Hikari vs random | **10–0–0** | **100%** | [72.3%, 100%] | 10 | 18.6 | 4.3 s |

Console output (abridged to the game lines):

```
--- Hikari (TBP subprocess) vs heuristic ---
  game  1 seed=0     win   reason=top_out_b              ticks=88   accepted=88   fallbacks=0    invalid=0   topout=block_out          2.49s
  game  2 seed=1     loss  reason=top_out_a              ticks=41   accepted=34   fallbacks=7    invalid=7   topout=-                  1.24s
  game  3 seed=2     win   reason=top_out_b              ticks=91   accepted=91   fallbacks=0    invalid=0   topout=block_out          2.64s
  game  4 seed=3     win   reason=top_out_b              ticks=98   accepted=98   fallbacks=0    invalid=0   topout=block_out          2.65s
  game  5 seed=4     win   reason=top_out_b              ticks=92   accepted=92   fallbacks=0    invalid=0   topout=block_out          2.45s
  game  6 seed=5     loss  reason=top_out_a              ticks=108  accepted=108  fallbacks=0    invalid=0   topout=-                  2.92s
  game  7 seed=6     win   reason=top_out_b              ticks=85   accepted=84   fallbacks=1    invalid=1   topout=block_out          2.27s
  game  8 seed=7     win   reason=top_out_b              ticks=46   accepted=46   fallbacks=0    invalid=0   topout=block_out          1.24s
  game  9 seed=8     loss  reason=top_out_a              ticks=111  accepted=109  fallbacks=2    invalid=2   topout=-                  2.97s
  game 10 seed=9     loss  reason=top_out_a              ticks=37   accepted=37   fallbacks=0    invalid=0   topout=-                  1.00s
  SUMMARY vs heuristic: 6-4-0 (60.0% wins) over 10 games; engine suggestions 797, accepted 787, fallbacks 10 (rate 1.25%)

--- Hikari (TBP subprocess) vs random ---
  game  1 seed=0     win   reason=top_out_b              ticks=17   accepted=17   fallbacks=0    invalid=0   topout=block_out          0.39s
  ... (all ten games top_out_b, 16–24 ticks)
  game 10 seed=9     win   reason=top_out_b              ticks=24   accepted=23   fallbacks=1    invalid=1   topout=block_out          0.56s
  SUMMARY vs random: 10-0-0 (100.0% wins) over 10 games; engine suggestions 186, accepted 184, fallbacks 2 (rate 1.08%)
```

No match crashed, timed out, restarted an engine, or had an action rejected by
the versus layer (`invalid_actions == [0, 0]` in every game). All four losses
ended by `top_out_a` (Hikari itself topped out); all wins ended by `top_out_b`
(the baseline topped out).

### 7.2 Engine telemetry

| Metric | vs heuristic | vs random |
|---|---|---|
| Engine suggestions | 797 | 186 |
| Accepted placements | 787 | 184 |
| Invalid suggestions → heuristic fallback | 10 | 2 |
| Fallback rate | 1.25% | 1.08% |
| Timeouts / protocol errors / restarts | 0 / 0 / 0 | 0 / 0 / 0 |
| `move_info.search.nodes` summed per position | 20,322,182 | 5,861,894 |
| Mean answer latency | 20.28 ms | 20.33 ms |

### 7.3 Per-player averages (10 games each)

**vs heuristic**

| Player | Pieces | Lines | Attack | Sent | Recv | Inserted | T-spins | Tetrises | Max B2B | Holds | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Hikari | 79.7 | 32.8 | 37.7 | 34.7 | 16.3 | 13.3 | 3.6 | 4.7 | 1.6 | 18.7 | 14.6 | 8.1 |
| Heuristic | 79.7 | 45.8 | 20.3 | 16.5 | 34.3 | 30.5 | 1.3 | 1.4 | 1.0 | 29.1 | 16.5 | 13.0 |

Hikari cleared fewer raw lines but generated more attack (T-spins, tetrises,
B2B) and kept a cleaner board on average, yet lost four games by topping out
itself — including a 108-piece game with zero fallbacks and a 111-piece game.
That is consistent with a real handicap rather than a decoding bug: TBP gives
the engine no pending-garbage or opponent information, and Hikari's own versus
rules are not used. This run does **not** isolate the cause.

**vs random**

| Player | Pieces | Lines | Attack | Recv | Inserted | T-spins | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|
| Hikari | 18.6 | 4.1 | 5.2 | 0.0 | 0.0 | 0.6 | 5.8 | 0.4 |
| Random | 18.6 | 0.1 | 0.0 | 4.8 | 4.8 | 0.0 | 22.7 | 60.3 |

Random never generated attack and topped out after ~18 pieces under the first
garbage batches — a sanity check that our arena's attack/garbage reaches the
opponent.

### 7.4 Reproducibility caveat

Paired seeds make the **arena** deterministic (`VersusMatch`, piece bags,
garbage, heuristic), but Hikari's suggestions are **not** bit-reproducible: its
continuous search is bounded by wall-clock think time and worker scheduling, so
a rerun can produce a different move stream and a slightly different score. A
re-run of the same command during fallback investigation (with a logging
subclass, same seeds) produced different per-game outcomes. Replays must
therefore always be based on the recorded action stream, not on re-querying the
engine.

---

## 8. Fallback investigation (10 + 2 invalid suggestions)

The OPPONENTS §6.3 guardrail is < 1% fallback per engine; Hikari measured
**1.25%** vs heuristic. Every invalid suggestion was investigated by replaying
the game with a logging subclass that captured `last_suggestion`, the whole
board, the current/hold pieces and every legal placement of the suggested piece.

Both sampled positions were genuine **tucks/slides**, not coordinate or
orientation errors:

* Seed 1, T suggestion `north x=7 y=0` → cells
  `(6,39),(7,38),(7,39),(8,39)`. Row 38 is occupied at column 6
  (`..#####...`), so a straight drop from column 6 rests one row higher
  (`(7,36),(6,37),(7,37),(8,37)`); reaching the suggested cells requires sliding
  the left cell under the row-38 overhang. Our action space is
  `(rotation, column, hold)` **hard drops**, so this placement is unrepresentable.
* Seed 1, Z suggestion `south x=2 y=12` → cells
  `(1,27),(2,27),(2,28),(3,28)`. A straight drop from column 1 collides at
  `(3,27)` while descending and stops at rows 25/26; the suggested resting
  position is only reachable by a sideways path.

All other 787/797 (heuristic) and 184/186 (random) suggestions mapped exactly
to a legal action. The rate is reported as-is, not hidden: the heuristic plays
those moves, so Hikari is slightly weaker than its own search suggests. The
count is small (n=10 and n=2), so the rate estimate is imprecise.

---

## 9. Compatibility limitations (explicit)

1. **Placement suggester, not a simulator.** Hikari receives a board, queue,
   hold, combo and B2B flag and returns placements. It does not simulate our
   match, attack tables, garbage or Season 2 state. The arena is authoritative.
2. **Hikari rules ≠ TETR.IO Season 2.** The engine's own versus model (24-row
   board, 3-frame spawn, 38-frame line clear, 60-frame garbage, its own attack
   table, up to 8 rows rising) is **not used**. B2B **charging**, **surge**, S2
   cancellation and garbage insertion live only in `tetrisrl`
   (`scoring.py`, `garbage.py`, `engine.py`).
3. **No pending-garbage planning.** TBP has no garbage/opponent message. Hikari
   sees garbage only after it lands on the board we send; it cannot plan around
   incoming attack. This is the largest capability gap.
4. **24-row board truncation.** We send our rows 39…16. A stack reaching our row
  15 or above is invisible to Hikari (and sending 40 rows with such occupancy
   would be rejected outright). This is a documented handicap, not silently
   "fixed".
5. **No 180° rotation, no SRS+.** Hikari implements SRS with its own Mirai-style
   placement generation; TETR.IO SRS+ kick nuances and 180° placements are not
   modelled. Our engine still validates every placement with SRS+; placements
   only reachable through SRS+ are rejected → fallback.
6. **Hard-drop action space vs. reachable-placement search.** Hikari searches
   tucks and spins; our action encoding is hard drops from spawn plus a hold
   choice. Mismatches are counted (1.25% / 1.08%), and are the sole cause of the
   invalids observed.
7. **Search restart per piece.** A fresh `start` every piece rebuilds the DAG;
   simpler and fallback-safe, but weaker than a continuous `play`/`new_piece`
   session (which we cannot use because our fallback may not play its move).
8. **Time-based search.** Suggestions depend on wall-clock think time and worker
   scheduling; the engine is not bit-deterministic across runs (§7.4).
9. **No randomizer state.** The adapter omits TBP `randomizer`, so Hikari
   infers/speculates the bag; deliberate non-leakage and a small handicap.
10. **No strength claim.** 6–4 vs a one-ply heuristic and 10–0 vs random are
    small-sample results on paired seeds, with the engine handicapped as above.

---

## 10. Reproduce everything

```bash
# 1. Clone + build the pinned engine (once)
cd /home/alfi/Active/tetrlio
git clone https://github.com/SoRA-X7/hikari_rei third_party/hikari_rei
git -C third_party/hikari_rei checkout 21b63c652f232d64016b2af72876d7a4b0e238fd
(cd third_party/hikari_rei && cargo build --release)
sha256sum third_party/hikari_rei/target/release/hikari_rei

# 2. Adapter / protocol / lifecycle tests (engine tests auto-run when built)
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_hikari.py -v

# 3. Full suite
.venv/bin/python -m pytest

# 4. Real matches (produced §7)
.venv/bin/python scripts/run_hikari_match.py \
    --games 10 --opponent heuristic random \
    --max-pieces 300 --think-ms 20 --threads 1

# 5. Quick plumbing run
.venv/bin/python scripts/run_hikari_match.py --games 2 --max-pieces 100 \
    --opponent heuristic random
```

The engine tests skip automatically when
`third_party/hikari_rei/target/release/hikari_rei` is absent
(`hikari_available()`), so the suite still runs on a clean checkout. Override
the binary with `TETRISRL_HIKARI_BIN=/path/to/hikari_rei`.

---

## 11. Non-claims

* We did **not** modify Hikari's source; the clone is at the pinned commit.
* We did **not** use Hikari's own versus/attack logic. Every competitive rule was
  enforced by `tetrisrl` under `tetrio_s2`.
* We did **not** verify Hikari's strength against strong human/TETR.IO
  opposition; the results are against an in-repo one-ply heuristic and a random
  agent, over 10 paired seeds each.
* The 1.25% fallback rate exceeds the < 1% guideline; its cause (tuck-only
  placements) was verified on samples, and it is reported rather than patched.
