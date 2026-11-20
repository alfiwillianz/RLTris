# Integration: Cold Clear (original) via its C ABI

**Status: REAL INTEGRATION EXECUTED.** Cold Clear (the original 2022 bot, not
Cold Clear 2) was cloned at a pinned commit, built as a shared library from its
`c-api` crate, loaded into Python with `ctypes`, and played **30 real versus
matches** in `tetrisrl.environment.versus.VersusMatch` under the project's
`tetrio_s2` ruleset. Every engine decision was mapped to a legal placement
action; the run included a garbage probe that measured whether the per-move
incoming-garbage argument changes the engine's suggestion.

Verification date: **2026-11-20** · Host: Linux x86-64, rustc/cargo 1.100.0,
Python 3.12 (`/home/alfi/Active/tetrlio/.venv/bin/python`).

The point of this integration is the one capability Cold Clear 2's TBP path
lacks: **`cc_request_next_move(bot, incoming)` accepts a pending-garbage count
for every decision**. The engine can therefore plan around garbage it expects to
receive, not only garbage already on its board.

---

## 1. TL;DR

| Item | Value |
|---|---|
| Engine | [Cold Clear](https://github.com/MinusKelvin/cold-clear) (`MinusKelvin/cold-clear`) |
| Pinned commit | `279edd7c3177ff8077f6a930193397814b281f27` (2022-01-18, "don't count long moves that are part of tspin doubles") |
| Licence | **MPL-2.0** (weak, file-scoped copyleft) |
| Build | `cargo build --release -p c-api` → succeeded in 32.48 s (warnings, no errors) |
| Library | `third_party/cold-clear/target/release/libcold_clear.so`, 1,531,360 bytes, SHA-256 `189bf1233b60de12b6553dcf914907c77a16f4fa01e28a5d7c25059953753892` |
| Crate layout | `c-api/Cargo.toml`: `[lib] name = "cold_clear"`, `crate-type = ["cdylib", "staticlib"]` |
| Integration mode | **Dynamic linking only** (`ctypes.CDLL`); no Cold Clear source copied into RLTris |
| ABI | `cc_launch_with_board_async`, `cc_request_next_move`, `cc_poll_next_move`, `cc_reset_async`, `cc_destroy_async`, `CCMove`, `CCWeights`, `CCOptions` |
| Adapter | `tetrisrl/agents/opponents/coldclear1.py` (`ColdClear1Agent`, `name = "coldclear1"`) |
| Runner | `scripts/run_coldclear1_match.py` |
| Tests | `tetrisrl/tests/test_opponents_coldclear1.py` — **11 passed** |
| Real matches | **30 games**: 20 at 20k nodes and 10 at 60k nodes (details §7) |
| Garbage-aware evidence | Pending garbage changed the suggestion in **29/212** (13.7%) and **19/190** (10.0%) probed decisions |
| Fallbacks | 0/1603 accepted decisions at 20k; 1/1411 at 60k (0.07%) |
| Engine's role | **Placement suggester only.** RLTris owns attack, garbage, cancellation, B2B charging, Surge and top-out. |

**What this is not:** it is not a Season 2 model inside Cold Clear. The engine
receives a garbage *count*, not a queue; it has no Surge/charge concept, no
SRS+, and no 180° rotation. These gaps are documented in §8.

---

## 2. Files

| File | Purpose |
|---|---|
| `tetrisrl/agents/opponents/coldclear1.py` | ctypes ABI wrapper, board/queue/hold encoding, move→action mapping, `ColdClear1Agent`, counters |
| `tetrisrl/tests/test_opponents_coldclear1.py` | 11 tests: availability, encoding, guard, real search, incoming garbage, timeout, lifecycle, versus smoke |
| `scripts/run_coldclear1_match.py` | Real-match runner with JSON report and `--garbage-probe` |
| `third_party/COLD_CLEAR_NOTICE.md` | Provenance, MPL-2.0 obligations, pinned commit, library hash |
| `docs/integration_coldclear1.md` | This document |
| `third_party/cold-clear/` | Local clone + build tree (not vendored into the Python package; treat as a build artifact) |

No other project file was modified by this integration. `tbp.py`,
`agents/__init__.py`, the dashboard and the arena were left untouched.

> Note: the working tree contained concurrent work by other agents (Blockfish,
> RIku, dashboard). The Cold Clear adapter does not import or modify them.

---

## 3. Build

Exact commands:

```bash
cd /home/alfi/Active/tetrlio
mkdir -p third_party
git clone https://github.com/MinusKelvin/cold-clear third_party/cold-clear
git -C third_party/cold-clear checkout 279edd7c3177ff8077f6a930193397814b281f27
(cd third_party/cold-clear && cargo build --release -p c-api)
```

Observed (exit code 0):

```
warning: use of deprecated method `enum_map::EnumMap::<K, V>::is_empty`
warning: `cold-clear` (lib) generated 6 warnings
warning: unused return value of `Box::<T>::from_raw` that must be used
warning: `c-api` (lib) generated 1 warning
    Finished `release` profile [optimized] target(s) in 32.48s
```

Artifacts:

```bash
ls -l third_party/cold-clear/target/release/libcold_clear.{so,a}
# -rwxr-xr-x ... 1531360 libcold_clear.so
# -rw-r--r-- ... 16725444 libcold_clear.a
sha256sum third_party/cold-clear/target/release/libcold_clear.so
# 189bf1233b60de12b6553dcf914907c77a16f4fa01e28a5d7c25059953753892
```

The C ABI built on the first attempt on Rust 1.100.0 with no source patches, so
the fallback (the workspace's TBP binary) was **not** used. For completeness,
the workspace also contains a `tbp` crate (package name `cc-tbp`, with
`src/main.rs`); it was inspected but not built.

The default library path is
`third_party/cold-clear/target/release/libcold_clear.so`; override it with
`TETRISRL_COLDCLEAR1_LIB=/path/to/libcold_clear.so` or the `library=` argument.

---

## 4. C ABI, as used

### 4.1 Constants and structs

From `c-api/coldclear.h` (verified against `c-api/src/lib.rs`):

* `CCPiece`: `I=0 O=1 T=2 L=3 J=4 S=5 Z=6`.
* `CCMovementMode`: `CC_0G=0, CC_20G=1, CC_HARD_DROP_ONLY=2`.
* `CCSpawnRule`: `CC_ROW_19_OR_20=0, CC_ROW_21_AND_FALL=1`.
* `CCBotPollStatus`: `CC_MOVE_PROVIDED=0, CC_WAITING=1, CC_BOT_DEAD=2`.
* `CCMove`: `bool hold`, `uint8_t expected_x[4]`, `uint8_t expected_y[4]`,
  `uint8_t movement_count`, `CCMovement movements[32]`, then `nodes`, `depth`,
  `original_rank`.
* `CCOptions`: movement mode, spawn rule, PC priority, `min_nodes`, `max_nodes`,
  `threads`, `use_hold`, `speculate`.
* `CCWeights`: the full 44-int evaluation weight struct plus three bools.

The ctypes mirrors were checked against the compiled library: on this x86-64
build `sizeof(CCMove)=152`, `sizeof(CCWeights)=180`, `sizeof(CCOptions)=28`,
matching the C layout exactly. No parsing of JSON or text is involved.

### 4.2 Launch / decision lifecycle

```text
cc_default_options(&options)           # then override min_nodes/mode/...
cc_default_weights(&weights)           # stock evaluation weights
bot = cc_launch_with_board_async(
          &options, &weights, NULL,    # NULL book
          field,                       # bool[400], bottom-left row-major
          bag_remain,                  # bitmask; 0 => full bag
          hold_or_NULL,                # CCPiece*
          b2b,                         # bool
          combo,                       # u32 consecutive clears
          queue, count)                # CCPiece[current, previews...]
cc_request_next_move(bot, incoming)    # <-- per-move garbage hint
loop:
    status = cc_poll_next_move(bot, &move, NULL, NULL)
    status==CC_WAITING   -> sleep ~0.5 ms and poll again (until timeout)
    status==CC_MOVE_PROVIDED -> use move
    status==CC_BOT_DEAD  -> fallback
cc_destroy_async(bot)                  # always, in a finally block
```

### 4.3 Board encoding

`field` is **400 booleans in row-major order with index 0 = bottom-left**:
`index = y_bottom_up * 10 + x`. Our `Board.rows[0]` is the **top** row, so the
encoder emits `field[(39 - y_ours) * 10 + x] = occupied(y_ours, x)`. This was
verified with a synthetic board containing marks on the bottom row, the second
row and the top row (`test_board_field_is_bottom_left_row_major`).

### 4.4 Queue, hold, combo, B2B, bag

* `queue = [current, *preview(5)]` (6 pieces). The current piece is
  `queue[0]`, so the engine can evaluate both placing it and holding it.
* `hold` is a pointer to the current hold piece, or `NULL`.
* `b2b = state.b2b_active`; `combo = max(0, state.clear_state.combo + 1)`.
  Cold Clear's combo is the number of consecutive line clears, whereas
  TETR.IO's displayed combo is 1-based differently; the `+1` conversion is
  documented in the header and matches the TBP adapter.
* `bag_remain = 0`, which `Board::new_with_state` interprets as "all seven
  pieces remain". The six explicit queue entries are authoritative for the
  decision. `speculate=False` is the default because our engine does not expose
  the randomizer's bag state, and feeding a wrong bag would corrupt
  speculation. This is a small strength handicap, deliberately chosen over
  leaking hidden randomizer state.

### 4.5 Move decoding

`CCMove.expected_x/expected_y` are absolute cell coordinates with `(0,0)` at the
bottom-left. The adapter converts them to our top-down coordinates with
`(x_ours, y_ours) = (x_cc, 39 - y_cc)`, validates bounds and four distinct
cells, and matches the resulting cell set against every legal placement in
`GameState.legal_actions()`.

Matching is geometric plus the hold flag—rotation names are never trusted. This
is the same robust strategy used by the Cold Clear 2 TBP adapter. If a cell set
matches but the hold flag does not, the cell match is used as a last resort; if
no legal placement matches, the move is counted as inexpressible and the
heuristic plays instead.

### 4.6 Why one bot per decision (and not `cc_reset_async`)

`cc_reset_async(bot, field, b2b, combo)` resets the **board, B2B and combo
only**. It does not update the hold piece or the queue, so after a hold action
or a garbage insertion there is no C-API call that makes a persistent bot's
internal state exactly match ours. The adapter therefore calls
`cc_launch_with_board_async` once per decision and destroys the bot immediately
after the poll completes. Consequences:

* every decision sees the exact board, hold, queue, B2B, combo and incoming
  garbage count;
* `incoming` is safe to vary per call;
* the engine's search tree is rebuilt per piece (the same handicap as the
  TBP adapter's `start`-per-piece strategy).

`cc_reset_async` is declared and typed in the wrapper for completeness, but the
agent does not rely on it.

### 4.7 Options used

| Option | Value | Reason |
|---|---|---|
| `mode` | `CC_HARD_DROP_ONLY` | Match our hard-drop placement action space and avoid tucks that cannot be encoded; also faster. `zero_g` can be selected for probing. |
| `spawn_rule` | `CC_ROW_21_AND_FALL` | Closest to our spawn geometry (TETR.IO spawns high and falls); configurable. |
| `min_nodes` | 20,000 default (60,000 in the second series) | The C ABI has no wall-clock think parameter; node count is the only think-budget control. ~20k nodes ≈ 20–35 ms/decision here. |
| `max_nodes` | `4 * min_nodes` | Safety cap; the bot is destroyed as soon as a move is returned. |
| `threads` | 1 | Deterministic, reproducible; `threads=0` would panic. |
| `use_hold` | true | Hold is part of our action space. |
| `speculate` | false | See §4.4. |
| Book | `NULL` | No opening book. |
| PC loop | off | Season 2 arena does not use PC-loop planning; default `None`. |

---

## 5. Adapter behaviour (`ColdClear1Agent`)

* **Lazy, guarded loading**: importing the module, constructing an agent, and
  pytest collection never call `CDLL`. Loading is refused under pytest unless
  `allow_in_tests=True`, and can be disabled with
  `TETRISRL_COLDCLEAR1_DISABLE=1`.
* **Timeouts**: `timeout` (default 5 s) bounds the poll loop. On timeout the bot
  is destroyed in a `finally` block and the heuristic plays; the next decision
  starts a fresh bot.
* **Fallbacks**: missing library, disabled loading, a dead engine, a malformed
  move, or a legal-but-inexpressible placement all fall back to
  `HeuristicAgent` and increment distinct counters. A broken engine never
  crashes a match.
* **Counters** (`agent.stats`): `searches`, `accepted`, `invalid_moves`,
  `fallbacks`, `timeouts`, `errors`, `engine_dead`, `nodes_total`,
  `answer_latency_ms`, `incoming_searches`, `garbage_probes`,
  `garbage_probe_differences`, `garbage_probe_errors`, `probe_searches`,
  `last_incoming`, `last_move`, `last_error`. `as_dict()` also reports
  `mean_answer_latency_ms` and `nodes_per_search`.
* **Garbage probe** (`garbage_probe=True`): when a decision has pending
  garbage, the agent performs a second search on the identical state with
  `incoming=0` and records whether the suggestion (cell set or hold flag)
  changed. This measures garbage-awareness without changing the move actually
  played.
* **Determinism/lifecycle**: `reset(seed)` clears counters and re-enables the
  agent; `terminate()` marks it closed and drops the library handle. Because
  each decision destroys its bot, there is no worker thread or process left
  behind. Replays record the actions, so match replay does not depend on
  re-running the engine.

---

## 6. Tests

```bash
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_coldclear1.py
# 11 passed
.venv/bin/python -m pytest
# 193 tests collected; full suite passed
```

Coverage:

1. availability/path resolution and env override;
2. bottom-left row-major field encoding;
3. geometric move→action mapping (including hold);
4. invalid move rejection;
5. pytest-collection guard (no library load without `allow_in_tests`);
6. `TETRISRL_COLDCLEAR1_DISABLE=1` guard;
7. one real search returning a legal action (5 decisions);
8. a real search with `incoming=10` proving the per-call garbage argument is
   accepted (`last_incoming == 10`);
9. timeout → heuristic fallback, then clean recovery with a new agent;
10. lifecycle: `reset`/`terminate`/re-`reset`, idempotent shutdown;
11. real `VersusMatch` smoke game against `HeuristicAgent` (40-piece cap) with
    zero versus-layer invalid actions.

Real-engine tests are skipped automatically when the `.so` is absent.

---

## 7. Real matches

### 7.1 Commands

```bash
# 20-game series at 20k nodes, garbage-aware probe enabled
.venv/bin/python scripts/run_coldclear1_match.py --games 10 \
    --opponent heuristic --opponent random --garbage-probe \
    --json results/coldclear1_match_report.json

# second series: 10 heuristic games at 60k nodes
.venv/bin/python scripts/run_coldclear1_match.py --games 10 \
    --opponent heuristic --nodes 60000 --garbage-probe \
    --json results/coldclear1_match_report_60k.json
```

Configuration: `tetrio_s2` ruleset, `max_pieces=400`, paired seeds `0..9`,
Cold Clear 1 as agent A, baseline as agent B, one bot per decision. JSON
reports are under `results/` (gitignored).

### 7.2 Results summary

| Series | Score (W–L–D) | Games | Avg ticks | Accepted | Invalid | Fallbacks | Timeouts/errors | Wall time |
|---|---|---|---|---|---|---|---|---|
| 20k nodes vs heuristic | **8–2–0** | 10 | 160.3 | 1603 | 0 | 0 | 0 / 0 | 56.7 s |
| 20k nodes vs random | **10–0–0** | 10 | 20.8 | 208 | 0 | 0 | 0 / 0 | 5.3 s |
| 60k nodes vs heuristic | **10–0–0** | 10 | 141.2 | 1411 | 1 | 1 | 0 / 0 | 132.8 s |

All matches ended `top_out_b` (baseline topped out) except the two 20k losses,
which ended `top_out_a` after long games (364 and 309 ticks). No match hit the
400-piece cap. `VersusMatch.invalid_actions == [0, 0]` in every game: the arena
never had to reject or substitute an action at its own layer.

The 20k losses are real and are not hidden: at 20k nodes the engine spends only
~20–35 ms per decision, which is weaker than the 60 ms/move Cold Clear 2
configuration in `docs/BENCHMARKS_INTEGRATION.md`. At 60k nodes the same seeds
went 10–0.

### 7.3 Engine telemetry

| Metric | 20k vs heuristic | 20k vs random | 60k vs heuristic |
|---|---|---|---|
| Total searches (includes probes) | 1,815 | 208 | 1,602 |
| Accepted placements | 1,603 | 208 | 1,411 |
| Inexpressible suggestions | 0 | 0 | 1 |
| Fallback rate | 0.00% | 0.00% | 0.07% |
| Timeouts / errors / dead | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| Nodes total | 36,343,606 | 4,164,870 | 96,158,106 |
| Nodes per search | 20,024 | 20,023 | 60,024 |
| Decisions with pending garbage | 212 | 0 | 190 |
| Garbage probes | 212 | 0 | 190 |
| Probes where the suggestion changed | **29 (13.7%)** | — | **19 (10.0%)** |
| Probe errors | 0 | 0 | 0 |

The one 60k fallback was a legal engine placement our hard-drop action space
could not express (a 3-move tuck path, `movement_count=3`); the heuristic played
that one piece. This is the expected hard-drop-vs-reachable-placement gap, not a
parse failure.

### 7.4 Garbage-awareness

`cc_request_next_move(bot, incoming)` is called with
`state.pending_garbage` for every decision. The probe confirms the engine
actually uses it: on identical boards, changing `incoming` from the pending
count to 0 changed the chosen placement in 29/212 (13.7%) and 19/190 (10.0%) of
probed decisions. A direct probe on an empty board also showed different
placements for `incoming=0` and `incoming=4` while both remained legal.

This is the capability the TBP path lacks. It is still only a **count** hint:
the engine does not know the garbage hole columns, the queue order, or when each
batch will land.

### 7.5 Per-player averages (60k vs heuristic, 10 games)

| Player | Pieces | Lines | Attack | Sent | Recv | Inserted | T-spins | Tetrises | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|---|---|
| Cold Clear 1 | 141.2 | 69.8 | 56.0 | 51.4 | 23.5 | 18.9 | 2.0 | 6.8 | 5.7 | 2.3 |
| Heuristic | 141.2 | 78.0 | 29.9 | 23.5 | 51.0 | 44.5 | 2.9 | 1.2 | 22.0 | 18.1 |

Cold Clear cleared fewer raw lines but generated ~1.9× the attack (tetrises,
T-spins, B2B), kept a much lower board, and buried the heuristic under ~51
incoming lines per game. At 20k nodes the same pattern held with lower
efficiency: engine attack 61.7 vs heuristic 34.5, engine final height 8.6 vs
19.8, but two games went long enough for the engine to top out first.

### 7.6 Interpretation limits

These are 10–20 games per series on paired seeds, not a strength estimate.
The 8/10 result has a Wilson 95% interval of roughly **[49%, 94%]**; 10/10 is
roughly **[72%, 100%]**. The baselines are a one-ply heuristic and uniform
random. Beating them is not evidence of TETR.IO-level strength.

---

## 8. Compatibility limitations (explicit)

1. **Guideline SRS, not SRS+.** Cold Clear's `libtetris` uses the guideline
   I/JLSTZ kick tables. TETR.IO's SRS+ mirrors the I kicks; any placement that
   needs an SRS+-only kick cannot be proposed by the engine. Our engine still
   validates and applies the chosen placement with SRS+.
2. **No 180° rotation.** `PieceMovement` has only `Left`, `Right`, `Cw`, `Ccw`,
   `SonicDrop`; the engine cannot propose 180 spins or 180-only tucks.
3. **Pre-Season-2 attack/B2B model.** The engine's internal evaluation knows
   only a boolean B2B flag and an additive combo count. It has no B2B charging,
   Surge, All-Mini+, opener phase or clutch clear. Its attack table is not used:
   `tetrisrl` classifies spins and computes Season 2 attack for every
   placement. **Our arena owns Season 2.**
4. **Garbage is a count, not a queue.** `incoming` is a hint of how many lines
   are expected after the next placement. Hole columns, batch timing, the
   queue cap and cancellation state are not communicated. Garbage-aware
   behaviour is therefore approximate.
5. **No randomizer/bag state.** The adapter sends `bag_remain=0` and disables
   speculation rather than leaking or guessing our seven-bag state. This is a
   deliberate handicap.
6. **One launch per decision.** The search tree is discarded every piece
   because `cc_reset_async` cannot update hold/queue. This is weaker than a
   continuous `play`/`new_piece` session and is the main performance cost.
7. **Hard-drop action space vs. move generation.** `mode=CC_HARD_DROP_ONLY`
   removes most tucks, but the engine can still propose placements our
   `(rotation, column, hold)` hard-drop encoder cannot express. Counted:
   0/1603 at 20k, 1/1411 at 60k (0.07%); those pieces are played by the
   heuristic.
8. **Think budget.** The C ABI has no time limit; `min_nodes` is the only
   control. 20k nodes is fast but weak (8–2); 60k nodes is stronger (10–0) and
   ~3× slower. This is an engineering trade-off, not a property of the engine.
9. **Platform.** The default artifact is a Linux x86-64 `.so`; other platforms
   must build the library and point `TETRISRL_COLDCLEAR1_LIB` at it.
10. **No Season 2 strength claim.** These matches say only that an unmodified
    Cold Clear library made every placement for one side of 30 deterministic
    arena matches and won under *our* ruleset.

---

## 9. MPL-2.0 compliance

* Cold Clear is **MPL-2.0**. Integration is **dynamic linking at runtime**
  (`ctypes.CDLL`); the library is a separate, unmodified build of the upstream
  `c-api` crate.
* **No Cold Clear source was copied into any `tetrisrl` file.** The adapter
  contains only our own ctypes declarations, encoding logic and agent code.
* The clone at `third_party/cold-clear/` is unmodified and pinned at
  `279edd7c3177ff8077f6a930193397814b281f27`; the upstream `LICENSE` is kept in
  the clone. `third_party/COLD_CLEAR_NOTICE.md` records the provenance and
  obligations.
* MPL §3.3 permits distribution of a Larger Work under other terms provided the
  MPL Source Code Form and notices are made available. Anyone redistributing
  the compiled `.so` must make the corresponding source available (the pinned
  commit is the Source Code Form; rebuild with `cargo build --release -p c-api`).
* If the clone is modified later, the modified MPL files must remain MPL-2.0
  and their source must be published. This integration needs no patches.

---

## 10. Reproduce

```bash
cd /home/alfi/Active/tetrlio

# 1. Clone + build the pinned engine
git clone https://github.com/MinusKelvin/cold-clear third_party/cold-clear
git -C third_party/cold-clear checkout 279edd7c3177ff8077f6a930193397814b281f27
(cd third_party/cold-clear && cargo build --release -p c-api)
sha256sum third_party/cold-clear/target/release/libcold_clear.so
# 189bf1233b60de12b6553dcf914907c77a16f4fa01e28a5d7c25059953753892

# 2. Tests (real-engine tests skip automatically if the .so is absent)
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_coldclear1.py
# 11 passed

# 3. Real matches (this produced §7.2)
.venv/bin/python scripts/run_coldclear1_match.py --games 10 \
    --opponent heuristic --opponent random --garbage-probe \
    --json results/coldclear1_match_report.json
.venv/bin/python scripts/run_coldclear1_match.py --games 10 \
    --opponent heuristic --nodes 60000 --garbage-probe \
    --json results/coldclear1_match_report_60k.json
```

Environment override: `TETRISRL_COLDCLEAR1_LIB=/path/to/libcold_clear.so`.
Disable loading entirely: `TETRISRL_COLDCLEAR1_DISABLE=1`.

---

## 11. Observations / issues encountered

* **Struct layout**: ctypes mirror sizes were checked against the C header
  (152/180/28 bytes). `CCMove.movements` is a C enum array (4 bytes each), not
  a byte array; treating it as bytes would corrupt all later fields.
* **Board orientation**: `field` index 0 is bottom-left; emitting our top-down
  rows directly produces a vertically mirrored board. Tests pin this.
* **Queue/hold**: passing only the current piece makes the engine unable to
  decide whether holding is useful; the adapter sends current + five previews.
  `use_hold=True` with an unknown queue is why `speculate` is off.
* **`combo` type**: the C API takes `u32`; our TETR.IO combo is `-1` for "no
  combo", so the adapter sends `max(0, combo + 1)`.
* **No parse/encoding errors** were observed in 3,625 engine searches: zero
  protocol/parse failures, zero timeouts, one geometric inexpressibility at
  60k. All 30 matches passed the versus layer's action validation.
* **Concurrent workspace note**: the adapter file was present in the working
  tree while another agent committed shared files; this document reflects the
  adapter as tested (including the `incoming_searches` counter). No other
  agent's code was modified.

---

## 12. Non-claims

* We did **not** modify, patch or relicense Cold Clear.
* We did **not** use Cold Clear's attack, B2B, garbage or spin logic; the arena
  adjudicates all competitive rules.
* We did **not** claim Cold Clear implements TETR.IO Season 2, SRS+ or 180°
  rotation.
* The 60k-node 10–0 is not a general strength claim; it is 10 deterministic
  games against a one-ply heuristic on paired seeds.
