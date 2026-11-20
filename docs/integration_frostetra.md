# Frostetra integration — SBP/1 placement suggester

**Status: integrated as a real external opponent over SBP/1.** A pinned
frostetra release build was launched as a subprocess, completed the SBP
handshake, and returned placements that the adapter mapped to legal actions in
20 real versus matches. It beat the in-repo heuristic **10-0** and random
**10-0** (paired seeds 0-9, 300-piece cap). The engine only suggests placements:
TetrisRL owns the board, attack, garbage, cancellation, B2B charging and Surge.

The integration is **experimental**. The engine is MIT-licensed and advertises
SRS+/180, but its exact rotation-table parity with our ruleset is not fully
established (§7), its pending-garbage field is parsed and discarded (§6), and
its empty-hold behaviour via this SBP dialect is limited (§3.3). The match
numbers below are adapter-validation evidence against two in-repo baselines,
not a strength claim about the engine or a TETR.IO-parity claim.

| Field | Value |
|---|---|
| Upstream | https://github.com/ruelalarcon/frostetra |
| Pinned commit | `b92dc7606414776eb2bf2dfc67cb3119b41338ea` (2026-11-03, `Revert "Implement garbage pressure"`) |
| Version | `0.1.0`; binary reports `0.1.0 b92dc76` |
| Licence | **MIT** (`LICENSE.txt`, “Copyright (c) 2021 Mark Carlson / Copyright (c) 2026 Ruel Nathaniel Alarcon”) |
| Language / build | Rust 2021, `cargo build --release`; no system libraries |
| Binary | `third_party/frostetra/target/release/frostetra` |
| Binary SHA-256 | `e4324d0eeaca994258d0415d01e390dc09b8956ab3c28a1b0a181752f8e87394` |
| Protocol | SBP/1 (`register`/`rules`/`ready`/`start`/`suggest`/`suggestion`/`advance`/`board`/`stop`/`quit`/`info`) |
| Adapter | `tetrisrl/agents/opponents/frostetra.py` |
| Tests | `tetrisrl/tests/test_opponents_frostetra.py` (15 tests) |
| Match runner | `scripts/run_frostetra_match.py` |
| Notice | `third_party/FROSTETRA_NOTICE.md` |

---

## 1. Clone, pin, build

```bash
cd /home/alfi/Active/tetrlio
git clone https://github.com/ruelalarcon/frostetra third_party/frostetra
git -C third_party/frostetra checkout b92dc7606414776eb2bf2dfc67cb3119b41338ea
(cd third_party/frostetra && cargo build --release)
```

Toolchain: `rustc 1.100.0 (0ef1bc386 2026-11-09)` / `cargo 1.100.0` (Arch Linux).

Result: **success** in ~10 s, exit code 0, one warning (`unused dependency
enum_dispatch` in `Cargo.toml`). Artifact 9.6 MB,
`target/release/frostetra`, SHA-256 above. The source tree was not modified; the
upstream `LICENSE.txt` remains in place and the attribution is in
`third_party/FROSTETRA_NOTICE.md`. Override the adapter's binary path with
`TETRISRL_FROSTETRA_BIN`.

## 2. Handshake and message flow (verified against source + binary)

```text
bot    -> register {name:"Frostetra", version:"0.1.0 b92dc76", capabilities:{...}}
client -> rules {randomizer:"seven_bag", kickset:"srs_plus", rot180:true,
                 sonic_drop:"only", spin_detection:"t-spins",
                 back_to_back_sources:["quad","t-spin","t-spin-mini","perfect-clear"],
                 spawn_position:{x:4,y:20}, board_size:{width:10,height:40}}
bot    -> ready
client -> start {board:<40 rows, bottom-to-top>, active:"T", queue:["T",...],
                 hold:null, combo:0, back_to_back:0, incoming_garbage:[...],
                 piece_stream:{offset:0, pieces:[...]}}
client -> suggest {incoming_garbage:[...]}          # optional field per SBP/1
bot    -> info {topic:"search", data:{nodes,nps,extra}} (optional, may repeat)
bot    -> suggestion {moves:[{location:{piece,orientation,x,y}, spin}]}
client -> advance {move:<accepted placement>}        # best effort, then resync
... repeat per piece ...
client -> stop / quit
```

* `register` is emitted immediately on process start. `rules` must be sent before
  `start`; `ready` is the only accepted acknowledgement.
