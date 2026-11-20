# BENCHMARKS — Open-Source Tetris AI Opponents

**Status:** research complete. Integration update: Cold Clear 2 was subsequently cloned, built and executed; see `docs/BENCHMARKS_INTEGRATION.md` for the executed match results and limitations. Everything else in this document remains a survey.
**Verification date:** 2026-11-20.
**Author:** Opponent Researcher (subagent).
**Scope:** discover and verify open-source Tetris AI engines usable as local versus
opponents for RLTris under TETR.IO Season 2 / SRS+ mechanics, and specify a genuine
search-based in-repo baseline in case no external engine is usable offline.

---

## 0. Method and evidence limits

What was actually checked, per candidate:

* repository metadata from the GitHub REST API (`api.github.com/repos/...`):
  stars, forks, language, license, created/pushed timestamps, archived flag, default branch;
* release and commit history from the GitHub API;
* repository trees from the GitHub contents API;
* raw `README`, `LICENSE`, protocol headers and source files from `raw.githubusercontent.com`;
* negative results from GitHub repository search.

Limits that must be respected when reading this document:

* **`web_search` failed for the entire session** with `HTTP 401 UNAUTHORIZED`
  (invalid/missing token). All discovery therefore went through the GitHub API and
  direct repository pages. This biases discovery toward GitHub and away from
  blogs/Discord/Hard Drop posts; a project that exists only off-GitHub would have
  been missed.
* The unauthenticated GitHub API rate limit (60 req/h) was **exhausted** partway
  through. A few directory listings therefore come from repo descriptions or
  partial data and are marked `[UNVERIFIED]`.
* **No repository was cloned, no dependency installed, no engine was built or run.**
  Every "build requirements" line is read from documentation/manifests, not proven
  by a local build. Every strength number is either self-reported by the project or
  absent.
* Star counts and dates are point-in-time (2026-11-20) and are used as a weak
  proxy for adoption, not as a quality judgement.

**Central finding.** No verified, permissively licensed, actively maintained
open-source engine implements the full TETR.IO **Season 2** attack model
(B2B charging, surge, Season 2 garbage/cancellation). The only project that claims
S2 support is `seipass/intetrigence` (AGPL-3.0, 6 days old, 0 stars, unvetted).
Therefore the arena must own the ruleset, and external engines should be used only
as **placement suggesters** (board + queue + hold + B2B/combo in, placement out),
never as the authority on TETR.IO mechanics.

---

## 1. TL;DR

