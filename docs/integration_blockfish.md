# Blockfish integration — cheese/downstacking specialist

**Status: integrated as a clearly-labelled cheese/downstacking specialist.**
A real external blockfish build was compiled, launched as a subprocess, and it
produced placements in real versus matches against our heuristic and random
baselines. **It is not a versus benchmark**: blockfish models neither versus
play nor TETR.IO Season 2, and its match results below are adapter-validation
evidence, not a competitive strength claim.

| Field | Value |
|---|---|
| Upstream | https://github.com/blockfish/blockfish |
| Pinned commit | `739953f9331b7648f269fc52cff5aae330108ccd` (2025-07-13, "Merge pull request #11 from yaahc/rate-last-move") |
| License | **LGPL-2.1** (no "or later" clause), retained at `third_party/blockfish/LICENSE.txt` |
| Adapter | `tetrisrl/agents/opponents/blockfish.py` |
| Tests | `tetrisrl/tests/test_opponents_blockfish.py` (10 tests, all passing) |
| Match runner | `scripts/run_blockfish_match.py` |
| LGPL notice | `third_party/BLOCKFISH_NOTICE.md` |
| Metadata | `BlockfishAgent.specialist == "cheese"`, `is_versus_benchmark == False` |

---

## 1. Clone and pin

```bash
cd /home/alfi/Active/tetrlio
git clone https://github.com/blockfish/blockfish third_party/blockfish
git -C third_party/blockfish rev-parse HEAD
# 739953f9331b7648f269fc52cff5aae330108ccd
```

`third_party/blockfish/` is a local clone + build tree and is ignored by
`.gitignore` (`third_party/*` with exceptions). The notice and the upstream
`LICENSE.txt` stay with the clone.

## 2. Build result

Toolchain on the build machine:

```text
$ which protoc
/usr/bin/protoc
$ protoc --version
libprotoc 36.1
$ rustc --version
rustc 1.100.0 (0ef1bc386 2026-11-09) (Arch Linux rust 1:1.100.0-1)
$ cargo --version
cargo 1.100.0 (3acc79c0c 2026-11-05) (Arch Linux rust 1:1.100.0-1)
```

Build command (the service binary is the `blockfish` bin behind the `service`
feature, which pulls `protos`, `protobuf`, `protoc-rust` and
`pretty_env_logger`):

```bash
cd third_party/blockfish
cargo build --release -p blockfish --features service
```

**Result: success.** `Finished release profile [optimized] target(s) in
13.21s`, exit code 0, warnings only (deprecated `std::usize::MAX` and generated
protobuf lifetime warnings). `protoc` was present, so no pure-Rust protobuf
fallback was needed; blockfish's `build.rs` invokes `protoc-rust` with
`blockfish.proto` when the `protos` feature is enabled.

Artifact and hash:

```text
third_party/blockfish/target/release/blockfish
sha256 b564d61775268b955ed5a6baae3dd16e2c1cd965dab197be46075d82a3c803cb
```

Locked dependency versions used by the build (`Cargo.lock`): `protobuf 2.27.1`,
`protoc-rust 2.27.1`; the rest are the workspace's normal Rust crates
(`thiserror`, `log`, `serde`, `serde_json`, `red_union_find`, plus optional
`pretty_env_logger` for the service). No GPU, SDL2, or Python protobuf package
is required: the adapter implements the small wire subset itself.

Override the binary path with `TETRISRL_BLOCKFISH_BIN` if you build elsewhere.

## 3. Protocol (verified against the pinned source)

Blockfish's service is `blockfish-engine/src/bin/service.rs` with messages from
`blockfish.proto`. It is **length-delimited protobuf over stdin/stdout**: each
message is a protobuf varint length followed by the serialized message
(`CodedInputStream::read_message` / `write_message_no_tag`). The service sends
a `Response.greeting` at startup and then one `Response.finished` per
`Request.analyze`.

