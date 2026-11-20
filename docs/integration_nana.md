# Integration — `nightcrab/nana` as a real versus opponent

**Status: REAL INTEGRATION EXECUTED.** `nana` was cloned with submodules at the
pinned commit `3cb49c6cc680f07282382de2862f1aa656d9afa1`, built with CMake
(Release), driven as a **TBP2** subprocess through
`tetrisrl/agents/opponents/nana.py`, and played **20 versus matches** (10 vs the
in-repo heuristic, 10 vs the random baseline) inside
`tetrisrl.environment.versus.VersusMatch` under the project's `tetrio_s2`
ruleset. nana answered **848 suggestions**; 754 were played and 94 were replaced
by the in-repo heuristic because the suggested placement is not expressible in
our `(rotation, column, hold)` hard-drop action space.

Verification date: **2026-11-20** · Host: Linux, GCC 16.2.1, CMake 4.4.5
(installed into the project venv because `cmake` was not on `PATH`), Python 3.12
(`/home/alfi/Active/tetrlio/.venv/bin/python`).

---

## 1. TL;DR

| Item | Value |
|---|---|
| Engine | [nightcrab/nana](https://github.com/nightcrab/nana) (parallel MCTS/TDS, opponent model) |
| Pinned commit | `3cb49c6cc680f07282382de2862f1aa656d9afa1` (2026-11-10, `git describe`: `v0.2.0-9-g3cb49c6`) |
| Submodule | `cpp/Tetris/game/ShakTrisLib` → `Nightcrab/ShakTrisLib` @ `d8093fa9a592a3b5b2cc0daf1d9dde34a31bf49c` |
| License | **MIT**, "Copyright (c) 2026 Paul Anderson"; submodule MIT (upstream `LICENSE.txt` still has a `[year] [fullname]` placeholder — upstream hygiene flag) |
| Build | `cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j` → exit 0 |
| Binary | `third_party/nana/build/cpp/nana_tbp`, 1,233,320 bytes, SHA-256 `bcb1452666a391fc31e85c230bb166d6c4029c6ca5b40860bff12dd5987817ad` |
| Config | `third_party/nana/build/cpp/nana.json` = `{"rules": "tetrio", "threads": 2}` |
| Engine self-report | `{"type":"info","name":"Nana","version":"0.1","author":"Shakkar + Awyzza","features":["set_threads","set_thinks"]}` |
| Protocol | **TBP2** (JSON lines); `opponents[0]` is mandatory, `queue[0]` is the current piece, opponent pending garbage arrives as `opponents[0].meter` |
| Adapter | `NanaAgent(TBPAgent)` in `tetrisrl/agents/opponents/nana.py` |
| Tests | 20 in `tetrisrl/tests/test_opponents_nana.py` — **20 passed in 3.86 s**; full suite **248 passed in 21.44 s** |
| Real matches | **Yes** — **6–4–0 vs heuristic**, **10–0–0 vs random** (10 paired seeds each, 300-piece cap, 150 ms/move, 2 threads) |
| nana telemetry | 665 suggestions vs heuristic (585 accepted, 80 fallbacks, 12.03 %); 183 vs random (169 accepted, 14 fallbacks, 7.65 %); 0 timeouts, 0 protocol errors |
| Latency | mean 150.69 ms/move (heuristic series), 150.50 ms/move (random series) |
| Nodes | **Not exposed** — nana v0.1 `suggestion` has no `move_info`; `nodes_total` is 0 |
| Engine's role | **Placement suggester only.** `tetrisrl` owns attack, garbage, cancellation, B2B charging, surge, spin classification and top-out. |

**What this is not:** it is not a TETR.IO Season 2 strength estimate for nana.
nana's own `tetrio` rules are **Season 1** damage, it has no 180° rotation, it
only sees the bottom 32 rows, and 7.65–12.03 % of its chosen placements were
replaced by the heuristic. The matches show that the unmodified binary played
legally and won under *our* ruleset against two simple baselines.

---

## 2. Files

| File | Purpose |
|---|---|
| `tetrisrl/agents/opponents/nana.py` | TBP2 `start` builder, availability/config helpers, `NanaAgent`, nana-specific launch/transport |
| `tetrisrl/tests/test_opponents_nana.py` | 20 tests: paths/config, TBP2 start encoding, meters, pytest guard, real handshake/suggestions/synthetic opponent/missing-opponents/versus smoke |
| `scripts/run_nana_match.py` | Match runner used for §7 (JSON report + console table) |
| `third_party/NANA_NOTICE.md` | Provenance, license text, submodule, build identity, binary hash |
| `docs/integration_nana.md` | This document |

`tbp.py`, `agents/__init__.py`, the dashboard and every other existing file
were left unchanged. This task created only the five files above; other
unrelated files in the shared working tree are outside this change. The
upstream source is **not** vendored into the Python package;
`third_party/nana/` is a gitignored build clone, and
`third_party/NANA_NOTICE.md` is the committed provenance record.

---

## 3. Exact build steps

```bash
cd /home/alfi/Active/tetrlio
git clone --recurse-submodules https://github.com/nightcrab/nana third_party/nana
git -C third_party/nana checkout 3cb49c6cc680f07282382de2862f1aa656d9afa1
git -C third_party/nana submodule update --init --recursive

# cmake was not on PATH on this host; the project venv had no pip either, so
# uv installed the official cmake wheel into the venv:
uv pip install --python .venv/bin/python cmake        # cmake 4.4.5

.venv/bin/cmake -S third_party/nana -B third_party/nana/build -DCMAKE_BUILD_TYPE=Release
.venv/bin/cmake --build third_party/nana/build -j
```

Observed result: configure exit 0, build exit 0. The default `NANA_GUI=ON`
build succeeded because X11/OpenGL/libpng were present; all targets built
(`nana_tbp`, `nana_interactive`, `nana_emulate`, `nana_emulate_tbp`,
`nana_bench`, `nana_speed`, `nana_msgbench`, `nana_eval_dump`). mimalloc
`v3.5.4` was fetched by CMake `FetchContent` at configure time.

Minimal config, written beside the executable (nana's TBP mode reads
`nana.json` from `executableDirectory()`; argv and `NANA_CONFIG` are ignored in
that mode):

```json
{
  "rules": "tetrio",
  "threads": 2
}
```

The config is really loaded: temporarily replacing it with
`{"rules":"tetrio","threads":2,"bogus":1}` made `nana_tbp` exit 2 with

```text
nana config: /home/alfi/Active/tetrlio/third_party/nana/build/cpp/nana.json: unknown keys: bogus
```

The config was restored afterwards. `NanaAgent` also creates this minimal file
if it is missing (helper `ensure_nana_config`); it never rewrites an existing
one unless asked.

Reproduce the binary identity:

```bash
sha256sum third_party/nana/build/cpp/nana_tbp
# bcb1452666a391fc31e85c230bb166d6c4029c6ca5b40860bff12dd5987817ad
```

---

## 4. TBP2 protocol, as actually implemented by nana

Everything below was verified against the pinned source
(`third_party/nana/cpp/tbp.cpp`, `cpp/Tetris/bot/Config.cpp`,
`cpp/Tetris/game/EmulationGame.*`, `cpp/Tetris/game/ShakTrisLib/...`) and live
probes of the built binary.

### 4.1 Lifecycle used by the adapter

```text
engine  → info                 {"type":"info","name":"Nana",...}
adapter → rules                {"type":"rules"}
engine  → ready                {"type":"ready"}
adapter → start                {board, queue, hold, combo, back_to_back, meter, opponents:[...]}
adapter → suggest              {"type":"suggest"}
engine  → suggestion           {"moves":[{location, spin, inputs}], "type":"suggestion"}
... repeat start/suggest for every piece ...
adapter → quit                 {"type":"quit"}  (then stdin close / kill)
```

One `start` is sent **per piece**; `play`/`new_piece` are not used. This is the
safe choice because the adapter may legitimately fall back to the heuristic,
and a `play` stream would desynchronise the engine's board. nana rebuilds its
emulation game from every `start` (`game = EmulationGame()`), then calls
`Search::continueSearch(game)` when its search tree is already initialised.

### 4.2 `start` fields

| Field | Adapter behaviour |
|---|---|
| `board` | 40 × 10, **row 0 = bottom**. Cells are `null` for empty, `"#"` for occupied. nana's `Board::height` is **32**, and `json_to_board` reads only rows 0–31: the top 8 hidden rows of our 40-row wire board are invisible to nana. |
| `queue` | `[current, *previews]` (`queue[0]` is the current piece — `game.game.current_piece = queue.front(); queue.erase(queue.begin())`). nana uses the next queue entry as a **hold-swap candidate**, so it may return a placement for the next piece; `action_for_tbp_move` maps that to a hold action by geometry. |
| `hold` | Our hold piece or `null`. |
| `combo` | Integer consecutive-clear count. Our engine follows TETR.IO (`-1` = no combo), so the adapter sends `max(0, combo + 1)` as in the other TBP adapters. |
| `back_to_back` | Sent as an **integer** (`state.b2b_count`); nana accepts a JSON boolean or integer (`player_1["back_to_back"].is_boolean() ? ... : get<int>()`). |
| `meter` | Top-level pending garbage for player 1. **nana does not read this field**; it is emitted for TBP2 completeness. |
| `opponents` | **Mandatory.** `CHECK_ERR(player_2 = message["opponents"][0])`; without it the process dies (live probe: exit code −11 / SIGSEGV after `ready`). The adapter always sends exactly one opponent object, synthesising an empty board when no opponent state exists. |
| `opponents[0].meter` | **The pending-garbage field nana actually consumes.** `readOpponent()` stores `player_2["meter"]` in `SeenOpponent::meter`, which feeds `Eval::opponentDirection` (`OpponentFeature::METER`) and the HMM opponent model. The adapter sets it to `opponent_state.garbage.total()`. |
| `randomizer` | **Not sent.** This avoids leaking the current seven-bag to the opponent (and nana then uses its own bag assumptions). |

**Whitespace is a protocol hazard:** nana reads each message with
`std::cin >> str_input`, so pretty-printed JSON is truncated at the first
space. `TBPSession` writes compact JSON (`separators=(",", ":")`); the missing-
opponents probe with spaces failed with a JSON parse error at column 9. Do not
switch the transport to indented output.

### 4.3 Suggestion format and coordinates

```json
{"type":"suggestion","moves":[
  {"location":{"orientation":"north","type":"I","x":6,"y":0},
   "inputs":[],"spin":"none"}
]}
```

* `x`, `y` are the SRS true-rotation centre, `y = 0` at the bottom, exactly the
  convention `tbp.tbp_move_cells` implements. This is not an assumption:
  nana's `ShaktrisConstants.hpp::piece_definitions` and
  `generate_rot_piece_def()` use the same four cells and the same
  `(x, y) → (y, −x)` rotation as `CC_NORTH_CELLS` / `_cc_rotate_cell`.
* `spin` is nana's own classification (`none|mini|full`); the adapter ignores it
  and lets `spin_from_placement` re-classify under `tetrio_s2`.
* **No `move_info`**: `inputs` is always empty in this version, so there is no
  node count, NPS or search-depth telemetry. Only latency is recorded.

### 4.4 Pending garbage: what nana actually sees

This is narrower than the earlier survey wording suggested:

* nana reads **the opponent's** pending garbage (`opponents[0].meter`) and uses
  it in the opponent model / conditioning. Since our `opponent_state` is the
  side nana is attacking, this tells nana how much of its incoming attack is
  already sitting in the opponent's meter.
* nana does **not** initialise its own `EmulationGame::garbage_meter` from the
  TBP2 `start`; there is no field for our own pending garbage in its parser.
  It therefore cannot plan around garbage that is about to land on *its* board
  through this protocol. The top-level `meter` we send is ignored.

The adapter sends both fields (top-level for spec completeness, opponent object
for actual use) and documents the distinction in the module docstring.

---

## 5. Adapter behaviour (`NanaAgent`)

* **Profile** (`NANA_PROFILE`): `tbp_version=2`, `queue_mode="current_first"`,
  `b2b_type="int"`, `combo_offset=1`, `board_rows=40`,
  `requires_opponents=True`, `name="nana"`.
* **Launch**: `[nana_tbp]` with no argv (nana parses none); config is read from
  `nana.json` beside the binary. `TETRISRL_NANA_BIN` and
  `TETRISRL_NANA_CONFIG` override path resolution for tooling.
* **Timing**: `think_time=0.15 s` (the MCTS budget per placement) and
  `timeout=10 s` (suggestion deadline). nana answers `suggest` immediately
  after stopping search, so observed mean latency is ~150 ms at 2 threads.
  MCTS can overshoot under load; a timeout closes the process, increments
  `stats.timeouts`, and the move is played by the fallback.
* **Fallback**: inherited `HeuristicAgent`; a missing binary, timeout, protocol
  error, or unexpressible placement increments the corresponding counter and
  plays a legal heuristic move. Matches never crash on a broken engine.
* **Lifecycle**: lazy process launch; `terminate()` sends `quit`, closes stdin,
  waits, then kills if needed; reader threads are daemonic. `reset()` closes the
  session and clears counters.
* **Pytest guard**: the inherited guard refuses to spawn nana under pytest
  unless `allow_in_tests=True` is passed explicitly. Importing the module,
  constructing `NanaAgent`, and collecting tests never starts a process.
* **Fallback semantics**: the adapter uses `moves[0]` only and validates it
  against `state.legal_actions()`. It deliberately does not shop for a
  playable alternative, because that would hide a real compatibility gap.
* **Verified fallback cause**: the four-cell mapping is exact; the rejected
  suggestions are placements our hard-drop action space cannot encode
  (tucks/slides under overhangs). Example captured in game seed 1: nana asked
  for a Z north placement at cells `(4,35),(5,35),(5,36),(6,36)`, which is
  tucked under the filled cell `(6,35)` and therefore not reachable by a hard
  drop. The heuristic replaced it and the game continued.
* **Config safety**: `ensure_nana_config()` writes only the two keys nana
  accepts (`rules`, `threads`) and refuses invalid values; nana rejects unknown
  keys outright.

---

## 6. Tests

Command and observed result:

```bash
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_nana.py
# 20 passed in 3.86s
```

Pure-Python tests (always run): pinned commit constant, binary/config path
resolution and env overrides, executable check, TBP2 profile values, config
writer (known keys, no overwrite, invalid values), start-message fields,
`queue[0]=current`, 40 bottom-first rows, combo `-1→0` conversion, integer B2B,
opponent-meter propagation, synthetic opponent when `opponent_state=None`,
pytest launch guard, missing-binary fallback, agent naming/profile.

Real-engine tests (skipped when `nana_tbp` is absent): handshake reports
`Nana`; six raw suggestions decode to four cells, do not overlap, rest on the
board, and map to legal actions; six `choose_action` calls against a scripted
opponent are legal with no errors/timeouts; `choose_action` with no
`opponent_state` still works (the adapter synthesises `opponents[0]`); a raw
`start` without `opponents` kills the process (guard regression test); a full
`VersusMatch` smoke (40-piece cap) runs with zero invalid actions at the versus
layer.

Full suite (includes the 20 new tests):

```bash
.venv/bin/python -m pytest
# 248 passed in 21.44s
```

---

## 7. Actual match results (real nana)

Commands (exactly as run; one process per game, paired seeds 0–9, 300-piece
cap, 150 ms/move, 2 threads, `tetrio_s2` rules, nana as agent A and the
baseline as agent B):

```bash
.venv/bin/python scripts/run_nana_match.py --games 10 --opponent heuristic \
    --max-pieces 300 --json results/nana_match_heuristic.json
.venv/bin/python scripts/run_nana_match.py --games 10 --opponent random \
    --max-pieces 300 --json results/nana_match_random.json
```

Both exited 0; no game crashed and no series had errors. JSON reports:
`results/nana_match_heuristic.json`, `results/nana_match_random.json`.

### 7.1 Result summary

| Series | Score (W–L–D) | Win rate | Wilson 95 % CI | Games | Mean ticks | Wall time |
|---|---|---|---|---|---|---|
| nana vs heuristic | **6–4–0** | **60.0 %** | 31.3 % – 83.2 % | 10 | 66.5 | 106.19 s |
| nana vs random | **10–0–0** | **100.0 %** | 72.2 % – 100.0 % | 10 | 18.3 | 28.88 s |

All 20 matches ended by top-out: six wins vs heuristic by `top_out_b`, four
losses by `top_out_a`; all ten random games ended `top_out_b`. No match reached
the 300-piece cap; `invalid_actions == [0, 0]` in every game.

### 7.2 Per-game table — vs heuristic

| # | seed | outcome | reason | ticks | accepted | fallbacks | invalid | timeouts | wall (s) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | win | `top_out_b` | 26 | 26 | 0 | 0 | 0 | 4.09 |
| 2 | 1 | win | `top_out_b` | 63 | 56 | 7 | 7 | 0 | 9.90 |
| 3 | 2 | win | `top_out_b` | 46 | 46 | 0 | 0 | 0 | 7.23 |
| 4 | 3 | loss | `top_out_a` | 82 | 73 | 9 | 9 | 0 | 12.91 |
| 5 | 4 | loss | `top_out_a` | 55 | 43 | 12 | 12 | 0 | 8.75 |
| 6 | 5 | win | `top_out_b` | 85 | 76 | 9 | 9 | 0 | 13.40 |
| 7 | 6 | win | `top_out_b` | 84 | 74 | 10 | 10 | 0 | 13.36 |
| 8 | 7 | loss | `top_out_a` | 104 | 93 | 11 | 11 | 0 | 16.38 |
| 9 | 8 | loss | `top_out_a` | 31 | 20 | 11 | 11 | 0 | 4.93 |
| 10 | 9 | win | `top_out_b` | 89 | 78 | 11 | 11 | 0 | 14.05 |

### 7.3 Per-game table — vs random

| # | seed | outcome | reason | ticks | accepted | fallbacks | invalid | timeouts | wall (s) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | win | `top_out_b` | 17 | 14 | 3 | 3 | 0 | 2.62 |
| 2 | 1 | win | `top_out_b` | 16 | 16 | 0 | 0 | 0 | 2.45 |
| 3 | 2 | win | `top_out_b` | 13 | 13 | 0 | 0 | 0 | 1.99 |
| 4 | 3 | win | `top_out_b` | 14 | 14 | 0 | 0 | 0 | 2.14 |
| 5 | 4 | win | `top_out_b` | 18 | 17 | 1 | 1 | 0 | 2.76 |
| 6 | 5 | win | `top_out_b` | 21 | 19 | 2 | 2 | 0 | 3.22 |
| 7 | 6 | win | `top_out_b` | 16 | 16 | 0 | 0 | 0 | 2.45 |
| 8 | 7 | win | `top_out_b` | 18 | 17 | 1 | 1 | 0 | 2.76 |
| 9 | 8 | win | `top_out_b` | 27 | 22 | 5 | 5 | 0 | 4.15 |
| 10 | 9 | win | `top_out_b` | 23 | 21 | 2 | 2 | 0 | 3.52 |

### 7.4 Engine telemetry

| Metric | vs heuristic | vs random |
|---|---|---|
| nana suggestions | 665 | 183 |
| Accepted placements | 585 | 169 |
| Invalid suggestions → heuristic fallback | 80 | 14 |
| Fallback rate | **12.03 %** | **7.65 %** |
| Timeouts | 0 | 0 |
| Protocol errors | 0 | 0 |
| Engine starts (processes) | 10 | 10 |
| Mean answer latency | 150.69 ms | 150.50 ms |
| Nodes total / per move | **not exposed (0)** | **not exposed (0)** |

### 7.5 Per-player averages (10 games each)

**vs heuristic**

| Player | Pieces | Lines | Attack | Sent | Recv | Inserted | T-spins | Tetrises | B2B max | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nana | 66.4 | 28.4 | 31.3 | 29.2 | 11.9 | 9.8 | 4.8 | 1.1 | 1.6 | 10.3 | 8.7 |
| Heuristic | 66.4 | 35.5 | 15.5 | 11.9 | 27.9 | 24.2 | 1.0 | 1.1 | 0.8 | 15.9 | 11.7 |

**vs random**

| Player | Pieces | Lines | Attack | Sent | Recv | Inserted | T-spins | Final height | Final holes |
|---|---|---|---|---|---|---|---|---|---|
| nana | 18.3 | 5.7 | 7.2 | 7.2 | 0.0 | 0.0 | 1.3 | 3.2 | 2.1 |
| Random | 18.3 | 0.1 | 0.0 | 0.0 | 6.8 | 6.8 | 0.0 | 23.9 | 58.3 |

The random baseline cleared only one line across all ten games (0.1 per game)
and topped out after ~18 pieces under
the first garbage batches — a sanity check that nana's attacks reached it. The
heuristic series is more informative: nana produced ~2× the attack and kept a
lower, cleaner board, but still lost 4/10 games, and its fallback rate was
higher in longer, messier games.

### 7.6 Interpretation limits

These are 20 games on paired seeds, not a strength estimate. The 6–4 record has
a Wilson 95 % CI of **31.3 %–83.2 %** (n=10); 10–0 gives **72.2 %–100 %**. nana
was handicapped by 150 ms/move, 2 threads, no 180°, Season 1 damage, a 32-row
view, and a **7.65–12.03 % fallback rate** — far above the <1 % guardrail in
`docs/OPPONENTS.md`. That fallback rate means roughly one in eight to one in
twelve of nana's chosen placements was replaced by the heuristic, so these
matches measure "nana with a tuck-blind action-space filter", not nana's full
strength.

---

## 8. Compatibility limitations (explicit)

1. **Placement suggester, not a simulator.** nana receives a board, queue, hold,
   combo, B2B and (opponent) meter and returns placements. It does not simulate
   our match, attack tables, cancellation or garbage insertion; the arena
   remains the single authority.
2. **Season 1, not Season 2.** `nana.json`'s `"rules": "tetrio"` selects
   `modes/TetrioS1.hpp`: S1 damage, S1 B2B chain power and S1 combo table. It
   has no TETR.IO S2 B2B charging, surge segments, or S2 cancellation. All of
   that is recomputed by `tetrisrl`.
3. **No 180° rotation.** nana implements guideline SRS wall kicks (`srs_rotate`)
   and has no 180° path. Placements requiring our 180° are unavailable to it.
4. **No SRS+ guarantee.** nana's kicks are guideline SRS (`piece_offsets_*`),
   not TETR.IO SRS+; our engine still validates/applies placements with SRS+.
5. **32-row board.** `Board::height = 32`; the top 8 rows of the 40-row wire
   board are ignored. A stack above row 32 (our rows 0–7) is invisible to nana,
   so its suggestions there can be invalid or overhang-dependent.
6. **Hard-drop action space vs. reachable-placement search.** nana's movegen
   includes tucks/slides/spin entries; our action encoding is
   `(rotation, column, hold)` hard drops. Rejected placements are counted and
   played by the heuristic: 80/665 (12.03 %) vs heuristic, 14/183 (7.65 %) vs
   random. This is the largest compatibility gap and directly weakens nana.
7. **No search telemetry.** The suggestion has no `move_info`/nodes, so the
   adapter cannot report nodes per move or verify search effort; only latency is
   available.
8. **Own pending garbage is not modelled.** nana reads only
   `opponents[0].meter`; it cannot plan around garbage about to land on its own
   board through TBP2. (It does condition on the opponent's meter.)
9. **No randomizer state.** The adapter omits `randomizer`, so nana does not
   speculate our seven-bag; this is a deliberate non-leak and a small handicap.
10. **Nondeterminism.** nana is a threaded MCTS with time-based search and
    random outcomes; matched seeds do not make its suggestions bit-identical.
    Our replays record chosen actions, so replay verification remains
    deterministic.
11. **One process per game, no persistent session.** The runner starts a fresh
    nana per game; `start` per piece rebuilds its emulation game (it does keep
    its UCT tree via `continueSearch`). No `play` stream is used.
12. **No claim about Season 2 strength.** The matches say only that the binary
    played legally under our ruleset and beat two simple baselines.

---

## 9. Reproduce everything

```bash
cd /home/alfi/Active/tetrlio

# 1. Clone + build the pinned engine (once).  Install cmake if it is not on PATH.
git clone --recurse-submodules https://github.com/nightcrab/nana third_party/nana
git -C third_party/nana checkout 3cb49c6cc680f07282382de2862f1aa656d9afa1
git -C third_party/nana submodule update --init --recursive
uv pip install --python .venv/bin/python cmake            # only if cmake is missing
.venv/bin/cmake -S third_party/nana -B third_party/nana/build -DCMAKE_BUILD_TYPE=Release
.venv/bin/cmake --build third_party/nana/build -j
printf '{\n  "rules": "tetrio",\n  "threads": 2\n}\n' > third_party/nana/build/cpp/nana.json

# 2. Adapter/protocol/lifecycle tests (real-engine tests auto-run when built)
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_nana.py
# observed: 20 passed in 3.86s

# Full suite
.venv/bin/python -m pytest
# observed: 248 passed in 21.44s

# 3. Real matches (this produced §7)
.venv/bin/python scripts/run_nana_match.py --games 10 --opponent heuristic \
    --max-pieces 300 --json results/nana_match_heuristic.json
.venv/bin/python scripts/run_nana_match.py --games 10 --opponent random \
    --max-pieces 300 --json results/nana_match_random.json
```

The real-engine tests skip automatically when
`third_party/nana/build/cpp/nana_tbp` is absent (`nana_available()`), so the
suite still runs on a clean checkout. Environment overrides:
`TETRISRL_NANA_BIN=/path/to/nana_tbp`,
`TETRISRL_NANA_CONFIG=/path/to/nana.json` (tooling only; nana itself reads the
file beside the executable).

---

## 10. Non-claims

* We did **not** modify nana's source; the clone is at the pinned commit and
  the built binary reports `Nana 0.1`.
* We did **not** use nana's own attack/garbage rules as the authority; every
  competitive rule was enforced by `tetrisrl`.
* We did **not** benchmark nana's strength. The 6–4 and 10–0 records are small
  paired-seed samples against a one-ply heuristic and a uniform-random agent,
  with a seated 7.65–12.03 % heuristic substitution rate.
* No node counts are reported because nana v0.1 exposes none; `0` in the JSON
  report means "not exposed", not "searched zero nodes".
