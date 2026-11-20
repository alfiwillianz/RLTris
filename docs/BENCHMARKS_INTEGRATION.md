# BENCHMARKS_INTEGRATION — Cold Clear 2 as a real versus opponent

**Status: REAL INTEGRATION EXECUTED.** Cold Clear 2 was cloned at a pinned
commit, built with `cargo build --release`, driven as a subprocess over the
Tetris Bot Protocol (TBP), and played **20 versus matches** (10 vs the
in-repo heuristic, 10 vs the random baseline) inside
`tetrisrl.environment.versus.VersusMatch` under the project's `tetrio_s2`
ruleset. The engine answered **962 suggestions**, every one was validated
against `GameState.legal_actions()`, and the matches are summarised in §7.

Verification date: **2026-11-20** · Host: Linux, Rust/cargo 1.100.0, Python
3.12 (`/home/alfi/Active/tetrlio/.venv/bin/python`).  The match runner disables
per-tick replay frames/events for speed; the full per-game stats are in the JSON
report referenced in §7, and `VersusMatch` replay recording itself is unchanged
and available when `record_frames=True`.

---

## 1. TL;DR

| Item | Value |
|---|---|
| Engine | [Cold Clear 2](https://github.com/MinusKelvin/cold-clear-2) (`MinusKelvin/cold-clear-2`) |
| Pinned commit | `ed8b19327b6bd1410ddd873d8611485bd45d8fae` (2022-06-29) |
| License | **MIT OR Apache-2.0**, at your option (notice + copies in `third_party/`) |
| Build | `cargo build --release` → succeeded in 9.85 s (7 warnings, no errors) |
| Binary | `third_party/cold-clear-2/target/release/cold-clear-2`, 1,812,760 bytes, SHA-256 `656af2b8d14fc1562d6769c9d03423f18747e3786126eacb05f1a4c32c47c7cd` |
| Engine self-report | `{"type":"info","name":"Cold Clear 2","version":"0.1.0 ed8b193","author":"MinusKelvin","features":[]}` |
| Protocol | TBP JSON lines over stdin/stdout (`start` → `suggest` → `suggestion`) |
| Adapter | `TBPAgent` in `tetrisrl/agents/opponents/tbp.py` |
| Test double | `SBPMockBot` in `tetrisrl/agents/opponents/mock_bot.py` (**a mock, not a benchmark**) |
| Real match | **Yes** — 10–0 vs heuristic, 10–0 vs random (details §7) |
| Engine's role | **Placement suggester only.** `tetrisrl` owns attack, garbage, cancellation, B2B charging, surge and top-out. |
| Engine nodes | ~115.6k nodes/move (60 ms budget), ~111.1M nodes across all 20 matches |
| Fallback rate | 4 / 962 suggestions (0.42%); all four were placements our hard-drop action space cannot express |

**What this is not:** it is not a Cold Clear 2 benchmark of TETR.IO Season 2
strength, and it does not mean Cold Clear 2 understands Season 2. It means a
real, unmodified Cold Clear 2 binary made every placement decision for one side
of 20 deterministic matches, with `tetrisrl` adjudicating all competitive rules.

---

## 2. Files

| File | Purpose |
|---|---|
| `tetrisrl/agents/opponents/tbp.py` | TBP wire encode/decode, subprocess session, `TBPAgent` adapter, counters |
| `tetrisrl/agents/opponents/mock_bot.py` | Deterministic **mock** TBP bot subprocess for plumbing tests (`SBPMockBot`) |
| `tetrisrl/agents/opponents/__init__.py` | Public exports (no process is started at import time) |
| `tetrisrl/tests/test_opponents.py` | 17 tests: protocol roundtrip, geometry mapping, fallback paths, lifecycle, guarded real-engine smoke tests |
| `scripts/external_match.py` | Match runner used for the numbers in §7 (JSON report + console table) |
| `third_party/COLD_CLEAR_2_NOTICE.md` | Provenance, license, pinned commit, binary hash |
| `third_party/LICENSE-cold-clear-2-MIT`, `...-APACHE-2.0` | Copies of the upstream license texts |
| `docs/BENCHMARKS_INTEGRATION.md` | This document |

The upstream source is **not** vendored into the Python package. The clone lives
at `third_party/cold-clear-2/` (a build artefact; treat it as gitignored, keep
the notice + licenses).

---

## 3. Exact build steps

```bash
cd /home/alfi/Active/tetrlio
mkdir -p third_party
git clone https://github.com/MinusKelvin/cold-clear-2 third_party/cold-clear-2
cd third_party/cold-clear-2
git checkout ed8b19327b6bd1410ddd873d8611485bd45d8fae
cargo build --release
```

Observed tail of the build (exit code 0):

```
warning: `cold-clear-2` (lib) generated 7 warnings (run `cargo fix --lib -p cold-clear-2` to apply 6 suggestions)
warning: field `profile` is never read
  --> src/main.rs:12:5
...
    Finished `release` profile [optimized] target(s) in 9.85s
```

All dependencies are crates.io versions pinned by the committed `Cargo.lock`;
there are no git dependencies. The build created a 134 MB `target/` directory.

Reproduce the exact binary identity:

```bash
sha256sum third_party/cold-clear-2/target/release/cold-clear-2
# 656af2b8d14fc1562d6769c9d03423f18747e3786126eacb05f1a4c32c47c7cd
```

---

## 4. TBP protocol, as actually implemented by Cold Clear 2

Everything below was verified against **this** binary (source in
`third_party/cold-clear-2/src/{main.rs,lib.rs,tbp.rs,data.rs,bot.rs,dag.rs}` and
live probes), not only against the spec at
<https://github.com/tetris-bot-protocol/tbp-spec> (`text/0000-mvp.md`).

### 4.1 Lifecycle used by the adapter

```
engine → info                     {"type":"info", ...}
adapter → rules                   {"type":"rules"}
engine → ready                    {"type":"ready"}
adapter → start                   {board, queue, hold, combo, back_to_back}
adapter → suggest                 {"type":"suggest"}
engine → suggestion               {"moves":[...], "move_info":{...}}
... repeat start/suggest for every piece ...
adapter → quit                    {"type":"quit"}   (then stdin close / kill)
```

Cold Clear 2 answers `suggest` with `moves: []` until its worker thread has
expanded the root node. The adapter retries `suggest` every ~3 ms until a move
arrives or the timeout expires. A new `start` is sent for **every piece**, which
restarts the engine's search tree; TBP has no message that updates the board in
place, and reusing `play` would desynchronise whenever our fallback is used.

Two other frontend→bot messages exist and were verified in the engine source but
are **not** used by this adapter: `play {"move": {...}}` tells the bot to advance
its own copy of the board (hold is inferred from which piece was placed), and
`new_piece {"piece": "T"}` appends a newly revealed piece to its queue. They are
the efficient path for a continuous session, but they assume the frontend always
plays the engine's move; our adapter may legitimately fall back to the heuristic,
so a fresh `start` per piece is the safe choice.

### 4.2 `start` fields

| Field | Adapter behaviour |
|---|---|
| `board` | 40 rows × 10 cells. **Row 0 is the bottom row** (verified: the engine's `Board::from` maps row index → bit index, and its `y=0` is the floor). Our `Board.rows[0]` is the *top* row, so the adapter sends `reversed(rows)`. Empty cells are JSON `null`; occupied cells are `"#"`. The protocol also accepts `"G"` for garbage; Cold Clear 2 treats any non-null cell as occupied, but our `Board` stores occupancy only and does not preserve garbage provenance, so the adapter cannot faithfully emit `"G"` (the encoder supports it for callers that know the row indices). |
| `queue` | List of piece letters. Cold Clear 2's `create_bot` uses `queue[0]` as the **reserve/hold slot** when `hold` is `null`, and as the **current piece** when `hold` is non-null. Empirically: with `hold=null, queue=["I","O","T","S","Z"]` the engine suggests **O** (queue[1]); with `hold="T", queue=["I",...]` it suggests **I** (queue[0]). The adapter therefore sends `[first_preview, current, *previews]` when hold is empty, and `[current, *previews]` otherwise, so the engine's root piece is always our current piece. |
| `hold` | Our hold piece, or `null`. |
| `combo` | Our `ClearState.combo` follows TETR.IO (`-1` = no combo); TBP wants a count, so the adapter sends `max(0, combo + 1)` (same conversion Quadspace uses: `Ren + 1`). The engine rejects negative values with a panic (`invalid value: integer -1, expected u32`), which is how this was caught. |
| `back_to_back` | `state.b2b_active`. |
| `randomizer` | **Not sent.** Cold Clear 2 then uses `Randomizer::Unknown`, i.e. no seven-bag speculation. This deliberately avoids leaking hidden bag state to the opponent and is a small strength handicap. |

### 4.3 Suggestion format and coordinate conventions

```json
{"type":"suggestion","moves":[
  {"location":{"type":"O","orientation":"north","x":4,"y":0},"spin":"none"}
],"move_info":{"nodes":33416,"nps":664555.36,"extra":"..."}}
```

* `type` is one of `I O T L J S Z`; `orientation` is `north|east|south|west`.
* `x`, `y` are the **SRS true-rotation centre**, with `y=0` at the **bottom** row
  and `x=0` the left column. Cold Clear 2 computes absolute cells as
  `rotate_cell(orientation, PIECE_CELLS[type]) + (x, y)` with
  `north=(x,y)`, `east=(y,-x)`, `south=(-x,-y)`, `west=(-y,x)` (y grows upward).
* The adapter converts to our top-down coordinates with
  `(x_ours, y_ours) = (x_cc, 39 - y_cc)` and then finds the **legal action**
  whose resolved placement covers exactly those four cells, preferring the
  non-hold action when the suggested piece equals the current piece and the
  hold action otherwise. Rotation labels are never trusted; only cell geometry
  is matched. Example (verified live): O north at `x=4, y=0` →
  cells `{(4,39),(5,39),(4,38),(5,38)}` → action `rotation=0, column=4,
  hold=0` (action id 8).
* `spin` is the engine's intended spin classification. The adapter ignores it:
  our engine re-classifies the placement with its own SRS+/TETR.IO spin rules,
  so the competitive rules stay ours.
* `move_info.nodes` is accumulated in `TBPAgent.stats.nodes_total`.

### 4.4 Incoming garbage

TBP has **no garbage message and no pending-garbage field**. Cold Clear 2 only
sees garbage once it has been inserted into the board we send. It cannot plan
around pending garbage, and it has no model of TETR.IO Season 2 charging/surge.
The adapter sends no attack, garbage, combo-charge or surge state beyond
`combo`/`back_to_back`; `tetrisrl.environment.engine` / `versus` own all of it.

---

## 5. Adapter behaviour (`TBPAgent`)

* **Lazy process launch**: importing `tbp.py`, creating `TBPAgent`, and collecting
  pytest tests never spawn a process. The engine starts on the first
  `reset()`/`choose_action()` that needs it.
* **Test-collection guard**: under pytest, launching is refused unless
  `allow_in_tests=True` is passed explicitly; when refused, the adapter falls
  back and records `protocol_errors += 1` instead of spawning an engine.
  `TETRISRL_TBP_DISABLE=1` is an additional opt-out.
* **Clean shutdown**: `terminate()` sends `quit`, closes stdin, waits 2 s, then
  kills if needed; reader threads are daemonised and joined best-effort.
* **Timeouts**: configurable suggestion deadline (`timeout`, default 5 s) and
  handshake deadline (default 10 s). On timeout the session is closed and the
  next call starts a fresh engine.
* **Validation**: the **first** suggested move (`moves[0]`, the engine's most
  preferred move) is converted to a candidate action and must be present in
  `state.legal_actions()`. The conversion matches the four absolute cells and
  yields the action whose `column` is the placement's left-most occupied column,
  as required by the project action encoding. If the move is not expressible
  (invalid coordinates, wrong piece, or a tuck/spin our hard-drop action space
  cannot encode), the adapter falls back to the in-repo `HeuristicAgent` and
  increments `stats.invalid_suggestions` and `stats.fallbacks`. Alternative
  moves in the suggestion list are intentionally not tried: the brief requires
  converting the first move, and silently shopping for a playable alternative
  would hide a real compatibility gap.
* **Counters** (`agent.stats`): `engine_starts`, `suggestions`, `accepted`,
  `invalid_suggestions`, `fallbacks`, `timeouts`, `protocol_errors`,
  `engine_restarts`, `answer_latency_ms`, `nodes_total`, `last_move_info`,
  `last_error`. `agent.fallback_count` is a convenience property.
* **Honest failure**: a missing binary raises `TBPProcessError` inside
  `choose_action`, is counted, and the move is played by the heuristic; matches
  never crash on a broken engine.

---

## 6. Mock bot (`SBPMockBot`) — plumbing only

`python -m tetrisrl.agents.opponents.mock_bot --mode drop` is a ~250-line pure
Python TBP test double. It is clearly labelled in its `info` message
(`"Mock TBP Bot (test double, not a benchmark)"`) and in code/docstrings. Modes:

* `drop` — hard-drop the current piece at rotation 0 into the first fitting
  column (deterministic);
* `invalid` — return an out-of-bounds placement to exercise fallback;
* `file --moves-file` — replay scripted TBP moves;
* `--telemetry FILE` — append every received `start` as JSON lines
  (used by tests to verify board/queue/hold encoding);
* `--empty-first`, `--delay-ms`, `--crash-after` — exercise the retry, timeout and
  process-death paths.

**It must never be used as a benchmark number.** The real-engine results in §7
come only from the Cold Clear 2 binary.

---

## 7. Actual match results (real Cold Clear 2)

Command (exactly as required):

```bash
.venv/bin/python scripts/external_match.py --opponent coldclear --games 10 --seed 0
```

Configuration: `tetrio_s2` ruleset, one process per game, `--max-pieces 400`,
`--think-ms 60`, `--timeout 5`, paired seeds `0..9`, Cold Clear 2 as agent A,
baseline as agent B. JSON report:
`results/external_match_coldclear_1795188684.json`.

### 7.1 Result summary

| Series | Score (W–L–D) | Win rate | Games | Avg reported ticks¹ | Wall time |
|---|---|---|---|---|---|
| Cold Clear 2 vs heuristic | **10–0–0** | **100%** | 10 | 78.8 | 57.3 s |
| Cold Clear 2 vs random | **10–0–0** | **100%** | 10 | 15.4 | 10.6 s |

¹ `MatchResult.ticks` reports the final loop index (0-based), so the number of
placements (`accepted`) is `ticks + 1` in every game. This is an arena reporting
quirk, not an engine issue.

Exact console output (abridged to the summary lines; the full per-game table is
in the JSON report):

```
--- Cold Clear 2 (TBP subprocess) vs heuristic ---
  game  1 seed=0     win   reason=top_out_b              ticks=51   accepted=52   invalid=0   fallbacks=0    topout=block_out          3.71s
  ...
  game 10 seed=9     win   reason=top_out_b              ticks=159  accepted=160  invalid=0   fallbacks=0    topout=block_out         11.34s
  SUMMARY vs heuristic: 10-0-0 (100.0% wins) over 10 games; engine fallbacks 4 (rate 0.5%)

--- Cold Clear 2 (TBP subprocess) vs random ---
  game  1 seed=0     win   reason=top_out_b              ticks=19   accepted=20   invalid=0   fallbacks=0    topout=block_out          1.27s
  ...
  game 10 seed=9     win   reason=top_out_b              ticks=19   accepted=20   invalid=0   fallbacks=0    topout=block_out          1.27s
  SUMMARY vs random: 10-0-0 (100.0% wins) over 10 games; engine fallbacks 0 (rate 0.0%)
```

All 20 matches ended by `top_out_b` (the baseline topped out — `block_out` — while
Cold Clear 2 was still alive). No match hit the 400-piece cap; no engine process
crashed or was restarted; no action was rejected by `VersusMatch`
(`invalid_actions == [0, 0]` in every game).

### 7.2 Engine telemetry

| Metric | vs heuristic | vs random |
|---|---|---|
| Engine suggestions | 798 | 164 |
| Accepted placements | 794 | 164 |
| Invalid suggestions → heuristic fallback | 4 | 0 |
| Fallback rate | 0.50% | 0.00% |
| Nodes total | 92,281,497 | 18,852,084 |
| Nodes per move (mean) | 115,641 | 114,952 |
| Mean answer latency | 60.61 ms | 60.44 ms |
| Engine starts (processes) | 10 | 10 |
| Protocol errors / timeouts | 0 / 0 | 0 / 0 |

The four fallbacks all occurred in one long game (seed 3, 137 reported ticks):
Cold Clear 2 suggested a placement reachable only via a tuck/spin path that our
placement-based, hard-drop action space cannot encode. The heuristic then chose
the move. This is expected and measured, not hidden.

### 7.3 Per-player averages (10 games each)

**vs heuristic**

| Player | Pieces | Lines | Attack | Sent | Recv | Inserted | T-spins | Tetrises | B2B max | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Cold Clear 2 | 79.8 | 38.1 | 49.2 | 45.7 | 13.4 | 9.9 | 6.0 | 4.3 | 1.6 | 4.3 | 1.2 |
| Heuristic | 79.8 | 46.7 | 20.3 | 13.4 | 44.1 | 37.2 | 1.0 | 1.2 | 0.7 | 21.9 | 18.5 |

Cold Clear 2 cleared fewer raw lines but generated ~2.4× the attack (T-spins,
tetrises, B2B) and kept a clean/low board while burying the heuristic under ~44
lines of incoming garbage per game. The heuristic cleared more lines (a
downstacking response) but its board filled: final height ~22, ~19 holes.

**vs random**

| Player | Pieces | Lines | Attack | Recv | Inserted | T-spins | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|
| Cold Clear 2 | 16.4 | 3.8 | 5.9 | 0.0 | 0.0 | 1.0 | 4.5 | 0.4 |
| Random | 16.3 | 0.0 | 0.0 | 5.9 | 5.5 | 0.0 | 23.3 | 63.8 |

Random never cleared a line and topped out after ~16 pieces under the first
garbage batches — the expected outcome, and a sanity check that attack/garbage
from our arena is reaching the opponent.

### 7.4 Interpretation limits

These are **20 games on paired seeds**, not a strength estimate for Cold Clear 2
in general. The 10/10 result against the heuristic has a Wilson 95% confidence
interval of about **[72.3%, 100%]** (n=10), and the same for random; a 10–0 record
does not mean a 100% true win rate. In particular:

* Cold Clear 2 was handicapped: 60 ms/move, search tree discarded every piece
  (`start` per piece), no seven-bag speculation, no 180° rotation, and it cannot
  see pending garbage.
* The baselines are deliberately simple (one-ply handcrafted heuristic and
  uniform random). Beating them is not evidence of TETR.IO-level strength.
* Both sides played the same `tetrio_s2` engine; all scoring, garbage,
  cancellation and charging were adjudicated by `tetrisrl`.

---

## 8. Compatibility limitations (explicit)

1. **Placement suggester, not a simulator.** Cold Clear 2 receives a board,
   hold, queue, combo and B2B flag and returns placements. It does not simulate
   our match, opponent, attack tables or garbage. The arena remains the single
   authority.
2. **No TETR.IO Season 2 attack model inside the engine.** Cold Clear 2's own
   `battle`-style logic is not used (this rewrite has no versus module); its
   evaluation knows combo/B2B only through the `start` fields. B2B **charging**,
   **surge**, S2 cancellation and garbage insertion live exclusively in
   `tetrisrl` (`scoring.py`, `garbage.py`, `engine.py`).
3. **No incoming-garbage planning.** TBP has no garbage message/pending count.
   The engine sees garbage only after it lands on the board. This is the single
   largest capability gap relative to a native S2 bot.
4. **No 180° rotation.** Cold Clear 2's piece geometry/movegen does not use 180°
   rotations, so placements requiring one are unavailable to it. Documented
   handicap.
5. **No SRS+ guarantee.** Cold Clear 2 implements guideline SRS with its own
   move generation; it does not model TETR.IO SRS+ kick nuances. Our engine
   still validates and applies the placement with SRS+ (`rotation.py`), and a
   placement that our engine cannot reach is rejected (fallback).
6. **Hard-drop action space vs. reachable-placement search.** Cold Clear 2
   searches tucks and spins; our action encoding is `(rotation, column, hold)`
   hard drops plus the engine's T-spin spin-in resolution. Mismatches are
   counted: 4/798 suggestions (0.5%) vs heuristic, 0/164 vs random. This
   directly reduces the engine's effective strength and is reported, not
   silently patched.
7. **Search restart per piece.** Sending `start` every piece rebuilds the
   engine's tree; this is simpler and robust against our fallback but weaker
   than continuous `play`/`new_piece` operation.
8. **No randomizer state.** The adapter omits TBP `randomizer`, so the engine
   does not speculate the current seven-bag; this is both a strength handicap
   and deliberate non-leakage.
9. **Engine nondeterminism.** Cold Clear 2's MCTS-inspired selection uses
   `thread_rng`; matched seeds do not make its *suggestions* bit-identical.
   Our replays record the chosen actions, so replay verification is still
   deterministic.
10. **No claim about Cold Clear 2 vs. Season 2.** These matches say only that
    the binary played legally and won under *our* ruleset against two simple
    baselines.

---

## 9. Reproduce everything

```bash
# 1. Clone + build the pinned engine (once)
cd /home/alfi/Active/tetrlio
git clone https://github.com/MinusKelvin/cold-clear-2 third_party/cold-clear-2
git -C third_party/cold-clear-2 checkout ed8b19327b6bd1410ddd873d8611485bd45d8fae
(cd third_party/cold-clear-2 && cargo build --release)

# 2. Adapter / protocol / lifecycle tests (real-engine tests auto-run when built)
.venv/bin/python -m pytest tetrisrl/tests/test_opponents.py
# observed: 17 passed in 3.00s

# Full suite
.venv/bin/python -m pytest
# observed: 143 passed in 13.84s

# 3. Real matches (this produced §7)
.venv/bin/python scripts/external_match.py --opponent coldclear --games 10 --seed 0

# 4. Optional: plumbing-only run without the external engine (NOT a benchmark)
.venv/bin/python scripts/external_match.py --opponent mock --games 2 --max-pieces 20
```

The tests skip the two real-engine tests automatically when
`third_party/cold-clear-2/target/release/cold-clear-2` is absent
(`coldclear_available()`), so the suite is still runnable on a clean checkout.

Environment override: `TETRISRL_COLDCLEAR_BIN=/path/to/cold-clear-2`.

---

## 10. Reproduction notes / known issues encountered

* **Build**: succeeded on the first attempt (Rust 1.100.0); no source patches
  were needed.
* **`combo: -1` panic**: the engine panics on a negative `combo`; the adapter now
  converts TETR.IO's `-1 = no combo` to TBP's 0-based count
  (`max(0, combo + 1)`). Verified against the live binary.
* **Board orientation**: sending rows top-down first produced nonsensical
  placements; the engine's `y=0` is the bottom. The adapter now reverses rows
  and converts suggestion cells back with `y_ours = 39 - y_cc`; verified with
  live suggestions and the action-space mapping.
* **Queue off-by-one with empty hold**: with `hold=null`, Cold Clear 2 treats
  `queue[0]` as the reserve and `queue[1]` as the piece to place. The adapter
  sends `[first_preview, current, *previews]` in that case (documented above).
* **Blocking arena bug (fixed during this work)**: an earlier revision of
  `tetrisrl/environment/engine.py` contained
  `if self.garbage.total() > 0 and any(self.board.rows[0]):` (`rows[0]` is an
  int), which raised `TypeError` whenever pending garbage remained. The engine
  owner removed the dead block; the 20 matches above were run after the fix.
* **Engine answers empty while thinking**: `suggestion` may have `moves: []`
  until the root is expanded; `TBPAgent` retries `suggest` (tested with
  `--empty-first`).

---

## 11. Non-claims

* We did **not** verify Cold Clear 2's strength against strong human/Season 2
  opposition; the 10–0 results are against an in-repo one-ply heuristic and a
  random agent.
* We did **not** modify Cold Clear 2's source; the clone is at the pinned commit
  and the built binary's version string contains `ed8b193`.
* We did **not** use Cold Clear 2's own versus/attack logic (it has none in this
  rewrite). Every competitive rule was enforced by `tetrisrl`.
* The mock bot is a test double and its results must never be cited as
  benchmark numbers.