Request messages we send:

* `Request.set_config` (`Request.Config`): `node_limit` = field 1,
  `max_results` = field 3, `max_placements` = field 4 (field 2 is unused in the
  proto). We send `node_limit`, `max_results=1`, `max_placements=1`.
* `Request.analyze`: `id` (field 1), `snapshot` (field 2).
* `Snapshot`: `hold` string (1), `queue` string (2), `rows` repeated string (3).
* `set_ruleset` is deliberately not sent: `service.rs::set_ruleset` is a no-op
  that logs "`set_ruleset` is useless currently"; the engine always uses its
  compiled-in guideline SRS table.

Response messages we parse:

* `Response.greeting`: `version` (1), `motd` (2).
* `Response.finished`: `id` (1), `stats` (2: nodes=1, iterations=2,
  time_taken_millis=3), repeated `suggestions` (3).
* `Suggestion`: `rating` (**sint64**, field 1; lower is better) and packed
  `inputs` (field 2, enum varints).
* `Input` enum values: `LEFT=0, RIGHT=1, CW=2, CCW=3, HOLD=4, SD=5, HD=6`.
  `SD` is a sonic/hard drop in blockfish, not a soft-drop tick.

The adapter is stateless per request: it sends a complete snapshot for every
piece. `BlockfishAgent._request_analysis` validates the response `id`, parses
the first suggestion, and closes/reopens the session on timeout or protocol
error.

## 4. Board, queue, and action mapping

### Board

Blockfish's ruleset is 10x25 (20 visible + 5 hidden), while our board is 10x40
(20 visible + 20 hidden buffer). The mapping is explicit:

1. Take our **bottom 25 rows**: `board.rows[height-25 : height]` (top-down,
   i.e. our rows 15..39 for a 40-row board).
2. Reverse them to blockfish's **bottom-first** row order: our bottom row
   becomes blockfish row 0 (documented in `blockfish-js/src/ai.js`; also how
   `service.rs::matrix` indexes the first string).
3. Encode each row as a 10-character string: `X` occupied, `.` empty. Any
   alphabetic character counts as occupied in blockfish (`Color::try_from`).
4. Our rows above that 25-row window are **not** silently inserted into the
   snapshot. If any of them are occupied they are counted in
   `BlockfishAgent.stats.board_rows_unrepresentable`; this can only happen when
   the stack has reached the hidden buffer (near top-out).

Our occupancy bitboard has no garbage provenance, so every block is sent as
`X`; blockfish's cheese model only cares about occupancy.

### Queue and hold