* The rules enum values are **snake_case on the wire**: `srs_plus`, not `srs+`.
  Sending `srs+` makes `serde_json` reject the whole line and the process exits
  (`src/main.rs` unwraps the deserialiser). The adapter therefore sends
  `srs_plus` (or `srs` for our guideline preset) and advertises the same.
* `suggestion.moves` is usually a one-element list. The adapter tries moves in
  order and accepts the first placement that maps to one of our legal actions.
* `info` messages are not responses; the adapter consumes and ignores them
  (recording the `search` node count in `stats.nodes_total`) while waiting for
  `suggestion`.
* `advance` is sent after an accepted suggestion to keep the engine session
  coherent, but every piece is re-synchronised with a fresh `start`, so a
  desync cannot accumulate. `board` is supported by the engine and documented
  here, but the adapter does not need it: a fresh `start` after a garbage rise
  already carries the new board.

`register.capabilities` (observed on the built binary): kicksets `["srs",
"srs_plus"]`, `rot180:true`, sonic drop `["only","allow"]`, spin detection
`["none","t-spins","t-spins+","all","all+","all-mini","all-mini+","mini-only"]`,
B2B sources including `perfect-clear`, `piece_stream:true`, `spawn_position:true`,
`board:true`, board size width `4..127`, height `1..64`.

## 3. SBP dialect details that matter for our adapter

### 3.1 Board

SBP rows are **bottom-to-top**, 40 rows of 10 cells, `null` for empty and any
string for occupied. Our board is occupancy-only, so blocks are sent as `"X"`;
garbage provenance is not fabricated. Our bottom row (row 39 top-down) is SBP
row 0.

### 3.2 `start`: `active` and `queue` semantics

The SBP/1 text says `active` is the active piece and `queue` excludes it. The
pinned engine does not implement that split: `create_bot` sets
`reserve = hold.unwrap_or(active)` and `bot_queue = queue` when `hold` is null,
and the first search layer places `bot_queue[0]`. A live probe settles it:

| `start` fields | suggestion piece |
|---|---|
| `active:"T", queue:["I","O"], hold:null` | **I** (the first preview, not the active piece) |
| `active:"T", queue:["T","I","O"], hold:null` | **T** (correct) |
| `active:"T", queue:["I","O"], hold:"J"` | J (reserve) or T (active), not I |

`create_bot` builds the internal queue as `[active] + queue` when `hold` is set,
and as `queue` when `hold` is null; it always searches that queue's **head**.
The adapter therefore uses a hold-dependent queue:

| Our state | `active` | `queue` | Engine's internal current |
|---|---|---|---|
| `hold == None` | current | `[current, *previews]` | `queue[0] = current` |
| `hold != None` | current | `[*previews]` | `active = current` |

This is a deliberate, documented deviation from the SBP/1 prose, required by
the engine's dialect. Repeating the current piece in both `active` and `queue`
when a hold exists would make the engine search the same piece twice.

> **Integration pitfall (measured).** The first adapter build used
> `queue=[current, *previews]` unconditionally. That is correct while the hold
> slot is empty but duplicates the current piece as soon as a fallback populates
> the hold slot; the engine then searches `current, current, ...` and plays
> badly. The only change from that build to the final one is the hold-dependent
> queue above: the heuristic series went from **1-9** to **10-0** on the same
> seeds, settings and binary. Keep the queue discipline in mind when adapting
> another SBP engine.

### 3.3 Empty hold is not representable

With `hold:null`, the engine stores `reserve = active = current`. It can
therefore only "hold" a copy of the current piece, i.e. it cannot initiate a
hold from an empty slot. When our state has a hold piece, `hold` is sent
normally (`reserve = hold`, internal current = `active`) and hold swaps are
searchable.
Consequence: in a clean game frostetra never holds until some other agent moves
for it (in the matches below, hold actions came only after a fallback heuristic
move had populated the hold slot). This is a handicap relative to our engine,
not an adapter bug.

### 3.4 Seven-bag information and `piece_stream`