| # | Project | License | Lang | Activity | Versus/garbage | Protocol | Verdict |
|---|---------|---------|------|----------|----------------|----------|---------|
| 1 | [MinusKelvin/cold-clear](https://github.com/MinusKelvin/cold-clear) | MPL-2.0 | Rust | archived 2022-01 | yes (garbage count in, board reset) | C API (`c-api`), TBP, Rust lib | **ACCEPT-WITH-ADAPTATION** (top pick) |
| 2 | [MinusKelvin/cold-clear-2](https://github.com/MinusKelvin/cold-clear-2) | MIT OR Apache-2.0 | Rust | last commit 2022-06 | board+queue; garbage via host | TBP JSON-lines | **ACCEPT-WITH-ADAPTATION** |
| 3 | [ruelalarcon/frostetra](https://github.com/ruelalarcon/frostetra) | MIT | Rust | active 2026-11 | not evidenced | SBP JSON-lines | **ACCEPT-WITH-ADAPTATION** (experimental) |
| 4 | [RIKU0804/tetris-ai](https://github.com/RIKU0804/tetris-ai) | MIT | Rust + Python | 2026-06 | yes (own versus + garbage) | TBP JSON-lines | **ACCEPT-WITH-ADAPTATION** |
| 5 | [souta-lab/attax](https://github.com/souta-lab/attax) | AGPL-3.0 | TS + Rust/WASM | active 2026-11 | guideline + S2 profile | none (TBP adapter removed) | **REJECT** (GPU-only, AGPL, no protocol) |
| 6 | [seipass/intetrigence](https://github.com/seipass/intetrigence) | AGPL-3.0-only | Rust | 2026-11 (new) | S2 claimed, own arena | TBP host + own arena | **REJECT** as dependency; S2 reference only |
| 7 | [misakamm/MisaMino](https://github.com/misakamm/MisaMino) | "Copyleft by Misakamm" (non-OSI) | C++ | 2015 (dead) | yes (TOJ-style) | Windows DLL C ABI | **REJECT** for direct use; reference-only |
| 8 | [ZetrisAI/Zetris](https://github.com/ZetrisAI/Zetris) | BSD-3-Clause | C# | 2025-08 | plays real PPT/TETR.IO by screen capture | none | **REJECT** (not a library; Windows GUI) |
| 9 | [blockfish/blockfish](https://github.com/blockfish/blockfish) | LGPL-2.1 | Rust | 2025-07 | **no** (cheese race only) | protobuf over stdin + Python binding | **REJECT** for versus; cheese-only diagnostic |
| 10 | [tetris-bot-protocol/tbp-spec](https://github.com/tetris-bot-protocol/tbp-spec) | none declared | spec | 2021 | board `"G"` cells, combo, B2B | JSON lines | protocol reference, not a bot |

**Recommended top pick for integration: Cold Clear (v1), via its documented C API**
(`c-api/coldclear.h`), with the S2 arena supplying the board, hold, queue, B2B,
combo and **incoming garbage count** each piece and applying the returned placement
itself. If that build is impractical, fall back to Cold Clear 2 or `RIKU0804/tetris-ai`
over TBP (JSON lines). The in-repo beam-search baseline (§7) is **mandatory
regardless**: it is the only opponent guaranteed to exist offline and to share the
exact SRS+/Season 2 mechanics.

---

## 2. Compatibility matrix

Legend: ✅ documented/implemented · ⚠️ partial or claim-only · ❌ no · `?` unverified.

| Mechanic | Cold Clear 1 | Cold Clear 2 | frostetra | RIKU0804 | Attax | intetrigence | MisaMino | Blockfish |
|---|---|---|---|---|---|---|---|---|
| SRS | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (SRS+?) | ⚠️ own kicks | ✅ |
| SRS+ kicks | ? | ? | ✅ (claim) | ? | ✅ (guideline/S2 profiles) | ✅ (claim) | ❌ (TOJ-ish) | ❌ |
| 180° rotation | ❌ (no 180 in C API) | ? | ✅ (claim) | ? | ? | ✅ (claim) | ✅ (`can180spin`) | ❌ |
| 7-bag randomizer | ✅ | ✅ | ✅ (claim) | ✅ | ✅ | ✅ | ? (own) | ✅ |
| Hold | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| T-spin (full/mini) | ✅ (`CCTspinStatus`) | ? | ? | ✅ (3-corner) | ✅ | ✅ | ✅ | ❌ |
| Combo / B2B | ✅ (in/out) | ✅ (TBP start) | ? | ✅ | ✅ | ✅ | ✅ | ❌ |
| Garbage queue / cancel | external (`incoming`) | external (host) | not evidenced | ✅ internal | ✅ (own sim) | ✅ (S2) | ✅ (own rules) | ❌ |
| TETR.IO Season 2 attack | ❌ | ❌ | ❌ | ❌ | ⚠️ profile, 38% vs S2 champ (self-reported) | ⚠️ claimed | ❌ | ❌ |
| Versus | ✅ (host-driven) | ✅ (host-driven) | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| 40L / cheese | ❌ / ❌ | ❌ / ❌ | solo only | solo + versus | guideline + S2 | S2 | 40L/race mode | ✅ cheese 100L only |

---

## 3. Candidate dossiers

### 3.1 Cold Clear (v1) — `MinusKelvin/cold-clear`

* **URL:** https://github.com/MinusKelvin/cold-clear
* **License (exact):** Mozilla Public License 2.0 (`LICENSE`, 16,725 bytes). Weak,
  file-level copyleft: modifying Cold Clear files obliges publishing those files;
  linking/aggregating is permitted. Compatible with a proprietary or MIT project as
  long as Cold Clear's own files stay MPL.
* **Language:** Rust (workspace: `bot/`, `libtetris/`, `battle/`, `c-api/`, `tbp/`,
  `cc-client/`, `opening-book/`, `optimizer/`, `compare/`).
* **Activity:** 278★, 74 forks, **archived** (read-only), last commit 2022-01-18,
  releases up to `v0.1-alpha5` (2020-07-06, `cold-clear.exe` only). Effectively dead,
  but stable and widely used as a reference.
* **Build/runtime:** Rust toolchain; `cargo build --release -p c-api` for a static +
  shared C library; `cargo run --release` for the desktop client. The `bot` crate
  pulls `pcf` from a **git dependency**
  (`https://github.com/MinusKelvin/pcf`, rev `64cd955`), so an offline build needs
  that vendored. No system libraries for the C API; the client needs graphics/SDL-ish
  stack.
* **Dependencies:** `arrayvec`, `rand`, `enumset`, `enum-map`, `odds`, `serde`,
  `smallvec`, `bumpalo`, `ouroboros`, `rayon`, `crossbeam-channel`, git `pcf`.
* **Mechanics:** SRS rotation with wall kicks; T-spin classification
  (`CC_NONE`/`CC_MINI`/`CC_FULL`); B2B and combo tracked; board is 10×40 booleans;
  spawn rules `ROW_19_OR_20` and `ROW_21_AND_FALL`; movement modes `0G`, `20G`,
  `HARD_DROP_ONLY`; optional opening book; perfect-clear loop priority
  (`PC_OFF`/`PC_FASTEST`/`PC_ATTACK`). **No 180° movement in the C API** (enum is
  `LEFT, RIGHT, CW, CCW, DROP`).
* **Modes:** versus (the `battle` crate has `garbage_queue`, `garbage_blocking`,
  `garbage_messiness`, `max_garbage_add`, attack/cancel logic) and solo search.
  Not a 40L or cheese-race bot.
* **Integration path:** best-in-class for our use case.
  `cc_launch_with_board_async(options, weights, book, field, bag_remain, hold, b2b, combo, queue, count)`
  starts a bot mid-game; `cc_request_next_move(bot, incoming)` passes the number of
  garbage lines expected after the next placement; `cc_poll_next_move` /
  `cc_block_next_move` return a `CCMove` (hold flag, expected 4 cell coordinates,
  movement path, nodes, depth, rank) plus an optional multi-placement plan; after
  garbage lands, call `cc_reset_async(bot, field, b2b, combo)` and continue.
  Wrap the `cdylib` with `ctypes` (no C++ compiler needed on our side), or drive the
  `tbp` adapter as a subprocess using JSON lines.
* **Ruleset caveat:** Cold Clear's own `battle` crate is *not* TETR.IO Season 2:
  garbage is a simple count with messiness and cancel, no surge, no B2B charging.
  We must not use its battle module for scoring. Use only the search/placement API and
  let `tetrisrl` own S2 scoring, garbage, cancellation and surge. Because Cold Clear
  cannot use 180°, it is a slightly handicapped but still legitimate opponent;
  document the deviation. SRS+ kick differences vs. Cold Clear's SRS are unverified.
* **Verdict: ACCEPT-WITH-ADAPTATION.** This is the strongest *practical* external
  benchmark: a mature, well-known versus bot with a documented, stable C API that
  already accepts incoming garbage, B2B, combo and an arbitrary mid-game board — the
  exact boundary our arena needs. The adaptations are mechanical (ctypes shim, board
  conversion, reset-on-garbage, no-180 handicap, ignore its battle rules), not
  algorithmic. MPL-2.0 is acceptable for a research repository as long as we do not
  relicense Cold Clear's files. The archive status is a reproducibility *advantage*
  (the benchmark will not drift), provided the `pcf` git dependency is vendored.

### 3.2 Cold Clear 2 — `MinusKelvin/cold-clear-2`

* **URL:** https://github.com/MinusKelvin/cold-clear-2
* **License:** dual **MIT OR Apache-2.0** (`Cargo.toml`: `license = "MIT OR Apache-2.0"`;
  `LICENSE-APACHE`, `LICENSE-MIT`). GitHub detects Apache-2.0. Most permissive of the
  real versus engines.
* **Language:** Rust (single crate `cold-clear-2`, rlib + cdylib + bin).
* **Activity:** 71★, last commit 2022-06-29, **no releases**, unmaintained, not
  archived. A "complete rewrite and evolution" of Cold Clear; the README advertises
  column-major bitboards, multithreaded search, transposition-aware game tree and
  MCTS-inspired expansion.
* **Build/runtime:** `cargo build --release`; all dependencies are crates.io
  (`ahash`, `bumpalo-herd`, `enum-map`, `enum_dispatch`, `enumset`, `futures`,
  `nohash`, `once_cell`, `ordered-float`, `ouroboros`, `parking_lot`, `puffin`,
  `rand`, `serde`, `serde_json`, `structopt`). No git dependencies, so it is the
  easiest of the three Cold Clear variants to build offline after `cargo vendor`.
* **Protocol:** JSON messages, one per line, over stdin/stdout — verified in
  `src/main.rs` (serde_json read/write loop). README states it implements the
  **Tetris Bot Protocol** (TBP). `src/lib.rs` exposes `run(incoming, outgoing, config)`.
* **Mechanics:** standard guideline engine (10×40 board, SRS, 7-bag, hold, B2B,
  combo per TBP `start`). 180° support not stated in README/API docs — **unverified,
  assume no**. No built-in versus/garbage; the host inserts garbage and supplies a new
  board (TBP `start` rebuilds state, which is expensive if done every garbage tick).
  TBP itself carries combo and B2B, so the bot's evaluation is aware of them, but not
  of an incoming-garbage *count*.
* **Integration path:** run the binary as a subprocess, speak TBP JSON lines
  (`info → rules → ready → start → suggest → suggestion → play → new_piece → stop`).
  Our arena can send `start` once per garbage insertion (or after each lock, if we
  accept the cost), and must ignore the bot's movement path, using only its target
  placement. Alternative: link the `rlib` (Rust only; bad fit for Python) or the
  `cdylib`.
* **Verdict: ACCEPT-WITH-ADAPTATION.** The cleanest license and the simplest protocol
  of the mature engines, and a stronger search design on paper than v1. The costs are
  the missing incoming-garbage input (the host must restart or rebuild state per
  garbage event), no release artifacts, no proof it was ever finished, and no 180°.
  A good secondary benchmark and the best choice if MPL-2.0 is unacceptable.
  Not the top pick only because it is less proven than v1 and its TBP front-end has
  not been smoke-tested here.

### 3.3 frostetra — `ruelalarcon/frostetra`

* **URL:** https://github.com/ruelalarcon/frostetra
* **License:** MIT (`LICENSE.txt`, 1,111 bytes).
* **Language:** Rust (binary `frostetra`), JSON config.
* **Activity:** 0★, created 2026-06-11, last push 2026-11-04 (default branch `master`),
  322 KB. Single-author, no adoption, very new.
* **Build/runtime:** `cargo build --release`; stable Rust; no system libraries;
  expects an SBP runner (e.g. `ruelalarcon/minorail`, MIT, Python) or a custom client.
* **Protocol:** **SBP** ("Stacker Bot Protocol") JSON messages over stdin/stdout.
  Spec: https://github.com/ruelalarcon/stacker_bot_protocol (`spec/sbp-1.md`,
  ~12 KB, repo declares **no license**). Client owns authoritative state; bot receives
  rules + snapshots and returns placements; capability negotiation for randomizers,
  movement rules, board size, optional snapshot fields.
* **Mechanics (README claims):** SRS **and SRS+** kick sets, **180° rotation**,
  sonic drop (`only`/`allow`), configurable spawn, seven-bag tracking with speculative
  search, column-major bitboards, transposition-aware search, configurable per-move
  budget, search stats via SBP `info`. Descended from Cold Clear 2 with a freestyle
  evaluator using CC2's default weights.
* **Modes:** single-board suggestion engine ("freestyle"); **no versus, garbage queue
  or opponent state evidenced** in the README. The SBP snapshot shape was not
  inspected (`[UNVERIFIED]` whether it can carry pending garbage).
* **Integration path:** subprocess + SBP JSON lines. Because SBP is new and its spec
  is unlicensed, treat the wire format as moving and pin a commit; write a thin SBP
  client in `tetrisrl/agents/opponents/`. If SBP lacks garbage fields, the arena can
  still use it per-piece on the live board (garbage is already inserted before the
  snapshot), which loses only the bot's ability to plan *around* incoming garbage.
* **Verdict: ACCEPT-WITH-ADAPTATION (experimental).** Uniquely interesting because it
  is the only viable engine that explicitly claims **SRS+ and 180°**, which is exactly
  our rotation model, and it is MIT. But it is a 0-star, weeks-old, single-author
  project with an unlicensed protocol spec and no versus evidence. Use only after an
  independent smoke test (legal placements, sane latency, deterministic seeds) and
  never as the sole benchmark.

### 3.4 RIKU0804/tetris-ai

* **URL:** https://github.com/RIKU0804/tetris-ai
* **License:** MIT (GitHub-detected; `LICENSE` present).
* **Language:** Rust core (`core-rs/`, "zero external dependencies" — hand-rolled
  PRNG/JSON/threads) plus a Python reference implementation and viewer.
* **Activity:** 0★, created and last pushed 2026-06-22, 52 KB. Single author, very new.
* **Build/runtime:** `cd core-rs && cargo build --release`; no crates.io dependencies
  (explicitly advertised, which is excellent for offline reproducibility). Python path
  needs `pygame` only for the visualizer.
* **Protocol:** TBP over stdio (JSON lines) — README claims it can plug into TBP
  frontends. Also a native `bench`/versus mode.
* **Mechanics:** guideline engine, SRS + wall kicks, 3-corner T-spin detection,
  7-bag, hold; **full reachable-placement BFS** (tucks and spin slots, not just hard
  drops); beam search with hold and transposition pruning; linear evaluation plus
  optional MLP residual; genetic-algorithm weight tuning (solo or versus); internal
  versus mode with garbage offset/cancel and top-out. 180° support not mentioned
  (`[UNVERIFIED]`, likely no).
* **Self-reported strength:** solo width 32/depth 5 → APP 0.61, ~96% line efficiency,
  0 top-outs; deep-tuned width 24/depth 6 → APP 0.90 (inflated by PC looping);
  versus champion depth 6–8 beats shallow-tuned weights ~11–0. No third-party
  verification.
* **Integration path:** TBP subprocess. Because it also implements versus internally,
  its `core-rs` can double as a **reference implementation** for placement
  enumeration and beam search when we build our own baseline (§7) — but do not copy
  code without retaining the MIT notice, and re-derive rather than transplant.
* **Verdict: ACCEPT-WITH-ADAPTATION.** The best "offline-friendly, permissive,
  protocol-speaking" candidate on paper: MIT, zero Rust dependencies, real beam search,
  TBP, and even a versus mode. The risk is provenance: 0 stars, one commit burst,
  no external validation, and strength claims from the author. Treat as an
  experimental opponent and as a design reference, not as a trusted yardstick until
  it beats our heuristic baseline in a locally recorded match.

### 3.5 Attax — `souta-lab/attax`

* **URL:** https://github.com/souta-lab/attax
* **License:** **AGPL-3.0** (`LICENSE`, 34,523 bytes; `NOTICE.md` carves out the Hoiko
  benchmark). Strong network copyleft: if we modify and expose it over a network, we
  must publish the source; combining it into our codebase would force AGPL on the
  combined work. For a local research repo this is a distribution/redistribution
  hazard, not a runtime one.
* **Language:** TypeScript (Bun + Vite) rules engine/sim/UI, Rust (WASM) for the Hoiko
  replica, and a native **Vulkan GPU** search in `gpu/`.
* **Activity:** 2★, created 2026-09-10, pushed 2026-11-20 (active). Elaborate evidence
  (paper PDF, `bench-results/`, audits, reports), but tiny audience.
* **Build/runtime:** `bun install`, `bun run build`; Rust tests via `bun run test:rust`.
  The *current bot* is the GPU search and **requires a usable Vulkan device, with no
  fallback** (README: "stops at startup without one"). The CPU/TS search and its
  benchmark harness were removed on 2026-11-19.
* **Protocol:** the TBP adapter (`tbp/attax-tbp.ts`) was **removed on 2026-11-19** when
  the engine went GPU-only; there is currently no TBP front-end for the GPU engine.
  Recorded TBP matches remain as artifacts.
* **Mechanics:** guideline versus and a TETR.IO **Season 2 profile** (rules differences
  as profile data), beam search, no neural net, no opening book.
* **Self-reported results:** vs Cold Clear 2 **81–19** (width 96), vs a CC2 fork
  79–16–5, vs Hoiko 195–5, vs clys 88–12, and vs Sold Slear (S2 champion) **38.0%
  (228–372)** in the S2 lab. The README is unusually candid about caveats and about a
  withdrawn 43.1% number. These are author measurements, not independently verified.
* **Integration path:** none practical for us: no protocol front-end, Vulkan-only
  engine, AGPL, TypeScript/Bun toolchain. Re-adding its TBP adapter would mean
  maintaining a fork of a GPU engine.
* **Verdict: REJECT.** It is the strongest *claimed* versus AI and a valuable source of
  benchmark numbers and ideas, but it cannot be launched as a subprocess opponent, is
  GPU-bound (our arena must run CPU-only and offline), and its AGPL license would
  contaminate a permissively licensed research repo. Cite its results; do not depend
  on its code.

### 3.6 intetrigence — `seipass/intetrigence`

* **URL:** https://github.com/seipass/intetrigence
* **License:** **AGPL-3.0-only** (explicit in README; full LICENSE).
* **Language:** Rust workspace (`crates/core`, `crates/bot`, `crates/arena`,
  `crates/tbp`, plus `adapters/`).
* **Activity:** 0★, created 2026-11-14, pushed 2026-11-17, 32 MB (docs + videos).
  Days old, single author, no adoption.
* **Build/runtime:** `cargo build --workspace --release --locked`;
  `cargo test --workspace --release --locked`; FFmpeg for replay video. Runs matches via
  `arena -- match`, `verify`, `render`.
* **Content (from README/PLAN, in Japanese):** S2 board/rotation/7-bag/scoring/garbage
  queue, reachable-move enumeration + beam search + board evaluation, referee with
  replay verification and seed registry, TBP **host**, and adapters for Attax,
  Cold Clear 2 and "clys". It includes very large S2 documents (`docs/s2-spec.md`
  ~114 KB, `s2-referee-protocol.md` ~148 KB, attack/surge/combo analyses) and an
  honest result log: **1 win, 50 losses vs Attax** over 51 verified games, plus
  reports of retracted measurements.
* **Mechanics:** claims TETR.IO Season 2 scoring, garbage queue/cancel, surge/B2B
  charging, SRS+ and 180 (via its own core). The S2 spec is the most detailed
  public artifact found, but it is the author's interpretation, not official.
* **Integration path:** it is a full arena + bot, not a drop-in opponent process for
  our arena. One could run its beam bot through TBP, but that requires adapting its
  `crates/bot` and accepting AGPL. Its own arena could host our bot only if our bot
  spoke its TBP dialect and we accepted the license boundary.
* **Verdict: REJECT as a dependency.** AGPL-3.0-only is incompatible with keeping
  RLTris permissively licensed, and the project is too new/unvetted to be an
  authority. **However:** its S2 documentation is a useful cross-check for
  `docs/RULESET.md` (read it, do not copy AGPL text), and its "1–50 vs Attax" result
  is a useful calibration point: an honest S2 beam bot is currently far from the
  guideline-versus state of the art.

### 3.7 MisaMino — `misakamm/MisaMino`

* **URL:** https://github.com/misakamm/MisaMino
* **License (exact):** `LICENSE` is **21 bytes containing the single line
  `Copyleft by Misakamm`**. This is **not an OSI license**: it grants no explicit
  rights, has no warranty/patent terms, and is incompatible with SPDX/GitHub license
  detection (`NOASSERTION`). Treat as "all rights reserved with a vague copyleft
  claim". **This is a blocking licensing problem**, not a GPL-style inconvenience.
* **Language:** C++ (MSVC projects: `tetris_ai/Tspin08.sln`, `Tspin.sln`,
  `dllai/dllai.vcxproj`), Windows-only headers (`windows.h`, `__declspec(dllexport)`).
* **Size/shape:** `tetris_ai.cpp` 87 KB, `ai.cpp` 6.9 KB, `genmove.cpp` 30 KB,
  plus EGE graphics `.lib` binaries (`graphics08.lib` 859 KB, `bass.lib`) for the
  standalone game.
* **Activity:** 116★, 39 forks, created 2015-07-13, **last commit 2015-07-15**
  ("init proj"). No README, no releases, no issues workflow. Dead for a decade
  (it predates TETR.IO by ~4 years).
* **Source availability:** **source is present** (not binary-only), but it is a
  Windows/Visual Studio project and the standalone game depends on prebuilt
  `.lib` blobs.
* **Mechanics:** own 10×22 field model, `b2b`, `combo`, `comboTable` documented as
  "the comboTable in toj rule" (**TOJ / Tetris Online Japan-style** scoring), T-spin
  with mini/full and wall-kick spin detection, `setSpin180(bool)`, `can180spin`
  parameter (180 enabled but explicitly "no 180 wallkick only"), configurable
  `GarbageStyle`, `GarbageCancel`, `GarbageBuffer`, `GarbageBlocking`, and
  `ATTACK_MODE` 0 = race / 1 = TOP / 2 = head-to-head. So it **does support
  versus/attack**, with its own garbage rules — not SRS+ and not TETR.IO S2.
* **Protocol:** none. The integration surface is a **Windows DLL C ABI**:
  `char* TetrisAI(overfield[], field[], field_w, field_h, b2b, combo, next[],
  hold, curCanHold, active, x, y, spin, canhold, can180spin, upcomeAtt,
  comboTable[], maxDepth, level, player)`, plus `AIDllVersion()`, `AIName(level)`.
  Field rows are bitmasks (bit per column); output is a string of movement
  characters (`l r L R d D z x c v V`). `AI_MAX_DEPTH` is 2 in the DLL wrapper
  (the `level` argument is clamped), while the standalone/training path uses
  `AI_TRAINING_DEEP 16`; the exported call also takes `maxDepth`. In practice the
  DLL opponent is shallow unless patched.
* **Search quality:** real multi-ply search over next pieces with a handcrafted
  evaluation (holes, height change, height variance, attack, "no-attack clear",
  depth-dependent weight sets) — genuinely competitive for its era, and the engine
  behind Zetris.
* **Integration path:** write a Windows host that loads the DLL and calls `TetrisAI`
  per piece, or run it under Wine; there is no stdin protocol. Wrappers exist
  (`ZetrisAI/MisaMinoNET`, C++/.NET P/Invoke, 14★; `TheMining72/MisaMinoJS`, node
  addon, 1★; `Nitrolego/misamino-remix`, Python, **no license**) but they do not solve
  the platform or license problem. A pure-Python port would be a reimplementation,
  not an integration.
* **Verdict: REJECT for direct integration; reference-only.** The license alone blocks
  redistribution or derived work, and the Windows-DLL-only interface plus 2015
  TOJ-era rules make it a poor fit for a Linux/Python SRS+ arena. Its evaluation
  function and search structure remain useful as *ideas* for §7 (do not copy code).
  Any claim that "MisaMino is an open-source opponent" should be corrected: source is
  visible, but it is not open source in any OSI sense.

### 3.8 Zetris — `ZetrisAI/Zetris`

* **URL:** https://github.com/ZetrisAI/Zetris
* **License:** BSD-3-Clause (repository code). **Caveat:** Zetris is "MisaMino-based"
  and ships/loads the MisaMino engine; the BSD grant cannot cover code the maintainer
  does not own. The MisaMino license problem therefore propagates to the engine
  component.
* **Language:** C# / .NET (Windows Forms), projects `Zetris`, `Zetris.PPT`,
  `Zetris.TETRIO`, solution `Zetris.sln`.
* **Activity:** 84★, created 2018-09-10, last commit 2025-05-26, release `38`
  (2025-05-26, `Zetris-38.zip`). Maintained by mat1jaczyyy.
* **Build/runtime:** Windows only; Visual C++ 2022 redistributable; installs the
  **ScpDriverInterface** virtual-gamepad driver (admin rights) and reads the game
  screen; requires the game window (Puyo Puyo Tetris, and a TETR.IO project).
* **What it actually is:** a **screen-capture + virtual-gamepad GUI bot** that plays
  the real commercial/online client, not a library. It exposes no API, no stdin
  protocol, no Python binding. Its "Previews"/"Intelligence"/"Speed" settings map to
  MisaMino search width/depth.
* **Modes:** PPT solo and multiplayer versus; a `Zetris.TETRIO` project for TETR.IO
  (still capture/gamepad based). Online play is explicitly unsupported by the author
  ("to prevent cheating").
* **Important correction to the task premise:** **Zetris is not a Python wrapper.**
  It is C#/.NET. PyPI has no `zetris` package (request returned 404/null), no
  `misamino` package either, and the repo contains no Python. Any plan that assumes
  `pip install zetris` is based on a false premise.
* **Verdict: REJECT.** Wrong platform, wrong interface, no headless/protocol path, and
  the BSD license does not cleanly cover the MisaMino engine it depends on.
  `nevjin/ZetrisV2` (C#, BSD-3, 0★, 2025-05-17, PPT + TETR.IO, `build.zip`) is the
  same class of Windows GUI bot and is likewise rejected.

### 3.9 Blockfish — `blockfish/blockfish`

* **URL:** https://github.com/blockfish/blockfish
* **License:** **LGPL-2.1** (`LICENSE.txt`, 26,530 bytes). Weak copyleft; dynamic
  linking/process separation is the safe pattern. If we statically link or modify its
  engine, the modified library must be LGPL.
* **Language:** Rust workspace: `blockfish-engine`, `blockfish-client` (GUI),
  `blockfish-js`, `blockfish-python`, `fishtest`.
* **Activity:** 46★, created 2020-11-08, last commit 2025-07-13 (PR #11), releases
  `v0.8.8` (2022-05-25, no assets) and `v0.8.4` (2021-01-20, Linux tar.gz + Windows
  zip). Slow but not dead.
* **Build/runtime:** Rust 1.48+; the **client** requires SDL2 and SDL2_ttf dev
  libraries (and DLLs on Windows). The **engine** is pure Rust and can be built
  standalone. `blockfish-python` requires `protobuf` Python package.
* **What it is optimized for:** **Cheese Race** — clearing 100 lines of pre-placed
  garbage with random gaps using the fewest pieces. README: "a maximally defensive
  mode"; it beat the Jstris 100L cheese world record. It is a downstacking/cheese
  specialist, **not** a general versus engine.
* **Mechanics:** SRS, 7-bag, hold, hard/soft drop, finesse; no combo/B2B/attack
  state, **no garbage generation, no attack, no opponent**. Spin classification is not
  part of its objective and was not verified in source (`[UNVERIFIED]`); it is
  irrelevant to cheese-race piece count. The protobuf
  `Snapshot` is only `{hold, queue, rows}` and `Ruleset` contains only `SRS`; a
  `Suggestion` is a rating + a list of inputs. This is verified from
  `blockfish.proto`, not just the README.
* **Protocol:** length-prefixed **protobuf** over stdin/stdout (not line-based, not
  JSON). `blockfish-python/blockfish/ipc.py` shows the subprocess framing and
  `ai.py` wraps `analyze(snapshot)`; so a Python subprocess binding **exists**, but it
  only exposes cheese-race analysis.
* **Integration path:** spawn the Blockfish IPC server binary (the target that
  `blockfish-python` launches by path) and call `Analyze` with a snapshot; or link the
  Rust engine. Neither can represent pending garbage, B2B, combo, or an opponent.
* **Verdict: REJECT for versus. ACCEPT-WITH-ADAPTATION only as a cheese/downstacking
  diagnostic.** It must never be presented as a general-purpose versus benchmark or as
  a TETR.IO opponent. Its legitimate use is Stage-1/Stage-2 pressure testing of
  downstacking ability on artificially garbage-filled boards, clearly labelled
  "cheese-race specialist, not versus". The LGPL is manageable via subprocess, but the
  capability gap is the real blocker.

### 3.10 Not found / rejected without a dossier

| Name searched | Result | Verdict |
|---|---|---|
| **Sixel** | GitHub repo search for `sixel` returns terminal-graphics projects (chafa, libsixel, lsix, timg). **No Tetris AI named Sixel found.** | **NOT FOUND** — do not cite |
| **Nucleon** | GitHub search returns a Rust load balancer, a PHP framework, physics papers. **No Tetris AI named Nucleon found.** | **NOT FOUND** — do not cite |
| **TetraAI** | Only student/toy projects (`NeonNingen/TetraAI`, `ShadowAsura/TetraAI`, Python, no license, 2020–2023). | **REJECT** (toy, unlicensed) |
| **libtetris** | No standalone competitive engine. `libtetris` is a **subcrate inside Cold Clear**; other "libtetris" repos are Clojure/Objective-C/C toy libraries. | **N/A** — use Cold Clear |
| **MisaMino alternative** | `ZetrisAI/MisaMinoNET` (C++/.NET DLL import, NOASSERTION, 2025-05-26, 14★); `TheMining72/MisaMinoJS` (node addon, no license, 1★); `Nitrolego/misamino-remix` (Python, **no license**, 2023); `knewjade/misamino-survey` (MIT, 2019, survey only). All inherit the MisaMino license/platform problem. | **REJECT** |
| **TETR.IO bots** | `lemoncove/tetrio-bot-docs` (CC0, network protocol docs, 61★) is documentation, not an engine; `misterhat/tetrio-bot` (AGPL-3.0, 2022, JS) is a screen/network client; `halp1/triangle` (MIT, TypeScript) is a protocol library. None is a competitive search engine. | **REJECT** as engine; docs may help a future live-client adapter (out of scope) |
| **"tetris ai beam search github"** | Mostly coursework and 0★ demos. The serious ones are already above (Cold Clear, Attax, RIKU0804, intetrigence). | — |
| `Moriz82/tetriov2` (Rust, beam search, TETR.IO screen capture) | 0★, **no license**, 2026-03. | **REJECT** (unlicensed, unvetted) |
| `akameki/akirobo` (Rust, "all-spin versus AI") | 0★, **no license**, 2025-04. | **REJECT** (unlicensed) |
| `SoRA-X7/Quadspace` (C#, MIT, TBP playground) | 6★, 2021. A **TBP host/playground**, not a bot. | Support artifact |
| `ruelalarcon/minorail` (Python, MIT) | 0★, 2026-10. SBP runner/visualizer with websocket API, for frostetra. | Support artifact |
| `61bi-234469/s2-bot-lab` (JS, MIT) | 2★, 2026-11. Browser-local Season 2 simulator and bot GUI; names "Sold Slear" as S2 champion. Not an engine. | Support artifact / S2 cross-check |
| `MinusKelvin/cold-clear` forks (`ColdClearSharp`, `cold_clear_ai_love2d_wrapper`, `ssccinng/ColdCleartetr`) | C#/C wrappers with **no license** or MPL; stale 2020–2024. | **REJECT** (no advantage over upstream) |

---

## 4. Protocol landscape (integration-critical)

| Protocol | Transport | Format | State carried | Garbage-aware? | Used by |
|---|---|---|---|---|---|
| **TBP** (Tetris Bot Protocol) | stdin/stdout | **JSON, one message per line** | hold, queue, combo, B2B, 10×40 board (`null`/piece/`"G"`), randomizer state | board `"G"` cells only; **no incoming-garbage count** | Cold Clear 1 (`cc-tbp`), Cold Clear 2, RIKU0804, Quadspace |
| **SBP** (Stacker Bot Protocol) | stdin/stdout | JSON messages | rules negotiation, snapshots with capability advertisement | not evidenced `[UNVERIFIED]` | frostetra, Minorail |
| **Blockfish IPC** | stdin/stdout | length-prefixed **protobuf** | hold, queue, 40 rows | **no** | Blockfish, blockfish-python |
| **MisaMino DLL** | in-process C ABI | C function + char buffers | board rows, next[], hold, b2b, combo, spin, `upcomeAtt` | attack count in, no queue | MisaMino, MisaMinoNET, Zetris (indirect) |
| **Cold Clear C API** | in-process C ABI | structs + async poll | board, hold, queue, bag_remain, b2b, combo, plan | **`incoming` count**, reset on garbage | Cold Clear 1 |
| **Attax** | — | — | — | — | no front-end since 2026-11-19 |

**TBP lifecycle** (verified from `text/0000-mvp.md`, spec last touched 2021-08):

```
bot → info
frontend → rules
bot → ready
frontend → start {hold, queue, combo, back_to_back, board[40][10]}
frontend → suggest
bot → suggestion {moves:[...]}
frontend → play {move}
frontend → new_piece {piece}
... repeat suggest/play/new_piece ...
frontend → stop
frontend → quit
```

Messages are JSON objects with a `type` field, terminated by a newline; unknown types
and attributes must be ignored. The spec repo declares **no license** (GitHub license
field is empty), so treat it as a specification to implement, not text to copy.

**Integration implication.** TBP has no `garbage` message and no pending-garbage
field. Any versus use of a TBP bot must therefore insert garbage into the board
itself and either (a) send a fresh `start` after each garbage event (Cold Clear 2
rebuilds its state), or (b) accept that the bot cannot plan around future garbage.
Cold Clear 1's C API is the only interface in this survey that takes a *count* of
incoming garbage per move — which is why it is the top pick.

---

## 5. Licensing summary and consequences

| License | Projects | What it means for RLTris |
|---|---|---|
| **MIT / Apache-2.0 / BSD-3** | Cold Clear 2 (MIT OR Apache), frostetra, RIKU0804, Zetris repo, Quadspace, s2-bot-lab, minorail | Safe to depend on, vendor, or reimplement with attribution. Keep `NOTICE`/copyright. |
| **MPL-2.0** | Cold Clear 1 | File-level copyleft. Safe as a separate process or unmodified library; if we patch Cold Clear files, publish those files. Our repo can stay MIT. |
| **LGPL-2.1** | Blockfish | Safe via subprocess/dynamic linking; static linking or modifying the engine triggers source obligations for the library. |
| **AGPL-3.0** | Attax, intetrigence | Strong network copyleft. A separate process used only in local experiments is defensible, but **redistributing a combined work or exposing it over a network forces AGPL on the whole**. Unacceptable as a bundled dependency for this repo. |
| **"Copyleft by Misakamm"** | MisaMino | **Not a license.** No grant of rights; legally unusable for redistribution/derivatives. Do not vendor, port, or ship. |
| **No license** | MisaMinoJS, misamino-remix, ColdClearSharp, akirobo, tetriov2, SBP spec repo, TBP spec repo (spec text) | Default copyright: no rights beyond viewing. Do not copy code or spec text; reimplement from observed behavior if needed. |

**Policy recommendation:** keep `tetrisrl` MIT/Apache-compatible. Only MIT/BSD/
Apache-2.0 engines may be vendored or linked. MPL/LGPL engines may be used strictly as
separate executables invoked over a pipe, with their source unmodified and notices
preserved. AGPL engines may be cited but not bundled. MisaMino must not be shipped at
all.

---

## 6. Why no external engine can be the Season 2 benchmark

1. **No S2 attack model.** None of Cold Clear 1/2, frostetra, RIKU0804, MisaMino or
   Blockfish implements B2B charging, surge accumulation/release, or S2 garbage
   cancellation. intetrigence claims it, but is AGPL, days old, and self-reports
   1–50 vs Attax. Using any of them as the *rules authority* would silently replace S2
   with generic guideline versus — forbidden by the project brief.
2. **They are placement suggesters, not simulators.** With the exception of Attax and
   intetrigence (which ship their own arenas), these engines answer "given this board
   and queue, where should this piece go?" — which is exactly what we want, provided
   our arena owns garbage, scoring, surge and cancellation.
3. **Protocols omit the competitive state we care about.** TBP carries combo/B2B but
   not pending garbage; Blockfish carries neither; only Cold Clear's C API accepts an
   incoming-garbage count. So even a perfect external bot cannot reason about S2
   pressure through TBP alone.
4. **Availability/reproducibility.** Cold Clear 1 is archived (stable, but its `pcf`
   git dependency needs vendoring); Cold Clear 2 has no releases; frostetra and
   RIKU0804 are single-author 0★ projects; Attax needs Vulkan; MisaMino is
   Windows-only and unlicensed; Blockfish is cheese-only. The runtime environment may
   have no network, so none of these can be assumed present.

Conclusion: the mandatory "genuine search-based baseline" must be **in-repo**, and
external engines are optional, clearly labelled benchmark adapters.

---

## 7. Specification: in-repo genuine search-based baseline

This is the opponent we implement ourselves. It must be strong enough to be a
meaningful Stage-3 curriculum opponent and to sanity-check PPO/Double DQN, while
remaining deterministic, dependency-free and fast enough for headless training.

### 7.1 Design

**State.** `10 × 40` bitboard (rows as 10-bit ints), plus column heights, hole count,
pending garbage count, combo, B2B flag/charge. No opponent board is needed for the
placement search itself; garbage pressure enters through evaluation.

**Move generation (placements, not keystrokes).**
For the current piece and, if enabled, each hold option:
1. enumerate all `(rotation ∈ 0..3, x ∈ -2..11)` that fit at spawn rows;
2. BFS/DFS over `(rotation, x, y)` with **SRS+ kick tables including 180°** and the
   project's lock-delay move-reset rules, allowing tucks, spins and floor kicks;
3. dedupe by `(final cell mask, spin classification)`; keep the shortest path for
   replay/execution;
4. drop pieces (hard drop) from every reachable `(rotation, x, y)`.
Typical branching: ~34 hard-drop placements per piece, ~60–90 with tucks and both hold
options. This mirrors RIKU0804's "full reachable-placement BFS" and Cold Clear's
`CCPlanPlacement`.

**Evaluation (handcrafted, linear).**
```
score(board) =
    w_holes        * holes
  + w_covered      * covered_cells
  + w_bumpiness    * Σ|h[i] - h[i+1]|
  + w_bumpiness_sq * Σ(h[i] - h[i+1])²
  + w_agg_height   * Σh[i]
  + w_max_height   * max(h)
  + w_wells        * well_depth_penalty
  + w_row_trans    * row_transitions
  + w_tspin_slot   * tspin_slot_count
  + w_attack       * expected_attack(lines, tspin, combo, b2b)
  + w_b2b_keep     * (b2b_preserved ? 1 : 0)
  + w_garbage      * f(pending_garbage, max_height, holes)   # S2 pressure
```
Start from Cold Clear/MisaMino-style signs (holes ≫ height ≫ bumpiness, attack
positive, "no-attack clear" negative) and tune with CEM/GA over self-play. Keep the
weights in JSON so an ablation can zero any term.

**Search.**
* **Beam search** over piece sequences: beam width `W` (start 32), depth `D`
  (start 3 pieces, `D ∈ {2,3,4}`), with hold.
* Node = board + queue prefix + hold state + B2B/combo; hash for a transposition table.
* Score = immediate evaluation + `γ^(depth)` discounted leaf evaluation; or
  "best leaf" (minimax-free, standard for Tetris). Deduplicate identical boards.
* **Determinism:** stable tie-break `(score, -x, rotation, hold)`; seeded RNG only for
  tie-breaking if desired; no wall-clock-dependent branching.
* **Budget:** `N` ms per piece (e.g. 5–20 ms in Python with numpy, 1–5 ms in Rust).
  With `W=32`, `D=3`, branching 60: ~5,760 evaluations per move — feasible in numpy;
  a pure-Python list implementation should use `W=8–16`, `D=2`.
* **Garbage-aware planning:** before scoring a leaf, simulate inserting
  `pending_garbage` lines (S2 hole RNG, seeded) or apply a height/hole penalty
  proportional to it. Prefer clears that cancel pending garbage. This is the minimal
  S2-awareness an external TBP bot cannot express.

### 7.2 Complexity and expected strength

| Config | Evals/move | Expected behavior |
|---|---|---|
| `W=1, D=1` (greedy) | ~60 | survives, weak attack (heuristic baseline) |
| `W=16, D=2` | ~1,900 | solid downstacker, occasional T-spins, ~0.4–0.6 APP |
| `W=32, D=3` | ~5,800 | competitive versus heuristic/PPO early checkpoints |
| `W=64, D=4` | ~23,000 | near Cold Clear-class survival; CPU-heavy |

These are engineering expectations, not measured results; they must be calibrated by
actually playing the baseline against the random and heuristic agents.

### 7.3 Required tests and acceptance criteria

1. **Legality:** every emitted placement is reachable under SRS+ (including 180) and
   does not collide; property test over random boards.
2. **Determinism:** same seed + same board/queue ⇒ identical move, across processes.
3. **No leakage:** the baseline may see only the configured preview count, never the
   full bag (unless `previews=7+` is configured).
4. **Budget:** p99 decision time under the configured per-piece budget on the target
   CPU; no unbounded memory growth over 10k pieces.
5. **Strength:** beats the random legal-placement baseline ≥ 95% and the handcrafted
   heuristic baseline ≥ 60% over ≥ 200 paired-seed games, with confidence intervals
   reported.
6. **Ruleset parity:** the same engine call path is used by PPO, DQN and the baseline
   (identical observation/action/ruleset), as required by the project brief.

### 7.4 Adapter contract

All opponents (external or in-repo) implement the same interface:

```python
class Opponent:
    def reset(self, seed: int, ruleset: Ruleset) -> None: ...
    def observe(self, obs: Observation) -> None: ...       # board, queue preview, hold,
                                                           # pending garbage, combo, b2b
    def choose_action(self, legal: list[Action]) -> Action: ...
    def receive_result(self, result: StepResult) -> None:  # garbage sent/received,
                                                           # lines cleared, spin, topout
    def terminate(self) -> None: ...
```

External adapters map this to their wire format:

* **Cold Clear 1 (C API):** `reset` → `cc_launch_with_board_async`/`cc_reset_async`;
  `observe` → board + hold + queue + `incoming = len(pending_garbage)`;
  `choose_action` → `cc_request_next_move` + `cc_block_next_move`, convert
  `expected_x/y` cells to our `(rotation, x, hold)` action; ignore its movement path.
* **Cold Clear 2 (TBP):** `reset` → `start`; `observe` → `new_piece`/`start`;
  `choose_action` → `suggest`/`suggestion`, map target placement; `receive_result` →
  `play`; garbage → new `start` (documented approximation).
* **frostetra (SBP) / RIKU0804 (TBP):** same pattern over JSON lines; pin the spec
  commit and validate with a smoke test.
* **Blockfish (protobuf):** cheese-only adapter, used only in a labelled
  downstacking diagnostic; never in the versus tournament.

`choose_action` must accept the legal action mask from the engine and either pick a
legal action or declare `resign`/`topout`; mismatched placements must be rejected and
logged, not silently applied.

---

## 8. Recommended integration plan

1. **Mandatory, ship first:** in-repo beam-search baseline (§7), exposed through the
   `Opponent` interface and used in Stage 3 of the curriculum. This is the only
   opponent guaranteed to work offline, deterministically, under exact SRS+/S2 rules.
2. **Primary external benchmark:** Cold Clear 1 via `c-api` + a `ctypes` adapter.
   Vendor the `pcf` git dependency, pin the commit, build once, record the binary
   hash. Label it "guideline-versus bot, no 180°, S2 scoring owned by tetrisrl".
3. **Secondary external:** Cold Clear 2 via TBP (MIT/Apache, no git deps), used to
   cross-check the v1 numbers. If the TBP front-end proves unreliable, fall back to
   frostetra (SRS+/180) or RIKU0804 (MIT, zero deps) after a smoke test.
4. **Diagnostics only:** Blockfish cheese-race adapter (clearly labelled).
5. **Cite, never bundle:** Attax results and intetrigence S2 documentation.
6. **Do not integrate:** MisaMino, Zetris, ZetrisV2, Attax, intetrigence,
   Moriz82/tetriov2, akirobo, and every unlicensed wrapper.

Every external adapter must be marked `UNVERIFIED` until a recorded match has actually
run; per the project brief, never claim integration before that.

---

## 9. Source URLs (verified 2026-11-20)

Primary candidates:

* https://github.com/MinusKelvin/cold-clear — MPL-2.0, archived; `c-api/coldclear.h`, `tbp/`, `battle/`
* https://github.com/MinusKelvin/cold-clear-2 — MIT OR Apache-2.0; TBP JSON-lines
* https://github.com/ruelalarcon/frostetra — MIT; SBP, SRS+/180 claims
* https://github.com/ruelalarcon/stacker_bot_protocol — SBP spec (no license)
* https://github.com/ruelalarcon/minorail — MIT; SBP runner
* https://github.com/RIKU0804/tetris-ai — MIT; Rust beam search + TBP
* https://github.com/souta-lab/attax — AGPL-3.0; GPU/Vulkan, benchmark claims
* https://github.com/seipass/intetrigence — AGPL-3.0-only; S2 workspace/docs
* https://github.com/misakamm/MisaMino — "Copyleft by Misakamm"; Windows DLL
* https://github.com/ZetrisAI/Zetris — BSD-3; C# screen-capture bot
* https://github.com/nevjin/ZetrisV2 — BSD-3; Zetris-like TETR.IO bot
* https://github.com/ZetrisAI/MisaMinoNET — no license; .NET DLL import
* https://github.com/blockfish/blockfish — LGPL-2.1; cheese race
* https://github.com/tetris-bot-protocol/tbp-spec — TBP spec (no license); `text/0000-mvp.md`
* https://github.com/SoRA-X7/Quadspace — MIT; TBP host/playground
* https://github.com/61bi-234469/s2-bot-lab — MIT; browser S2 simulator/bot GUI
* https://github.com/lemoncove/tetrio-bot-docs — CC0; TETR.IO network protocol docs

Checked and rejected / not found:

* https://github.com/Nitrolego/misamino-remix — Python, no license
* https://github.com/TheMining72/MisaMinoJS — node addon, no license
* https://github.com/Moriz82/tetriov2 — Rust, no license
* https://github.com/akameki/akirobo — Rust, no license
* https://github.com/NeonNingen/TetraAI , https://github.com/ShadowAsura/TetraAI — toy, no license
* GitHub search `sixel` → terminal-graphics projects only; **no Tetris Sixel**
* GitHub search `nucleon` → load balancer/framework/physics; **no Tetris Nucleon**
* GitHub search `libtetris` → toy C/Clojure/Objective-C libraries; Cold Clear's `libtetris` is a subcrate

---

## 10. Explicit non-claims

* No engine in this document was built, run, or benchmarked locally.
* All win rates / APP numbers are the projects' own claims, except where no number
  exists.
* "Supports TETR.IO" for Zetris/Attax/intetrigence means the project claims to play or
  model it; none has been verified against Season 2 mechanics here.
* Sixel and Nucleon could not be found; absence of evidence is not proof they do not
  exist off-GitHub, but nothing verifiable was located.
* GitHub API rate limiting and the `web_search` 401 may have hidden candidates; the
  search space covered is GitHub-centric.