* `queue = [current_piece, *previews]` with our configured preview count
  (5 by default, matching blockfish's own preview count).
* `hold = state.hold` when present, otherwise the empty string.
* Blockfish's `State::next()` treats `queue[0]` as the current piece and derives
  the hold target itself, matching our hold semantics.

### From suggested inputs to our action id

Blockfish returns a key sequence, not a final `(x, y, rotation)`:

```text
inputs = [hold, right, right, cw, sd, hd]   # example shape
```

Our conversion replays the sequence on our own board:

1. Start from our current active piece (or the hold/next piece if the sequence
   begins with `hold`), at our spawn position.
2. Apply `left`/`right` one column when the moved cells fit; apply `cw`/`ccw`
   with **guideline SRS** kicks (blockfish's ruleset; the module caches
   `build_kick_tables("srs")`); apply `sd`/`hd` as a sonic drop to the floor.
3. The final four cells are compared against every placement returned by
   `state.legal_actions()` (`state.resolve(action)` gives the concrete cells).
   An exact cell-set match wins, preferring the correct hold bit.
4. If there is no exact match, a legal action with the same piece, rotation and
   left-most column is accepted as an **approximation** and counted in
   `stats.accepted_approx`. This keeps a suggested orientation/column when the
   engine's tuck path differs from our placement resolver. It is still a legal
   action.
5. Otherwise the adapter falls back to `HeuristicAgent`, increments
   `stats.fallbacks` (and `stats.rejected`), and records `last_error`. Every
   returned action is in `state.legal_actions()`; the adapter never returns an
   invalid id.

Our action encoding is unchanged: `action = rotation * 20 + column * 2 + hold`,
with `column` the piece's left-most occupied column (`tetrisrl/environment/actions.py`).

Mapping caveats, explicitly:

* Blockfish has no 180-degree rotation, so suggestions never use it.
* Blockfish uses guideline SRS, not our SRS+; I-piece kick test *order* differs.
  The replay uses guideline SRS (blockfish's ruleset) and the exact-cell check
  is the final validator.
* Rotations/tucks that our placement resolver cannot express (for example a
  sequence of sonic drops and moves into an overhang) cannot be mapped; those
  are the measured fallbacks.

## 5. Tests

```bash
cd /home/alfi/Active/tetrlio
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_blockfish.py -q
```

Result: **10 passed** (`.......... [100%]`). The live-engine tests are marked
`skipif` when the binary is absent; the fallback test never needs an engine.

Coverage:

* availability and `TETRISRL_BLOCKFISH_BIN` override;
* bottom-first 10x25 board mapping and unrepresentable-row counting;
* queue starts with the current piece;
* input replay maps to a legal action (`hd` and `hold, hd` cases);
* one live engine suggestion mapped to a legal action;
* fallback to the heuristic on an unavailable engine;
* lifecycle launch/terminate/relaunch and engine-start counters.

## 6. Real matches

All matches use the `tetrio_s2` ruleset, `max_pieces=200`, blockfish node limit
20,000 per piece, seeds 0..4, and the in-repo baselines. Our engine owns attack,
garbage insertion/cancellation, B2B charging and Surge; blockfish only chooses
placements.

```bash
cd /home/alfi/Active/tetrlio
.venv/bin/python scripts/run_blockfish_match.py \
    --vs heuristic random --games 5 --max-pieces 200 --seed 0
```

The rerun of the heuristic series produced identical results (deterministic
given the seeds and node limit).

### blockfish vs heuristic — 0 wins, 3 losses, 2 draws

| game | seed | outcome | reason | ticks | accepted | approx | rejected | fallbacks |
|---:|---:|---|---|---:|---:|---:|---:|---:|
| 1 | 0 | draw | max_pieces | 200 | 200 | 0 | 0 | 0 |
| 2 | 1 | loss | top_out (blockfish) | 63 | 63 | 11 | 0 | 0 |
| 3 | 2 | draw | max_pieces | 200 | 200 | 0 | 0 | 0 |
| 4 | 3 | loss | top_out (blockfish) | 61 | 60 | 9 | 1 | 1 |
| 5 | 4 | loss | top_out (blockfish) | 186 | 184 | 13 | 2 | 2 |
| **total** | | **0–3–2** | | | **707** | **33** | **3** | **3** |

Fallback rate: 3 / (707 + 3) = **0.4%**. 707 real blockfish suggestions were
mapped to legal placements.

### blockfish vs random — 5 wins, 0 losses, 0 draws

| game | seed | outcome | reason | ticks | accepted | approx | rejected | fallbacks |
|---:|---:|---|---|---:|---:|---:|---:|---:|
| 1 | 0 | win | top_out (random) | 24 | 24 | 0 | 0 | 0 |
| 2 | 1 | win | top_out (random) | 23 | 23 | 6 | 0 | 0 |
| 3 | 2 | win | top_out (random) | 18 | 18 | 0 | 0 | 0 |
| 4 | 3 | win | top_out (random) | 22 | 22 | 0 | 0 | 0 |
| 5 | 4 | win | top_out (random) | 21 | 21 | 0 | 0 | 0 |
| **total** | | **5–0–0** | | | **108** | **6** | **0** | **0** |

Blockfish only wins against random because random tops out quickly; this says
nothing about versus strength. Against the heuristic it topped out three times
and reached the 200-piece cap twice.

### Interpretation — not a competitive benchmark

* Blockfish's objective is **downstacking a cheese stack in as few pieces as
  possible**, not winning a versus match. It does not plan attacks, does not
  see pending garbage, and has no B2B/Surge model. Any attack credited to it
  was computed by our engine from the placement it chose.
* The sample is 5 games per baseline, with a 200-piece cap. It is an adapter
  smoke test with concrete placements, not a statistically meaningful
  comparison.
* Do not cite "5–0 vs random" as competitive strength; cite it as evidence that
  the adapter produces legal placements and that the specialist can survive /
  downstack against a weak baseline.

## 7. Limitations (explicit)

1. **Not a versus engine.** No attack, garbage queue, B2B charge, Surge,
   combo strategy, or Season 2 model. Versus results are dominated by our
   engine's rules, not blockfish's competitive skill.
2. **Guideline SRS only.** No 180, no spin detection; SRS+ I-kick order can
   differ from what blockfish replayed. Exact-cell matching is the guard.
3. **25-row snapshot.** Our top 15 rows are outside blockfish's board. Near
   top-out, occupied cells there cannot be represented and are counted in
   `board_rows_unrepresentable` rather than silently dropped without a trace.
4. **Reachability.** Some suggestions use tuck/soft-drop paths our placement
   action space cannot express; those fall back to the heuristic and are
   counted (0.4% against the heuristic in this run).
5. **No protocol garbage channel.** Blockfish cannot be told about pending
   garbage; it only sees garbage that has already been inserted into the board.
6. **Service is stateless.** Every piece re-sends the full snapshot; there is no
   incremental tree reuse, so throughput is bounded by one analysis per piece.
7. **Small sample.** Five games per baseline at `max_pieces=200`; no confidence
   intervals or significance claims are made.

The integration is nevertheless real: a compiled external engine was launched,
read our boards, returned key sequences, and **707 + 108 placements** were
converted into legal actions across the two series.

## 8. LGPL-2.1 compliance

* blockfish is **LGPL-2.1** (no "or later"). The upstream `LICENSE.txt` is
  retained at `third_party/blockfish/LICENSE.txt`; see
  `third_party/BLOCKFISH_NOTICE.md`.
* The engine is used **only as a separate subprocess**. No blockfish source is
  copied, translated, linked into, or embedded in `tetrisrl`; the adapter is our
  own code implementing the public protobuf service interface.
* Redistribution of a build containing the blockfish binary must include the
  LGPL-2.1 text and the upstream copyright notice, and satisfy LGPL-2.1 §6
  (make the corresponding source available — the pinned upstream commit is the
  exact source).
* The clone/build tree is not committed (`.gitignore` excludes
  `third_party/*` except notices and license files); `third_party/BLOCKFISH_NOTICE.md`
  is tracked.

## 9. Reproduce

```bash
# 1. clone at the pin
git clone https://github.com/blockfish/blockfish third_party/blockfish
git -C third_party/blockfish checkout 739953f9331b7648f269fc52cff5aae330108ccd

# 2. build the service (protoc required)
(cd third_party/blockfish && cargo build --release -p blockfish --features service)

# 3. availability + tests
.venv/bin/python -c "from tetrisrl.agents.opponents.blockfish import blockfish_available; print(blockfish_available())"
.venv/bin/python -m pytest tetrisrl/tests/test_opponents_blockfish.py -q

# 4. real matches (not a versus benchmark)
.venv/bin/python scripts/run_blockfish_match.py \
    --vs heuristic random --games 5 --max-pieces 200 --seed 0

# 5. optional JSON record
.venv/bin/python scripts/run_blockfish_match.py \
    --vs heuristic --games 1 --max-pieces 200 --json /tmp/blockfish_match.json
```