Because the empty-hold queue duplicates the current piece, the engine's default
bag tracker observes `[active, current, *previews]` and draws an impossible bag
when the hold slot is empty.
The engine advertises `piece_stream` (an engine-specific SBP extension:
`{"offset": <absolute generation index>, "pieces": [...]}`), so the adapter
sends the observed generated-piece order instead, starting at generation index 0
(a game's first piece starts a seven-bag). A live probe confirms the tracker
then infers a correct bag and starts speculative search.

Residual deviation: the engine computes
`current_observed_index = pieces.len() - (start.queue.len() + 1)`, which assumes
the SBP-standard queue. With `hold` set and `current` being the most recently
generated piece the index is exact; with an empty hold it is one piece behind,
and after an actual hold the held `current` was generated earlier than the
stream tail. In both cases the speculative bag can be stale (e.g. include the
current piece as still upcoming). This affects only engine-internal hypothetical
search, never the legality of the root suggestion. The match runner can disable
the stream and/or the randomizer to quantify the effect (§8.1).

### 3.5 `combo`, `back_to_back`, `incoming_garbage`

* Our `clear_state.combo` is `-1` when no combo is active, `0` after the first
  clear. The engine's `combo` counts consecutive clears, so the adapter sends
  `max(0, ours + 1)`.
* `back_to_back` is sent as an integer (the engine also accepts a JSON boolean).
* `incoming_garbage` is sent on **both** `start` and `suggest` as the amounts of
  our pending queue entries (empty list if known empty). The pinned engine
  deserialises the field and discards it: `src/protocol/sbp.rs` defines it on
  `Start` and `Suggest`, `src/runtime/bot_factory.rs` destructures it as
  `incoming_garbage: _`, and the dispatcher handles `Suggest { .. }`. A
  deterministic probe (§6) confirms that `[]`, `[8]` and `[3,5]` produce the
  same suggestion. The field is sent for forward compatibility only.

### 3.6 `suggestion`, `advance`, `board`, `stop`

* `suggestion` carries `moves`, a list of
  `{"location":{"piece":"T","orientation":"north","x":6,"y":0},"spin":"none"}`
  objects. There is **no separate column or rotation-index field**:
  `orientation` is one of `north`/`east`/`south`/`west`, and `(x, y)` is the SRS
  rotation anchor in the bottom-up SBP frame (the four cells are
  `(x+dx, y+dy)` after the spec's relative-cell transform). Our action id is
  recovered by cell matching, not by reading a column. `spin` is the engine's
  own classification (`none`/`mini`/`full`); our engine recomputes spins and
  never trusts it.
* `advance {move}` applies the accepted placement and its line clears to the
  engine's internal session. It does not confirm garbage. The adapter sends it
  best-effort after an accepted suggestion and then re-syncs with `start` on the
  next piece.
* `board {board}` replaces only the physical board mid-session (intended for
  garbage rise or edits) and keeps piece/queue/hold/combo. The adapter supports
  the engine's capability but does not use it: a fresh `start` after a garbage
  rise is simpler and also refreshes queue/hold/combo.
* `stop` discards the current session (the process stays alive); `quit` exits.
  The adapter sends `stop` before closing on a timeout/protocol failure, and
  `quit` on `terminate()`, with a 2 s kill fallback.

## 4. Adapter design (`tetrisrl/agents/opponents/frostetra.py`)

* `frostetra_binary_path()` / `frostetra_available()` resolve the binary from an
  argument, `$TETRISRL_FROSTETRA_BIN`, or
  `third_party/frostetra/target/release/frostetra`.
* `SBPSession` launches the process lazily, reads stdout on a thread, keeps a
  bounded stderr tail, validates `register` capabilities against the requested
  rules, and closes with `quit` (SIGKILL fallback after 2 s).
* `FrostetraAgent` sends one `start` per piece (board, active, hold-dependent
  queue, hold, combo, B2B, pending garbage, piece stream), sleeps `think_time` (default
  0.08 s, engine default background search with 4 workers and a 3M-node cap),
  then requests a suggestion until the deadline.
* Suggestions are converted by **geometry**: SBP `(x,y)` is the SRS anchor in a
  bottom-up frame; the four cells are mirrored to our top-down board and matched
  against `state.resolve(action)` for every legal action. The hold flag is
  inferred from whether the engine placed the current or the held piece.
* Failure handling: timeouts, process errors and non-expressible placements all
  fall back to the in-repo `HeuristicAgent`, increment `stats.fallbacks`, and
  are counted by category (`timeouts`, `protocol_errors`,
  `invalid_suggestions`). A fallback never crashes a match; a timeout/process
  failure sends `stop` and restarts the engine on the next piece.
* Launch guard: importing the module never starts a process; under pytest it
  refuses to launch unless `allow_in_tests=True`. `TETRISRL_SBP_DISABLE=1` or
  `TETRISRL_FROSTETRA_DISABLE=1` disables launching entirely.
* `FrostetraStats` records starts/restarts, suggestions, accepted, invalid,
  fallbacks, timeouts, protocol errors, latency, nodes, orientation/spin counts
  of accepted suggestions, and the last error.

## 5. Tests

```bash
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_frostetra.py -q
# 15 passed
```

Coverage: path/env resolution; bottom-to-top board encoding; rules/start field
encoding (queue dialect, combo offset, B2B, garbage chunks); geometry including a
south orientation; legal action mapping (including a held-piece suggestion);
invalid/floating moves; launch guard; disable env; a real suggestion mapped to a
legal action and capabilities recorded; real lifecycle/restart with no orphan
process; broken-command fallback; a deterministic two-process probe proving
`incoming_garbage` does not change the suggestion; and a 40-piece versus smoke
test against the heuristic. Engine tests are skipped when the binary is absent.

## 6. `incoming_garbage` verification

Source: `grep -rn incoming_garbage third_party/frostetra/src` returns only the
two struct definitions and the destructuring sites above; there is no read of
the value. The pinned commit is itself `Revert "Implement garbage pressure"`,
but that revert touched only `evaluator.rs`/`weights.rs`/`default.json` — the
"pressure" experiment used a config weight, not the SBP field.

Behavioural probe (seeded RNG, deterministic 5000-iteration per-suggestion
budget, three fresh processes, identical start):

```text
incoming=[]    : T north x=6 y=0
incoming=[8]   : T north x=6 y=0
incoming=[3,5] : T north x=6 y=0
equal: True
```

Conclusion: the field is accepted and ignored at this commit. The adapter sends
it anyway (forward compatibility) and records the number of requests that
carried pending garbage (`stats.garbage_queries`; 125 in the heuristic series).

## 7. SRS+ / 180: what is and is not evidenced

**Advertised and present in source (verified):**

* `register` advertises `kicksets:["srs","srs_plus"]`, `rot180:true`.
* `src/tetris/movegen/finder.rs` enumerates four orientations under
  `sonic_drop:"only"` and calls `rotate_to(...)` for clockwise,
  counter-clockwise and (when `rules.rot180`) `rotation.flip()`.
* `src/tetris/movegen/kicks/srs_plus.rs` contains explicit SRS+ JLSTZ and I
  tables plus 180 transitions. Its **JLSTZ** rows, including all four 180
  transitions, are identical to our table in
  `tetrisrl/environment/rotation.py`/`docs/RULESET.md`.

**Not evidenced / deviations (do not overclaim):**

* The engine's **I-piece SRS+ rows omit the `(0,0)` basic-rotation test**
  (`I_KICKS` starts at `(1,0)`), and `rotate_to` applies only the listed kicks
  with no implicit in-place test. Our table restores `(0,0)` as Test 1. Its I
  rotations therefore always shift by a kick; a rotation that only fits in place
  can be rejected. This is a source-level divergence from our SRS+ model.
* The engine's **I-piece 180 rows contain two tests**, while our
  community-sourced TETR.IO I 180 table has six. JLSTZ 180 parity is good; I
  180 parity is not established.
* Match-level orientation counts prove only that rotated final states occur
  (e.g. vs heuristic: north 302, east 409, south 129, west 96 of 936 accepted
  suggestions). A south-facing placement can be reached by two 90° rotations as
  well as by a 180, so this is **not** proof that a concrete placement required
  a 180-only kick. Likewise, no match demonstrates that a placement required an
  SRS+-only I kick (SRS and SRS+ mostly differ in test order, not reachable
  set).

Verdict: frostetra **does implement and exercise SRS+ and 180 mechanics**, and
its JLSTZ tables match ours, but **full SRS+/180 parity with TETR.IO is not
evidenced** and the I-piece differences above are real. We request
`srs_plus`/`rot180:true` because they are the closest advertised match to our
ruleset, and we keep our engine authoritative for all spin/attack scoring.

## 8. Real match results

Command:

```bash
.venv/bin/python scripts/run_frostetra_match.py --games 10 \
    --opponent heuristic --opponent random --max-pieces 300 --seed 0 \
    --json results/frostetra_match_20261120.json
```

20 games, paired seeds 0-9 per baseline, `max_pieces=300`, `think_time=0.08 s`,
`timeout=5 s`, TETR.IO Season 2 ruleset. Frostetra is player A (a win means the
opponent topped out first).

| Baseline | Score (W-L-D) | Win rate | Accepted | Fallbacks (rate) | Invalid | Timeouts | Protocol errors | Engine nodes |
|---|---|---|---|---|---|---|---|---|
| heuristic | **10-0-0** | 100.0 % | 936 | 37 (3.80 %) | 37 | 0 | 0 | 682,202,234 |
| random | **10-0-0** | 100.0 % | 194 | 10 (4.90 %) | 10 | 0 | 0 | 141,075,232 |

All fallbacks were **non-expressible placements** (typically `spin:"full"`
tucks/spins our hard-drop action space cannot encode), not timeouts or crashes.
No engine restarts and no protocol errors in either series. Accepted-suggestion
orientation census: vs heuristic `{north:302, east:409, south:129, west:96}`,
spins `{none:865, full:71}`; vs random `{north:77, east:83, west:21, south:13}`,
spins `{none:189, full:5}`.

Per-game detail vs heuristic (A = frostetra, B = heuristic):

| Seed | Outcome | Ticks | A lines | A attack | A sent | A recv (inserted) | B lines | B attack | B final height |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | win | 63 | 28 | 35 | 32 | 9 (6) | 31 | 10 | 27 |
| 1 | win | 91 | 39 | 42 | 40 | 10 (8) | 47 | 15 | 24 |
| 2 | win | 83 | 34 | 36 | 34 | 8 (6) | 40 | 14 | 22 |
| 3 | win | 152 | 75 | 81 | 77 | 23 (19) | 94 | 43 | 21 |
| 4 | win | 65 | 27 | 31 | 31 | 10 (10) | 32 | 14 | 21 |
| 5 | win | 79 | 37 | 46 | 42 | 13 (9) | 44 | 18 | 24 |
| 6 | win | 57 | 25 | 28 | 26 | 7 (5) | 25 | 9 | 23 |
| 7 | win | 105 | 44 | 53 | 46 | 13 (6) | 58 | 19 | 22 |
| 8 | win | 217 | 114 | 134 | 117 | 53 (36) | 149 | 79 | 24 |
| 9 | win | 61 | 29 | 33 | 26 | 18 (11) | 29 | 19 | 21 |

All ten heuristic top-outs were `block_out`; the baseline ended at stack heights
21-27 (above the 20 visible rows). Vs random every game ended by `block_out`
after 16-26 ticks; random never sent attack. Average match length was 97.3 ticks
vs heuristic and 20.4 vs random.

Interpretation (modest, not overclaimed): with the final adapter, frostetra
out-attacks and out-survives both in-repo baselines over these paired seeds. It
sends far more garbage than it receives (e.g. 117 sent vs 53 received in the
217-tick game) and converts that into top-outs. The heuristic is a one-ply
baseline and random is weak, so this validates the adapter and places the engine
above those baselines; it says nothing about its strength against search-based
engines, RL policies or TETR.IO human play. It also cannot plan around pending
garbage (§6) and cannot initiate an empty hold (§3.3) — the wins are despite
those limitations, partly because fallback heuristic moves occasionally
populate the hold slot (hold counts 20-90 in the heuristic series).

### 8.1 Adapter ablations (same seeds, vs heuristic)

To check whether our dialect workarounds (piece stream / seven-bag
advertisement) and the search budget materially change strength:

| Configuration | W-L-D | Accepted | Fallback rate | Notes |
|---|---|---|---|---|
| default (`randomizer=seven_bag`, piece stream on, 0.08 s) | **10-0-0** | 936 | 3.80 % | main run |
| piece stream off | 8-2-0 | 745 | 7.57 % | engine observes the duplicated current in its bag tracker |
| piece stream off, randomizer omitted | 8-2-0 | 783 | 5.55 % | no bag inference/speculation at all |
| default rules, `think_time=0.3` | **5-5-0** | 709 | 6.22 % | ~2.5M nodes/suggestion (near the 3M cap) |
| `think_time=0.3`, no stream and no randomizer | 8-2-0 | 759 | 8.00 % | removing bag speculation removes the 0.3 s degradation |

These are 10-game paired samples, not a statistical comparison; a 2-game
difference is within noise, but 10-0 vs 5-5 is not. The default stream/seven-bag
configuration is the most faithful description of our state and performed at
least as well as the ablations at 0.08 s.

**Search-time sensitivity (measured, not explained).** Giving the engine ~4x
more time in the default configuration made it **worse**, not better (10-0 at
0.08 s vs 5-5 at 0.3 s). The 0.3 s run spent ~2.5M nodes per suggestion, close
to the engine's 3M background cap. Removing bag speculation at the same 0.3 s
restored 8-2 (424M nodes), so the degradation is associated with deeper
speculative search, not with the wall-clock budget alone. A plausible mechanism
is the one-piece-stale speculative bag described in §3.4, but 10-game samples
and a timing-dependent engine cannot establish causation; we report the pattern
and do **not** claim that 0.08 s is optimal. The 0.08 s default was chosen a
priori alongside the existing CC2 adapter's 0.06 s, not tuned against the
baseline.

## 9. Limitations

* **No Season 2 attack/charging model.** The engine is a placement suggester;
  it never sees Surge, charge, attack tables or garbage insertion. Our arena
  owns all of them. Do not read the engine's internal B2B/combo evaluation as
  Season 2 behaviour.
* **No pending-garbage planning.** `incoming_garbage` is parsed and discarded
  (§6). Garbage is only visible after it lands on the board (via `start`).
* **Empty hold is unusable** through this dialect (§3.3). A fallback heuristic
  move that uses hold can populate the slot, after which the engine can use it.
* **Action-space mismatch.** The engine enumerates every reachable lock
  (including tucks/spins); our actions are (rotation, left-most column, hold)
  hard drops plus T spin-in resolution. Non-expressible suggestions fall back
  and are counted (3.8-4.9 % here; 5.6-7.6 % in the ablations).
* **Bag-tracker index off by one** because the engine assumes the SBP-standard
  queue while its own `start` handling requires our duplicate (§3.4). This
  affects speculative search only.
* **Search is timing-dependent.** The default config uses entropy RNG and a
  background node cap, so the 0.08 s suggestion can differ between runs. Use
  `--config` with a seeded RNG and `iterations_per_suggest` for deterministic
  probes (the tests do).
* **Rotation parity is partial** (§7): I-piece SRS+ in-place rotation and I-piece
  180 tables differ from ours. JLSTZ SRS+/180 tables match.
* **Single-author, low-adoption upstream** (0 stars at survey time, created
  2026-06-11). No external validation of strength; the numbers here are only
  our measurements.

## 10. Reproduction

```bash
cd /home/alfi/Active/tetrlio

# 1. Build the engine (already pinned in third_party/frostetra)
(cd third_party/frostetra && cargo build --release)

# 2. Tests (real-engine tests skip automatically if the binary is absent)
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_frostetra.py -q

# 3. The recorded 20-game series
.venv/bin/python scripts/run_frostetra_match.py --games 10 \
    --opponent heuristic --opponent random --max-pieces 300 --seed 0 \
    --json results/frostetra_match_20261120.json

# 4. Ablations
.venv/bin/python scripts/run_frostetra_match.py --games 10 --opponent heuristic \
    --max-pieces 300 --no-piece-stream
.venv/bin/python scripts/run_frostetra_match.py --games 10 --opponent heuristic \
    --max-pieces 300 --no-piece-stream --no-randomizer

# 5. Deterministic incoming-garbage probe (seeded per-suggestion config)
#    see test_incoming_garbage_does_not_change_the_suggestion
```

The adapter can be constructed directly:

```python
from tetrisrl.agents.opponents.frostetra import FrostetraAgent
from tetrisrl.environment.engine import GameState

agent = FrostetraAgent(think_time=0.08, timeout=5.0)
state = GameState(seed=0)
action = agent.choose_action(state)   # legal action id, or heuristic fallback
agent.terminate()
```

## 11. Files

| Path | Role |
|---|---|
| `tetrisrl/agents/opponents/frostetra.py` | SBP/1 client + `FrostetraAgent` |
| `tetrisrl/tests/test_opponents_frostetra.py` | 15 tests (11 need no frostetra process, 4 real-engine/skip) |
| `scripts/run_frostetra_match.py` | real match runner + JSON report + ablations |
| `third_party/FROSTETRA_NOTICE.md` | commit pin, MIT notice, build record |
| `docs/integration_frostetra.md` | this document |
| `results/frostetra_match_20261120.json` | raw 20-game report |

No shared file (`tbp.py`, `base.py`, ruleset, arena) was modified.
