# OPPONENTS — Additional open-source Tetris engines for mixed-opponent training

**Status:** repository research and source-level verification only. Nothing in this
document was cloned, built or executed during this pass; every build command below is
read from a manifest/README, not proven by a local build. This is the follow-up to
`docs/BENCHMARKS.md` (survey) and `docs/BENCHMARKS_INTEGRATION.md` (the executed Cold
Clear 2 integration), and it targets curriculum **Stage 5 (mixed-opponent training)**.
**Verification date:** 2026-11-20 (Asia/Jakarta).
**Author:** Opponent Researcher (subagent).
**Hard exclusion:** ZZZTOJ is closed-source and was not fetched, installed, inspected or
reverse-engineered. No candidate below depends on it.

---

## 0. TL;DR

* **Seven new, plausibly usable engines were found** beyond Cold Clear 2 and the in-repo
  baselines: `SoRA-X7/hikari_rei` (MIT, Rust, TBP, versus-aware), `nightcrab/nana` (MIT,
  C++, MCTS, TBP2), `ruelalarcon/frostetra` (MIT, Rust, SBP, SRS+/180),
  `RIKU0804/tetris-ai` (MIT, Rust, TBP), `citrus610/lemon-tea-2` (MIT, C++20, TBP),
  `cosmiolotl/otto` (MIT, Rust, NNUE search, no protocol), and
  `blchiu616/modern-versus-tetris-ai` (MIT, Python, TETR.IO S2 engine + DAG search).
* **Pending-garbage planning is still rare:** among the newly found engines only `nana`
  consumes it, through the unofficial **TBP2** `meter` field. Cold Clear (v1) can also
  receive an incoming-garbage *count* through its **C API**; Cold Clear 2 cannot (TBP has
  no such field). `frostetra` parses SBP `incoming_garbage` but does not use it in search.
* **Only one candidate explicitly implements SRS+ and 180°:** `frostetra` (README claim,
  source not exercised). No engine found *verifiably* implements TETR.IO **Season 2**
  attack (B2B charging, surge) — `attax` has an S2 *profile* but is AGPL-3.0 and
  GPU-only, `intetrigence` claims S2 but is AGPL-3.0-only and unvetted, and
  `modern-versus-tetris-ai` claims an S2 engine but is a single-commit project with no
  validation. The arena must keep owning the ruleset (unchanged conclusion from
  `docs/BENCHMARKS.md`).
* **Recommended next three:** `nana`, `hikari_rei`, `frostetra` (details and exact
  commands in §7). Cheapest genuine TBP opponent: `RIKU0804/tetris-ai`.
* **Not worth pursuing:** Attax, intetrigence, the whole MisaMino lineage, Zetris,
  Blockfish, and the host-only projects (§9).

---

## 1. Method and evidence limits

What was actually fetched this session (all read-only HTTP; no `git clone`, no install,
no build):

* GitHub REST metadata for every shortlisted repo (`stars`, `forks`, `language`,
  `license.spdx_id`, `created_at`, `pushed_at`, `archived`, `default_branch`, `size`);
* raw `README`, `LICENSE`, `Cargo.toml`, `Makefile`, protocol and search source files
  from `raw.githubusercontent.com` (the specific files are cited per dossier);
* repository trees from the GitHub contents API and, after the API limit was exhausted,
  from the HTML tree pages;
* pinned HEAD commits from `https://github.com/<owner>/<repo>/commits.atom`;
* the TBP MVP spec (`tetris-bot-protocol/tbp-spec`), the TBP2 spec
  (`shakkar23/Universal-Shaktris-Stadium/specs/TBP2.md`), and the Stacker Bot Protocol
  spec (`ruelalarcon/stacker_bot_protocol/spec/sbp-1.md`).

Limits that must be respected when reading this document:

* **`web_search` is unavailable in this environment** — it fails with
  `HTTP 401 UNAUTHORIZED` ("Invalid 'Authorization' header or token"). Discovery was
  therefore GitHub-only (API search + org/user pages + link-following from the TBP
  README). A project that lives only on a blog, Discord, or a non-GitHub forge would
  have been missed, except where another project linked to it.
* **The unauthenticated core API rate limit (60/h) was exhausted** at ~23:16 local time
  (reset 00:00). Repos discovered after that point were verified through raw files,
  HTML tree pages, the search endpoint (separate quota) and commit feeds. The only
  fields that are *partial* for those repos are `created_at` (not all) and exact star
  counts at the second; last-push dates and licenses are still first-hand. Partial
  entries are marked `[PARTIAL]`.
* **No engine was built or run.** Build dependencies are read from manifests/READMEs.
  Self-reported strength numbers are labelled as self-reported and are not independent
  evidence.
* **Star counts are a weak adoption proxy**, not a quality signal. Several of the best
  fits here have 0–5 stars because they are new or niche (the whole versus-bot scene is
  small and historically closed-source).
* The "strongest" vs-Tetris engines of the last few years (ZZZTOJ, clys, Sold Slear, and
  the TBP README's **Tetras**, **Wataame**, **Hikari**) were largely closed-source by
  design. The TBP README itself says the interfacing code was "generally not made public
  due to concerns about such programs being used to cheat". Hikari now has a public MIT
  Rust reimplementation by its original author (§4.1); for Wataame/Tetras no public
  repository was found (`traias` publishes `TetrasC`, a GPL-2.0 Windows/DxLib app with
  no TBP front-end; `ameyasu` has no public repos).

---

## 2. What changed since `docs/BENCHMARKS.md`

| Change | Evidence |
|---|---|
| Cold Clear 2 is now a **real, executed** opponent (20 matches, 0.42% fallback) | `docs/BENCHMARKS_INTEGRATION.md` |
| **Attax** still GPU/Vulkan-only and its TBP adapter is still absent — `tbp/` now contains only `SMOKE.md` and `intetrigence-match.md` | `README.md` §TBP; tree of `souta-lab/attax` |
| **MisaMino** license re-read: `LICENSE` is exactly **21 bytes** containing `Copyleft by Misakamm` — not an OSI license | raw `LICENSE` |
| **TBP2** (versus extension with `opponents` + garbage `meter`) exists and is implemented by `nana` | `Universal-Shaktris-Stadium/specs/TBP2.md`; `nana/cpp/tbp.cpp` |
| **Hikari** has a public MIT Rust port by the original author | `SoRA-X7/hikari_rei` |
| New engines not in the previous survey: `hikari_rei`, `nana`, `otto`, `lemon-tea-2`, `modern-versus-tetris-ai` | §4 |
| `Zetris` last push moved to 2025-08-22 (previous doc said last commit 2025-05-26) | GitHub metadata |
| `intetrigence` still AGPL-3.0-only, still days-to-weeks old, still 0★ | GitHub metadata |

---

## 3. Protocol landscape — the part that decides integration cost

All four protocols speak JSON lines over stdin/stdout. They differ in exactly the places
that matter for a versus arena.

### 3.1 TBP (MVP, `tetris-bot-protocol/tbp-spec`)

Messages: `info → rules → ready → start → suggest → suggestion → play → new_piece →
stop/quit`. The repo declares **no license** (raw `LICENSE` returns 404). Properties:

* `start` carries `board` (40×10, **bottom row first**), `queue`, `hold`, `combo`,
  `back_to_back` (boolean in TBP1).
* **No garbage, no opponent, no pending-attack field.** An engine sees garbage only
  after it has been inserted into the board. This is the single largest capability gap
  of CC2, RIKU0804 and lemon-tea-2.
* The spec does not nail down whether `queue[0]` is the current piece or the reserve.
  Engines disagree in practice — see §3.5.
* `suggestion.moves[0].location` is `{type, orientation, x, y}` on the **SRS true-rotation
  centre**, `y = 0` at the bottom. Our existing adapter already converts this by matching
  the four absolute cells, which is the right approach for every TBP engine.

### 3.2 TBP2 (unofficial versus extension, documented in `Universal-Shaktris-Stadium`)

`specs/TBP2.md` (13 KB) extends TBP1 for versus play. The repo is **GPL-3.0**; treat the
document as reference, re-implement the wire format rather than copying text/code.

* Adds `meter` (**pending incoming garbage**, integer) and an `opponents` array
  (`board`, `combo`, `back_to_back`, `meter`, `queue`, `hold`).
* Changes `back_to_back` to an integer (engines are expected to accept both).
* Stateful: `play` updates the engine's state; `suggest`/`suggestion` each turn.
* **`nana` requires `opponents[0]` in every `start`** (`CHECK_ERR(player_2 =
  message["opponents"][0])`, no `#ifdef` guard), so it *cannot* be driven by our current
  TBP1 adapter. This is the single most important adapter fact in this document.

### 3.3 Stacker Bot Protocol (SBP, `ruelalarcon/stacker_bot_protocol`)

A **stateless-per-snapshot**, capability-negotiated protocol. The repo declares **no
license** (raw `LICENSE` 404); the spec is marked SBP/1.

* Lifecycle: `register → rules → ready → start → suggest → suggestion → advance →
  new_piece… → stop/quit`, plus `board` for mid-session board replacement.
* `start` carries the **authoritative snapshot**: `board` (bottom-to-top), `active` (the
  current piece, separate), `queue` (upcoming, **excluding `active`**), `hold`, `combo`,
  `back_to_back`, optional `piece_stream`, and optional **`incoming_garbage`** as a list
  of pending chunks, oldest first.
* `rules` carries `kickset` (e.g. `"srs+"`), `rot180`, `sonic_drop`, `spin_detection`
  with all-spin classes (`"all"`, `"all+"`, `"all-mini"`, …), `back_to_back_sources`,
  `spawn_position`, `board_size`.
* The spec explicitly allows bots to *project* pending garbage in hypothetical search
  states while keeping it out of the physical board. This is the best-designed protocol
  for our use case; whether a bot uses it is another matter (`frostetra` does not, §4.3).

### 3.4 USS "Stateless Bot Protocol" (name collision)

`Universal-Shaktris-Stadium/specs/StatelessBotProtocol.md` also abbreviates to "SBP" but
is a **different** protocol: TBP1-derived, stateless, `play → move`, with `opponents` and
`meter`, 40 rows. Do not confuse it with the Stacker Bot Protocol. It lives in the same
GPL-3.0 repo as TBP2 and has no known bot implementing it that we can use.

### 3.5 Wire-format hazards found by reading source (adapter checklist)

| Hazard | Evidence | Consequence for `TBPAgent` |
|---|---|---|
| `queue[0]` meaning differs | CC2: with `hold=null`, `queue[0]` is the reserve (empirically verified in `BENCHMARKS_INTEGRATION.md`). RIKU0804 and `hikari_rei` treat `queue[0]` as the **current** piece (source: `handle_start` + `queue.remove(0)`); `nana` sets `current_piece = queue.front()` | The existing CC2 workaround `[first_preview, current, …]` must be **disabled per engine**, or every non-CC2 engine places the wrong piece |
| Board height differs | CC2: 40. `hikari_rei`: 24 (`HEIGHT = 24`), rejects occupied rows ≥ 24. `nana`/ShakTrisLib: 32 (`height = 32`), reads only the bottom 32 rows | Send bottom-first 40 rows; `hikari_rei` needs rows 24–39 empty (else error → fallback), `nana` silently ignores rows 32–39 |
| Combo base differs | TETR.IO `-1` = no combo; TBP wants a count. Existing adapter sends `max(0, combo+1)` | Reuse for CC2; RIKU/`hikari_rei`/`nana` probably use the same 0-based count, but this is **[UNVERIFIED]** per engine and must be tested on a known position |
| `back_to_back` type | TBP1 boolean; TBP2 integer; `hikari_rei` **requires boolean** (`back_to_back.as_bool()`) | Send boolean for TBP1 engines, integer/boolean tolerant for `nana` |
| 180° rotation | TBP has no 180; SBP has `rot180`; `hikari_rei`/`nana` are SRS-only | Engines without 180 are handicapped against our SRS+ arena; document, never "fix" silently |
| Pending garbage | TBP1 none; TBP2 `meter`; SBP `incoming_garbage` | Only `nana` consumes it; `frostetra` parses it but ignores it |
| `randomizer` / bag state | TBP optional; `hikari_rei` accepts `bag` or `randomizer.bag_state` | Omitting it avoids leaking hidden bag info; keep omitting |

---

## 4. Candidate dossiers

Legend: **[VERIFIED]** = first-hand repo/source/license evidence this session ·
**[UNVERIFIED]** = claim from README/prior doc or not exercised · ★ = stars at verification
time (weak signal).

### 4.1 `SoRA-X7/hikari_rei` — Hikari (Rust reimplementation)

* **URL:** https://github.com/SoRA-X7/hikari_rei
* **Pinned HEAD:** `21b63c652f232d64016b2af72876d7a4b0e238fd` (2026-11-20)
* **License (exact):** **MIT** — `LICENSE`, "Copyright (c) 2026 Hikari Rei contributors".
  The README states it is a Rust reimplementation of SoRA_X7's Hikari, ported from
  GitLab commit `90aef085a53d6048cbd19de7f4c9c53a6f3c8960`; the port author is the
  original author, which is what makes MIT plausible here. The GitLab original's license
  was **not verified** (its page is JS-rendered and no license text was retrievable), so
  this rests on the port's own `LICENSE`. [VERIFIED]
* **Language:** Rust (edition 2024, which requires Rust ≥ 1.85).
  Dependencies: `clap`, `rayon`, `serde`, `serde_json`, pinned by `Cargo.lock`. No GPU.
* **Build/runtime:** `cargo build --release` (first build needs crates.io; subsequent
  builds work with `--offline`). Runnable binary; no system libraries.
* **Protocol/interface:** **TBP1 over stdio**: `target/release/hikari_rei tbp --threads 1`.
  Source `src/protocol.rs` handles `rules`, `start`, `suggest`, `play`, `new_piece`,
  `stop`, `quit`, plus a `reset` extension (re-sync board while keeping queue/bag).
  `suggestion` includes `moves`, `move_info`, `board`, `queue`, `position_id`.
* **Mechanics:** Hikari's own 10×24 `SimpleBoard` (`HEIGHT = 24`), **SRS** kicks, T-spin
  classification, Mirai-style placement generation including spins/tucks, integer
  evaluation, layer-shared parallel search with backpropagation. Own versus rules: 24
  rows, 3-frame spawn, 38-frame line clear, garbage arrival after 60 frames, attack
  cancel, up to 8 rows rising on a non-clearing landing; a `tools/versus.py` harness
  exists and CI plays PRs against `main` (40 games, seeded). **No 180°.** [VERIFIED source/README]
* **Garbage planning:** Only indirectly — the host sends `reset`/`start` with the risen
  board. No pending-garbage field in its TBP dialect.
* **Activity/adoption:** 0★, **created 2026-11-20** — hours old at verification — pushed the
  same day; ported from a mature engine, with tests, evaluation tooling and CI workflows.
  It has no external users yet, so the *port* is unproven even though the algorithm is not.
* **Integration path:** point a per-engine TBP configuration at the binary. Required
  deltas: current-piece queue convention (`queue[0] = current`), `b2b` boolean, board
  bottom-first 40 rows with rows 24–39 empty (or truncate to 24 rows; truncation is
  safer than a hard error), combo convention to be verified. Reuse the existing
  four-cell geometry matcher.
* **Verdict: ACCEPT.** The best combination of license, protocol, build simplicity and
  genuine versus engineering found in this pass. It is a *different* search family from
  Cold Clear 2 and it has a real test/CI culture. Risks: 24-row board truncation, no 180,
  Hikari rules (not TETR.IO S2), 0★, no published strength vs Cold Clear (only a harness).
  Confidence: **[VERIFIED]** for repo/license/protocol/build; **[UNVERIFIED]** for
  in-arena strength and the exact combo convention.

### 4.2 `nightcrab/nana` — parallel MCTS versus engine

* **URL:** https://github.com/nightcrab/nana
* **Pinned HEAD:** `3cb49c6cc680f07282382de2862f1aa656d9afa1` (2026-11-10)
* **License (exact):** **MIT**, "Copyright (c) 2026 Paul Anderson" (`LICENSE`). The game
  library is a git submodule, `nightcrab/ShakTrisLib`, also **MIT** but its `LICENSE.txt`
  still has the placeholder `Copyright (c) [year] [fullname]` — legal hygiene flag, not a
  blocker. [VERIFIED]
* **Language:** C++23 (Clang/GCC/MSVC), CMake ≥ 3.22, mimalloc fetched at configure time,
  `ShakTrisLib` submodule. No GPU. Default `-march=native`.
* **Build/runtime:**
  `git clone --recurse-submodules … && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release &&
  cmake --build build -j`; the TBP backend is `nana_tbp` (launcher in
  `build/cpp/nana_tbp` under a Unix single-config generator). A `nana.json` beside the
  executable configures it; the upstream example is
  `{"rules":"tetrio","threads":3,"pin_layout":"compact"}`.
* **Protocol/interface:** **TBP2** (`cpp/tbp.cpp`, compiled with `TBP`+`TBP2`). It
  **requires `opponents[0]`** in `start` and reads `opponents` again in `play`; it also
  reads `meter`, `garbage_delay`, `back_to_back` (bool or int), `combo`, `queue`,
  `hold`. `suggestion` is standard TBP moves + `move_info`. It has `name`/`version` in
  `info`.
* **Mechanics:** ShakTrisLib implements standard SRS wall kicks (5 kick offsets; **no
  180**), 7-bag, hold, T-spin mini/full, B2B and combo; `modes/TetrioS1.hpp` implements
  the **TETR.IO Season 1** damage table (B2B chain power, combo power) and `VersusGame`
  has per-player meters, attack and garbage. **Not Season 2**: no surge/change charging
  as defined in our ruleset. [VERIFIED source]
* **Search:** parallel MCTS + Transposition Driven Scheduling, an HMM-style opponent
  model conditioned on the opponent's board/queue/hold/meter, and estimation over random
  outcomes. This is the only candidate that models the *opponent* explicitly.
* **Garbage planning:** **Yes** — `meter` is pending incoming garbage, and the search
  evaluates states with it (`EmulationGame::set_garbage_delay`). This is unique among the
  usable engines. [VERIFIED source]
* **Activity/adoption:** 5★, 0 forks, created 2024-02-10, pushed 2026-11-10; docs,
  tuner (PSO/CMA-ES/SPSA), README-advertised portable release binaries, 14 MB repo.
* **Self-reported strength:** 3,779–2,621 (59.0%, 95% CI 57.8–60.2) over 6,400 games vs
  **Cold Clear** under TETR.IO **Season 1** rules on Universal Shaktris Stadium, 50 ms
  time control. Not independently verified; it is the strongest documented claim among
  the new engines.
* **Integration path:** extend the TBP adapter to TBP2: send
  `opponents:[{board, combo, back_to_back, queue, hold, meter}]` and
  `meter = state.garbage.total()`, with `queue[0] = current`. Start-per-piece works
  (nana rebuilds its emulation game from each `start`), but the opponent model learns
  more if `play` is also sent — only do that if the adapter always plays the engine's
  move, which conflicts with fallback; start-per-piece is the honest default.
* **Verdict: ACCEPT-WITH-ADAPTATION.** Highest strategic value for Stage 5 (opponent-
  aware MCTS + the only pending-garbage input), MIT, active, real versus rules. Costs:
  TBP2 adapter extension, submodule + mimalloc at build time, brand-new/5★ project,
  Season 1 (not S2) damage, no 180, 32-row board truncation above row 32.
  Confidence: **[VERIFIED]** for repo/license/protocol/mechanics; **[UNVERIFIED]** for
  strength and for whether our arena's S2 garbage cadence suits its emulation model.

### 4.3 `ruelalarcon/frostetra`

* **URL:** https://github.com/ruelalarcon/frostetra
* **Pinned HEAD:** `b92dc7606414776eb2bf2dfc67cb3119b41338ea` (2026-11-03)
* **License (exact):** **MIT** (`LICENSE.txt`, "Copyright (c) 2021 Mark Carlson /
  Copyright (c) 2026 Ruel Nathaniel Alarcon") — a Cold Clear 2 derivative with
  attribution intact. [VERIFIED]
* **Language:** Rust 2021, crate `frostetra`, no system libraries; `cargo build --release`.
* **Protocol/interface:** **SBP** over stdio (`src/protocol/sbp.rs`). Implements
  `rules`, `start`, `suggest`, `suggestion`, `advance`, `board`, `stop`, `quit`,
  `info`. The snapshot type includes `incoming_garbage: Option<Vec<u32>>`.
* **Mechanics:** README claims **SRS and SRS+** kick sets, **180° rotation**, sonic drop
  (`only`/`allow`), configurable spawn, seven-bag tracking with speculative search,
  transposition-aware search, column-major bitboards, configurable per-move budget.
  Source contains the rule enums (`SonicDrop`, `SpinDetection`, `BackToBackSource`) and
  parses `rot180`/`kickset`/`spin_detection`. Not exercised here. [VERIFIED README/source]
* **Garbage planning:** **No.** `incoming_garbage` is parsed into the snapshot struct but
  has no other reference in `src/` (checked `src/protocol/sbp.rs`, `src/runtime/*`,
  `src/bot/core.rs`, `src/search/context.rs`, `src/main.rs`). Garbage is only visible
  after it lands on the board. [VERIFIED by source inspection at HEAD; absence of
  references, not proof of intent]
* **Activity/adoption:** 0★, created 2026-06-11, pushed 2026-11-04; docs and benches,
  single author, no versus evidence or users.
* **Integration path:** a dedicated **SBP client** (not TBP): `rules` with
  `kickset:"srs+"`, `rot180:true`, `spin_detection:"t-spins"` (or an all-spin class),
  `board_size:{width:10,height:40}`, `randomizer:"seven_bag"`; `start` with bottom-to-top
  board, **separate `active` piece**, `queue` excluding active, `hold`, `combo`,
  `back_to_back`, `incoming_garbage:[chunk sizes]`; `suggest`; convert
  `suggestion.moves[0].location`; `advance` with the accepted move; `board` after a
  garbage rise; `stop`+`start` after any fallback.
* **Verdict: ACCEPT-WITH-ADAPTATION (experimental).** The only engine that claims
  SRS+ **and** 180°, i.e. the closest match to our rotation model, MIT, active. But it
  ignores pending garbage, shares Cold Clear 2's evaluator lineage (less algorithmic
  diversity), and has zero external validation. Confidence: **[VERIFIED]** repo/license/
  protocol/SRS+ claim; **[UNVERIFIED]** actual kick behaviour, strength, and 180 coverage.

### 4.4 `RIKU0804/tetris-ai`

* **URL:** https://github.com/RIKU0804/tetris-ai
* **Pinned HEAD:** `d3f92d289a24e09ec72679d8ce653bfd8a98679e` (2026-06-22)
* **License:** **MIT** (`LICENSE`, "Copyright (c) 2026 riku"). [VERIFIED]
* **Language:** Rust core (`core-rs/`, **zero external crates** — hand-rolled JSON, PRNG
  and threads) + Python reference/visualiser.
* **Build/runtime:** `cd core-rs && cargo build --release`; binary
  `core-rs/target/release/tetris-core`. Python path needs `pygame` only for the viewer.
* **Protocol/interface:** **TBP1** over stdio: `tetris-core tbp --weights
  weights/champion-vs.json`. `src/tbp.rs` implements `rules`, `start`, `suggest`,
  `play`, `new_piece`, `stop`, `quit`; `queue[0]` is the current piece
  (`queue.remove(0)` after a placement); no garbage/opponent fields.
* **Mechanics:** guideline engine, SRS + wall kicks, 3-corner T-spin, 7-bag, hold, full
  reachable-placement BFS (tucks and spin slots), beam search with hold and transposition
  pruning, linear evaluation plus optional MLP residual, GA tuning (solo/versus), and an
  **internal** versus mode with garbage offset/cancel/top-out. No 180. [VERIFIED README]
* **Garbage planning:** Internal versus only; the TBP path cannot see pending garbage.
* **Activity/adoption:** 0★, single author, one commit burst 2026-06-22, no external
  validation. Self-reported: solo APP 0.61 (width 32/depth 5), APP 0.90 deep-tuned
  (inflated by PC looping), versus champion depth 6–8 beats shallow weights ~11–0.
* **Integration path:** existing `TBPAgent` with `binary=` and a per-engine queue
  convention (`queue[0]=current`, i.e. **do not** use the CC2 null-hold workaround).
  Reuse the geometry matcher; watch for tucks our hard-drop action space cannot express
  (same fallback class as CC2).
* **Verdict: ACCEPT-WITH-ADAPTATION.** Cheapest genuine search opponent to integrate:
  MIT, zero dependencies, TBP1, small codebase. Risks: unvetted single-author project,
  no garbage planning, no 180, and its full reachable-placement search will hit our
  action-space fallback more often than hard-drop-only engines.
  Confidence: **[VERIFIED]** repo/license/protocol; **[UNVERIFIED]** strength.

### 4.5 `citrus610/lemon-tea-2`

* **URL:** https://github.com/citrus610/lemon-tea-2
* **Pinned HEAD:** `edc3915b67863ed4c2fb10ad3fa218ac0a46889d` (2022-05-23)
* **License:** **MIT**, "Copyright (c) 2022 citrus610". [VERIFIED]
* **Language:** C++20, vendored `nlohmann/json` and small utility headers; **no external
  packages**. `Makefile` is Windows-oriented (`bin\tbp\tbp.exe`, `-luser32 -lgdi32 …`,
  backslashes) — a one-line Linux `g++` build is plausible but **not tested**.
* **Protocol/interface:** **TBP1** (`tbp/main.cpp`, `tbp/tbp.h`): `info`, `ready`,
  `rules`, `start`, `suggest`, `suggestion`, `play`, `new_piece`, `stop`, `quit`;
  `Cell::G` for garbage cells. No `opponents`/`meter`.
* **Mechanics:** own versus bot with board/movegen/search/transposition table/eval/plan
  and a tuner; `b2b`, `ren`, T-spin detection; **no garbage or opponent modelling** found
  in `bot/state.*`, `bot/board.*`, `bot/thread.*`. Its `ppt/` target links a Puyo Puyo
  Tetris sync library (a client, not a versus model). [VERIFIED by source inspection]
* **Activity/adoption:** 3★, created 2022-03-18, last push 2022-05-23, dormant.
* **Verdict: ACCEPT-WITH-ADAPTATION (experimental).** A self-contained TBP search bot
  with MIT and no deps; integration cost is a Linux build line + queue-convention check.
  It is dormant and unproven, so use only as a *secondary* TBP opponent.
  Confidence: **[VERIFIED]** repo/license/TBP source; **[UNVERIFIED]** Linux build.

### 4.6 `cosmiolotl/otto`

* **URL:** https://github.com/cosmiolotl/otto
* **Pinned HEAD:** `74852b4d9dbc279728882735dfe1a2140738d904` (2026-11-16)
* **License:** **MIT**, "Copyright (c) 2026 osmii". [VERIFIED]
* **Language:** Rust 2024 workspace (`crates/{bot,sim,selfplay,cli}`, `web/engine`).
  Workspace dependencies: `serde`, `serde_json`, `smallvec`, `rayon` (+ `criterion` for
  benches). No GPU.
* **Protocol/interface:** **None.** CLI subcommands (`replay`, `diff`, `gen`, `perft`,
  `bot-vs-bot`, `weights`, `tune`, `tournament`, `nnue-eval`); `replay <request.json>`
  consumes a JSON request and emits a trace. There is no stdin bot loop, so integration
  means writing a thin Rust bridge (read our state on stdin → call the `bot` crate →
  print a placement) or using its JSON request format per move.
* **Mechanics:** `crates/sim` has `board`, `falling`, `kicks`, `queue`, `garbage`,
  `attack`, `reach` (reachable placements), `replay`; `crates/bot` has `search`, `eval`,
  `nnue` and hand weights, `weights.json`, `selfplay`/tuning. So it is a **versus-aware
  search + NNUE/hand-eval engine with its own simulator**, not a TBP bot.
  Whether the search conditions on pending garbage is **[UNVERIFIED]**.
* **Activity/adoption:** 1★, pushed 2026-11-16; active, negligible adoption.
* **Verdict: ACCEPT-WITH-ADAPTATION (experimental, higher effort).** Interesting because
  it is a learned-evaluation engine (NNUE) with a versus simulator, which is a genuinely
  different evaluation family from CC/attax-style handcrafted search. But it needs a
  protocol bridge and its behaviour is unverified. Lower priority than §4.1–4.4.
  Confidence: **[VERIFIED]** repo/license/structure; **[UNVERIFIED]** API stability,
  garbage awareness, strength.

### 4.7 `blchiu616/modern-versus-tetris-ai`

* **URL:** https://github.com/blchiu616/modern-versus-tetris-ai
* **Pinned HEAD:** `b0f91b6807aa580d4899d123748c4c2885591e30` (2026-08-05)
* **License:** **MIT**, "Copyright (c) 2026 blchiu616". [VERIFIED]
* **Language:** Python (core/rules/bitboard, AI DAG search, GA tuner, FastAPI web,
  pygame clients, React frontend).
* **Protocol/interface:** none; `ai/process_thinker.py` and `ai/async_thinker.py` expose
  the AI for the web server and pygame clients. Could be driven in-process (same
  language) or via its FastAPI `/ws` play channel.
* **Mechanics:** README claims **TETR.IO S2 versus** rules (board, kicks, spins, garbage
  queue, attack math) + heuristic **DAG search** "inspired by Cold Clear" + GA reward
  tuning. Single-day repo, one commit, no external users; no test suite is listed in the
  root layout. [VERIFIED README]
* **Garbage planning:** the engine models garbage; whether the AI search conditions on
  pending garbage is **[UNVERIFIED]**.
* **Verdict: ACCEPT-WITH-ADAPTATION (experimental reference).** The only permissively
  licensed Python implementation that claims TETR.IO **S2** versus rules *and* ships a
  search AI — useful as a cross-check for our ruleset and as a cheap in-process opponent.
  Do not trust it as a benchmark until it plays our arena without rule mismatches.
  Confidence: **[VERIFIED]** repo/license/claims; **[UNVERIFIED]** correctness, speed,
  strength.

### 4.8 Re-verified existing candidates (details in `docs/BENCHMARKS.md`)

Every `owner/repo` identifier in the two tables below is a repository at
`https://github.com/owner/repo`.

| Candidate | What was re-checked | Verdict |
|---|---|---|
| `MinusKelvin/cold-clear` (v1) | workspace still contains `c-api` and `tbp` crates; 278★; **archived**, pushed 2022-01-29; MPL-2.0 | **ACCEPT-WITH-ADAPTATION** — still the best-documented *garbage-count-aware* engine (`cc_request_next_move(bot, incoming)`), but MPL-2.0 and dead. Keep as a second CC-family opponent if the C-API shim is built. |
| `MinusKelvin/cold-clear-2` | 71★, pushed 2022-06-29, `license = "MIT OR Apache-2.0"`, TBP1 | **INTEGRATED** (20 real matches). No garbage planning, no 180. |
| `souta-lab/attax` | 2★, AGPL-3.0, pushed 2026-11-20; `tbp/` now only `SMOKE.md` + `intetrigence-match.md`; README §TBP confirms adapter removed; GPU/Vulkan-only | **REJECT** — AGPL + GPU-only + no protocol. Cite its numbers, don't depend on it. |
| `seipass/intetrigence` | 0★, AGPL-3.0, pushed 2026-11-17 | **REJECT as dependency** — AGPL-3.0-only, unvetted (the prior survey reported 1–50 vs Attax). Useful S2 doc cross-check only. |
| `misakamm/MisaMino` | `LICENSE` exactly 21 bytes `Copyleft by Misakamm`; 116★; last commit 2015-07-15; Windows DLL C ABI | **REJECT** — non-OSI license blocks any redistribution/derivative; dead + Windows-only. |
| `ZetrisAI/Zetris` | 84★, BSD-3-Clause, pushed 2025-08-22; MisaMino-based, screen-capture + virtual gamepad | **REJECT** — not a library; BSD cannot cover the MisaMino engine. |
| `blockfish/blockfish` | 46★, LGPL-2.1, pushed 2025-07-13; cheese-race specialist | **REJECT for versus** — cannot play versus and cannot plan around attack; keep as an optional downstacking diagnostic, never as a general opponent. |

### 4.9 Rejected and host-only projects (one line each)

| Project | Why not |
|---|---|
| `ZetrisAI/MisaMinoNET` (14★) | `LICENSE` is the same 21-byte MisaMino text; wrapper cannot relicense the engine. Windows DLL. |
| `jezevec10/MisaMinoTBP` | Emscripten/WASM TBP wrapper of MisaMino; repo `NOASSERTION`, engine license still blocks use. |
| `TheMining72/MisaMinoJS` | Node native addon, **no license**, 2021; engine license problem. |
| `analog-hors/MisaMinoCLI` | C# MPL-2.0 CLI wrapper for MisaMino; wrapper license does not cure the engine. |
| `knewjade/misamino-survey` | Claims MIT over MisaMino survey code; that relicense is not the author's to make. Ignore. |
| `SoRA-X7/Quadspace` | 6★, MIT, **archived** TBP frontend/playground; a host, no AI advertised. |
| `imcatag/project-tetr` | MIT Unity TBP host; README: "The game has absolutely no authority… will accept move 0 every time"; hosts external bots, ships no AI. |
| `shakkar23/Universal-Shaktris-Stadium` | GPL-3.0 C TBP2 frontend/arena; valuable **spec** source, unusable as a dependency. |
| `ruelalarcon/minorail` | MIT Python SBP runner/arena; no built-in AI (`bots/` is process management). Useful for testing SBP bots, not an opponent. |
| `tetris-bot-protocol/tbp-rs` | MIT OR Apache-2.0 Rust TBP **types** crate; useful reference for the adapter, not an engine. |
| `tetris-bot-protocol/dellacherie` | No license, 1-ply Dellacherie heuristic, depends on `tbp` git branch; weaker than our in-repo heuristic. |
| `tetris-bot-protocol/battletris` | No license, TBP match runner (host), not an engine. |
| `analog-hors/bashtet` | MIT bash TBP bot implementing a 4-feature Lee heuristic; fun protocol conformance test, not competitive. |
| `nyctivoe/tetris-engine-in-rust` | **No license**; TETR.IO engine replica with SRS+, all-spin default, surge, garbage cancel, BFS + Python extension. Best *mechanics reference* found, but legally unusable. |
| `akameki/akirobo` | **No license**; all-spin Rust versus AI for **Botris Battle** (online API token), cannot run offline. |
| `traias/TetrasC` | GPL-2.0, Windows/DxLib app, no TBP front-end; not the TBP "Tetras". |
| `GregoryCannon/StackRabbit` | 467★ but **no license**, NES Tetris only, no versus/garbage; reject. |
| `barrycohen/tetris-zero` | MIT, solo RL/PC-loop agent (no preview, no garbage); not a versus opponent. |
| `sami-29/tetris-lab` | **No license**, browser puzzle solver for a known piece sequence, not versus. |
| `PeterPalotas/Tetris-Bot` | MIT but only a 4-file simulator + beam demo, no protocol, no versus, no garbage. |
| `amo-tx/TetrisAI` | **No license**, Windows/Android GUI, 9 heuristics, no protocol. |
| `rubot813/fearscape_ai` | Empty README, C++/SFML 2021, no protocol/license evidence of use. |
| `egwkim/all-spinner` | 1★, no license, described only as "Tetris all spin solver"; no engine/protocol evidence. |
| `ZetrisAI/...`/`SoRA-X7/ColdClearSharp` etc. | Windows/C# wrappers of Cold Clear/MisaMino; no headless protocol path worth maintaining. |

---

## 5. Compatibility matrix (expanded)

Legend: ✅ documented/implemented · ⚠️ partial/claim · ❌ no · `?` unverified.

| Engine | License | Lang | Protocol | SRS | SRS+ | 180 | Garbage in protocol | Plans around pending garbage | Versus-native | Last push |
|---|---|---|---|---|---|---|---|---|---|---|
| Cold Clear 1 | MPL-2.0 | Rust | C API + TBP | ✅ | ? | ❌ | ✅ C API `incoming` count | ✅ (count) | ✅ host-driven | 2022-01-29 (archived) |
| Cold Clear 2 | MIT/Apache | Rust | TBP1 | ✅ | ? | ❌ | ❌ | ❌ | host | 2022-06-29 |
| hikari_rei | MIT | Rust | TBP1 | ✅ | ❌ | ❌ | ❌ (board rise) | ❌ | ✅ own rules | 2026-11-20 |
| nana | MIT | C++ | TBP2 | ✅ | ❌ | ❌ | ✅ `meter` + `opponents` | ✅ | ✅ TETR.IO S1 | 2026-11-10 |
| frostetra | MIT | Rust | SBP | ✅ | ✅ claim | ✅ claim | ✅ `incoming_garbage` | ❌ (parsed, unused) | ❌ suggester | 2026-11-04 |
| RIKU0804 | MIT | Rust | TBP1 | ✅ | ? | ❌ | ❌ | ❌ | ✅ internal only | 2026-06-22 |
| lemon-tea-2 | MIT | C++20 | TBP1 | ✅ | ? | ? | ❌ | ❌ | ✅ internal | 2022-05-23 |
| otto | MIT | Rust | none (CLI/lib) | ✅ likely | ? | ? | sim only | ? | ✅ own sim | 2026-11-16 |
| modern-versus | MIT | Python | none (in-process/API) | ✅ | ? | ? | S2 model | ? | ✅ S2 engine | 2026-08-05 |
| attax | AGPL-3.0 | TS/Rust | ❌ (removed) | ✅ | ✅ profiles | ? | n/a (GPU sim only) | n/a | ✅ GPU | 2026-11-20 |
| intetrigence | AGPL-3.0 | Rust | TBP host/own | ✅ | ✅ claim | ✅ claim | ✅ claim | ? | ✅ | 2026-11-17 |
| MisaMino | non-OSI | C++ | Win DLL | ⚠️ own | ❌ | ⚠️ | ✅ own | ? | ✅ TOJ-style | 2015-07-15 |
| Blockfish | LGPL-2.1 | Rust | protobuf | ✅ | ❌ | ❌ | ❌ | ❌ | cheese only | 2025-07-13 |

### 5.1 Flags at a glance

| Flag | Projects |
|---|---|
| **Blocking license problem** (non-OSI / no license / unlicensed spec) | MisaMino and all its wrappers, `nyctivoe/tetris-engine-in-rust`, `akameki/akirobo`, `sami-29/tetris-lab`, `GregoryCannon/StackRabbit`, `tetris-bot-protocol/{dellacherie,battletris}`, tbp-spec and the Stacker Bot Protocol spec |
| **AGPL / strong copyleft** | `souta-lab/attax` (AGPL-3.0), `seipass/intetrigence` (AGPL-3.0-only), `shakkar23/Universal-Shaktris-Stadium` (GPL-3.0), `traias/TetrasC` (GPL-2.0) |
| **Windows-only / GUI / binary blob** | MisaMino (MSVC + `.lib` blobs), Zetris, ZetrisV2, MisaMinoNET, TetrasC (DxLib), `lemon-tea-2`'s Makefile (Linux build plausible but untested) |
| **Dead / archived / dormant** | Cold Clear 1 (archived 2022), MisaMino (2015), Quadspace (archived 2021), `lemon-tea-2` (2022), `PeterPalotas/Tetris-Bot` (last push 2025-12) |
| **Cannot plan around pending garbage** | Cold Clear 2, `hikari_rei`, `RIKU0804`, `lemon-tea-2`, `frostetra` (field parsed, unused), Blockfish; `attax` and `intetrigence` claim it but are unusable here |
| **Placement suggester only (not a simulator)** | every engine in this document; the arena stays authoritative |
| **Host/frontend, ships no AI** | Quadspace, project-tetr, Universal Shaktris Stadium, Minorail, AlphaStack, battletris |

---

## 6. Opponent diversity for training

The goal of Stage 5 is not "more opponents"; it is a **distribution of opponent policies
that is wide enough that the learner cannot fit one specific opponent's rhythm**. Three
axes matter:

1. **Search family** — DAG/beam search with handcrafted eval (CC2, RIKU, lemon-tea,
   hikari, frostetra); MCTS/PUCT with an opponent model (nana); learned/NNUE eval with
   search (otto); heuristic DAG search in Python (modern-versus).
2. **Pressure profile** — pure attacker (CC2, attax-style), defensive/downstacking
   (Blockfish, our heuristic under garbage), opportunistic spin hunter (RIKU, hikari),
   and garbage-aware counter-puncher (nana).
3. **Mechanical footing** — engines with 180° (frostetra), engines without it (CC2,
   hikari, nana), engines whose board is 24/32 rows instead of 40 (hikari, nana), engines
   that see pending garbage (nana) and engines that only see landed garbage (everything
   else). These are *handicaps*, and they are useful: they create opponents that force
   different responses, but they must be recorded so a win against a handicapped engine
   is never reported as a win against "the engine".

### 6.1 In-repo variants (already implemented)

`tetrisrl/agents/variants.py` (in the working tree) defines `VariantOpponent`, which
resamples a variant at the
start of every episode and is deterministic given the episode seed. From the source:

* heuristic weights jittered ×0.7–1.3 (holes ×0.8–1.5);
* `per_attack ∈ [0.5, 4.0]`, `opponent_pressure ∈ [0, 0.8]`, `height_threshold ∈ [10, 16]`;
* evaluation noise ∈ {0, 0, 0.05, 0.15};
* beam `depth ∈ [1, 3]`, `beam_width ∈ {4, 6, 8, 12, 16, 24}`,
  `attack_weight ∈ [0.5, 3.0]`, `opponent_aware` with p=0.75;
* pool choice between `heuristic` and `search`.

This is the right backbone for bulk training because it is free (no subprocess, no
latency), reproducible, and already covers the "handcrafted vs search" axis. Suggested
extensions (cheap, no external code):

* a **defensive** profile (high holes/height penalties, low `per_attack`) and a
  **rush** profile (high `per_attack`, low height penalty) sampled as explicit poles;
* a **garbage-blind** flag (ignore pending garbage in observation) and a
  **garbage-aware** flag, so the learner sees both;
* a **no-180** handicap flag and a **no-hold** handicap flag, matching what external
  engines can do;
* random think-time/beam-width per episode rather than per variant, so the learner
  cannot key on a fixed opponent speed;
* keep `noise=0.15` rare (it makes the opponent genuinely bad, not just different).

### 6.2 External engines as a *distribution*, not a ladder

External engines cost a subprocess and ~5–60 ms per placement. At ~100 placements per
side per game that is roughly 1–12 s of engine time per game per side (arithmetic
estimate, not a measurement), which is fine for evaluation and for a minority of
training episodes, but not for every rollout. A defensible Stage 5 mixture:

| Share | Opponent | Why |
|---|---|---|
| ~50 % | in-repo `VariantOpponent` (heuristic + beam) | volume, reproducibility, broad weight coverage |
| ~20 % | Cold Clear 2 (TBP, 10–20 ms) | strong, already validated, stable |
| ~15 % | `hikari_rei` (TBP, 20 ms) | different search family, versus-native, active |
| ~10 % | `nana` (TBP2, 20 ms) | opponent-aware MCTS; teaches unpredictability |
| ~5 % | `frostetra` (SBP, 20 ms) | SRS+/180 mechanics; held-out candidate |

Treat the percentages as a **starting hypothesis to ablate**, not a result. The important
properties are: (a) at least one opponent the learner never trains against (hold out
`frostetra`, or one variant pole, for the generalization experiment), (b) at least one
opponent that is *weaker* than the learner late in training (so the policy does not
degenerate into pure defense), and (c) at least one opponent that is stronger (so attack
timing is stressed).

### 6.3 Guardrails and metrics

* **Fallback rate per engine** (`TBPAgent.stats.fallbacks / suggestions`) must stay
  < 1 %. A rising rate means the engine is increasingly proposing tucks/spins our
  hard-drop action space cannot encode — the opponent is silently getting weaker.
* **Timeout/restart rate** per engine; a restart resets the engine's search tree.
* **Latency p50/p95** per engine, recorded in the match report; external engines must not
  change the *game's* timing, only the wall-clock cost.
* **Per-opponent win rate with confidence intervals** (Wilson), never a single aggregate
  number. Mixed training is only useful if per-opponent performance is reported.
* **Diversity diagnostics**: distribution of learner board heights at piece 50, APM,
  T-spin/B2B frequency, and action entropy. A policy that wins by one strategy against
  every opponent is overfit even if its aggregate win rate is high.
* **Pinned engines**: record commit SHA, binary hash and `info` string for every engine in
  every tournament, exactly as `third_party/COLD_CLEAR_2_NOTICE.md` does for CC2.
* **Replays record actions, not engine calls**; external engines may be nondeterministic
  (threads/`thread_rng`), so replay determinism must come from the recorded action stream.

---

## 7. Ranked shortlist — top 3 to integrate next

Ordering weighs *diversity value first, integration risk second*. If the team prefers
minimum risk, swap #1 and #2.

### #1 `nightcrab/nana` — opponent-aware MCTS with pending-garbage input

**Why first:** among the newly found engines it is the only one that plans around pending
garbage and the only one with an explicit opponent model, i.e. exactly the opponent class
Stage 5 lacks. (Cold Clear 1's C API can also take a garbage count, but it is archived.)
MIT, active, real versus rules, published (self-reported) 59 % vs Cold Clear over 6,400
games.

**Build (not executed here):**

```bash
cd /home/alfi/Active/tetrlio
git clone https://github.com/nightcrab/nana third_party/nana
git -C third_party/nana checkout 3cb49c6cc680f07282382de2862f1aa656d9afa1
git -C third_party/nana submodule update --init --recursive
cmake -S third_party/nana -B third_party/nana/build -DCMAKE_BUILD_TYPE=Release
cmake --build third_party/nana/build -j
# binary: third_party/nana/build/cpp/nana_tbp   (verify with: find third_party/nana/build -name nana_tbp)
```

Requirements: C++23 compiler (GCC/Clang), CMake ≥ 3.22, network at configure time
(mimalloc fetch + submodule), `-march=native` by default. Put `nana.json` beside the
binary: `{"rules": "tetrio", "threads": 2}`.

**Adapter protocol:** TBP2. Extend the existing adapter's `start`:

```json
{"type":"start",
 "board":[[...40 rows, bottom first...]],
 "queue":["T","I","O","S","Z","J","L"],
 "hold":null,"combo":1,"back_to_back":0,"meter":3,
 "opponents":[{"board":[[...]],"combo":0,"back_to_back":0,
               "queue":["I","O","T"],"hold":"L","meter":0}]}
```

`meter` = `state.garbage.total()`; `queue[0]` must be the current piece (remove the CC2
null-hold workaround); `combo` = `max(0, state.combo + 1)`; `back_to_back` may be bool or
int. Send `start` per piece (no `play`) — simple and fallback-safe. Gate on a smoke test
first: if `opponents` is missing the process exits (verified in source).

### #2 `SoRA-X7/hikari_rei` — TBP-native versus engine, easiest real integration

**Why second:** it is the lowest-risk *new* engine: MIT, Rust, TBP1 already implemented,
tests/CI, active today, and a search/eval family distinct from Cold Clear. Zero adapter
protocol work beyond per-engine conventions.

**Build (not executed here):**

```bash
cd /home/alfi/Active/tetrlio
git clone https://github.com/SoRA-X7/hikari_rei third_party/hikari_rei
git -C third_party/hikari_rei checkout 21b63c652f232d64016b2af72876d7a4b0e238fd
(cd third_party/hikari_rei && cargo build --release)   # first build fetches crates; later --offline works
# run: third_party/hikari_rei/target/release/hikari_rei tbp --threads 1
```

Because the port is hours old, treat it as a fast-moving dependency: pin the commit and
re-run the smoke tests after any update. If that churn is unacceptable, RIKU0804 (§4.4)
is the lower-churn TBP alternative.

**Adapter protocol:** TBP1, with three deltas from the CC2 configuration:
`queue[0] = current` (no reserve slot), `back_to_back` must be a **JSON boolean**, and the
board must be bottom-first with **rows 24–39 empty** (or send only the bottom 24 rows; a
non-empty row ≥ 24 is rejected with `Hikari supports occupied rows 0 through 23`). Reuse
the existing four-cell geometry matching and fallback path. Verify the combo convention
(`combo` is mapped to `ren` directly in `src/protocol.rs`) on a position with a known
combo before trusting it.

### #3 `ruelalarcon/frostetra` — SRS+/180 suggester over SBP

**Why third:** the only engine claiming SRS+ and 180°, which is our exact rotation model,
MIT, recently updated, and its protocol (SBP) is the cleanest snapshot design — the natural second
protocol for the arena and a stepping stone to other SBP bots.

**Build (not executed here):**

```bash
cd /home/alfi/Active/tetrlio
git clone https://github.com/ruelalarcon/frostetra third_party/frostetra
git -C third_party/frostetra checkout b92dc7606414776eb2bf2dfc67cb3119b41338ea
(cd third_party/frostetra && cargo build --release)
# run: third_party/frostetra/target/release/frostetra   (SBP JSON lines on stdio)
```

**Adapter protocol:** new SBP client (not TBP). Minimal flow:

```text
bot→ register | client→ rules {kickset:"srs+", rot180:true, spin_detection:"t-spins",
                               board_size:{width:10,height:40}, randomizer:"seven_bag"}
bot→ ready | client→ start {board:<bottom-to-top 40x10>, active:"T",
                            queue:["I","O","L"], hold:null, combo:0,
                            back_to_back:0, incoming_garbage:[2,1]}
client→ suggest | bot→ suggestion {moves:[{location:{piece,orientation,x,y},spin}]}
client→ advance {move:<accepted placement>}
client→ board {board:<new board>}       # after a garbage rise
client→ stop … quit                     # on fallback/desync
```

`incoming_garbage` is accepted but currently ignored by frostetra's search, so it buys
nothing yet — send it anyway for forward compatibility.

**Runner-up (cheapest of all):** `RIKU0804/tetris-ai` — `cd core-rs && cargo build
--release`, run `tetris-core tbp --weights weights/champion-vs.json`, reuse the TBP
adapter with `queue[0]=current`. Its zero-dependency build makes it the least fragile
engine to vendor offline.

---

## 8. Suggested integration sequence and gate criteria

1. **Parameterise the existing `TBPAgent`** with per-engine options instead of hard-coded
   CC2 behaviour: `queue_mode ∈ {"reserve_first", "current_first"}`, `b2b_type ∈
   {bool, int}`, `board_rows ∈ {24, 32, 40}`, `combo_offset ∈ {0, +1}`, `tbp_version ∈
   {1, 2}`. This one refactor unlocks CC1, CC2, RIKU, lemon-tea, hikari and nana.
2. **Add a TBP2 start builder** (`opponents`, `meter`) gated by `tbp_version=2`.
3. **Add an SBP client** for frostetra (and future SBP bots).
4. **Smoke tests per engine** (all must pass before any benchmark number is reported):
   * handshake completes and `info`/`name` is recorded;
   * 20 scripted pieces on an empty board: the engine's move is legal and is for the
     **current** piece (catches queue-mode mistakes);
   * 3 games vs the in-repo heuristic (paired seeds): no crash, fallback < 1 %,
     p95 latency < 200 ms at 20 ms budget;
   * edge states: hold empty/full, combo −1/0/5, B2B on/off, 1–8 pending garbage,
     stack at 23/24/32/40 rows (height truncation paths).
5. **Only then** run the tournament: ≥ 100 paired-seed games per opponent, report Wilson
   CIs, per-opponent stats and fallback rates. Never aggregate a handicapped engine's
   win rate without saying which handicap applied.

---

## 9. Not worth it (explicit)

* **Attax** — AGPL-3.0, Vulkan-only, TBP adapter removed. Cite the numbers; do not build.
* **intetrigence** — AGPL-3.0-only, days old, 1–50 vs Attax. Read the S2 docs, do not
  depend on the code.
* **MisaMino and every wrapper** (MisaMinoNET, MisaMinoJS, MisaMinoTBP, MisaMinoCLI,
  misamino-survey) — the 21-byte non-OSI license is a blocking problem; Windows DLL or
  WASM; 2015 TOJ-era rules.
* **Zetris / ZetrisV2** — Windows screen-capture + virtual gamepad GUI; no library/API;
  BSD cannot cover the MisaMino engine it loads.
* **Blockfish** — LGPL-2.1 and cheese-race-only; cannot play versus or plan around attack.
* **Quadspace / project-tetr / USS / Minorail / AlphaStack** — hosts and runners with no
  built-in AI. (Minorail is still useful to *test* SBP bots; USS is useful only as the
  TBP2 spec source.)
* **bashtet / dellacherie / battletris / tbp-rs** — not opponents: trivial bots, unlicensed
  samples, or a TBP type library.
* **nyctivoe/tetris-engine-in-rust** — excellent TETR.IO mechanics reference (SRS+,
  all-spin, surge), but **no license**, so it cannot be used or vendored.
* **akirobo / sami-29 / StackRabbit / tetris-zero / PeterPalotas / amo-tx / TetrasC** —
  wrong game (Botris online, NES, solo), no license, Windows-only, or a toy simulator.

---

## 10. Sources actually fetched

GitHub REST (metadata, contents, forks, rate limit):
`https://api.github.com/rate_limit`,
`https://api.github.com/search/repositories?q=…` (queries: `tetris bot`, `tetris ai`,
`tetris beam search`, `tetris expectimax`, `tetris bot protocol`, `stacker bot protocol`,
`tetris srs engine`, `tetris mcts`, `misamino`, `cold-clear`, `tetrio bot`,
`tetris versus ai`, `tetris garbage engine`, `srs+ tetris`, `all-spin tetris`,
`topic:tetris-ai`, `tbp tetris`, `hikari_rei`, `botris`),
`https://api.github.com/repos/{nightcrab/nana, nightcrab/ShakTrisLib,
ruelalarcon/frostetra, RIKU0804/tetris-ai, PeterPalotas/Tetris-Bot,
imcatag/project-tetr, jezevec10/MisaMinoTBP, analog-hors/MisaMinoCLI,
nyctivoe/tetris-engine-in-rust, akameki/akirobo, blchiu616/modern-versus-tetris-ai,
souta-lab/attax, seipass/intetrigence, shakkar23/Universal-Shaktris-Stadium}`,
`https://api.github.com/repos/MinusKelvin/cold-clear-2/forks`.

Raw files (representative; brace lists denote multiple literal URLs):
`https://raw.githubusercontent.com/nightcrab/nana/HEAD/{LICENSE,README.md,.gitmodules,cpp/tbp.cpp,cpp/CMakeLists.txt,nana.example.json}`,
`…/nightcrab/ShakTrisLib/HEAD/{LICENSE.txt,src/engine/Board.hpp,src/engine/modes/TetrioS1.hpp,src/engine/RotationSystems.hpp,src/VersusGame.hpp}`,
`…/SoRA-X7/hikari_rei/HEAD/{LICENSE,README.md,Cargo.toml,src/board.rs,src/protocol.rs}`,
`…/ruelalarcon/frostetra/HEAD/{LICENSE.txt,README.md,Cargo.toml,src/protocol/sbp.rs,src/runtime/*,src/bot/core.rs}`,
`…/ruelalarcon/stacker_bot_protocol/HEAD/spec/sbp-1.md`,
`…/shakkar23/Universal-Shaktris-Stadium/HEAD/specs/{TBP2.md,StatelessBotProtocol.md}`,
`…/tetris-bot-protocol/tbp-spec/HEAD/{README.md,text/0000-mvp.md}`,
`…/RIKU0804/tetris-ai/HEAD/{LICENSE,README.md,core-rs/src/tbp.rs}`,
`…/citrus610/lemon-tea-2/HEAD/{LICENSE,README.md,Makefile,tbp/main.cpp,tbp/tbp.h,bot/*.h,bot/*.cpp}`,
`…/cosmiolotl/otto/HEAD/{LICENSE,README.md,Cargo.toml,crates/cli/src/main.rs,crates/bot/src/spec.rs}`,
`…/blchiu616/modern-versus-tetris-ai/HEAD/{LICENSE,README.md}`,
`…/souta-lab/attax/HEAD/README.md`,
`…/misakamm/MisaMino/HEAD/LICENSE`,
`…/tetris-bot-protocol/{tbp-rs,dellacherie,battletris}/HEAD/Cargo.toml`.

Commit pins: `…/commits.atom` for nana, hikari_rei, frostetra, RIKU0804, lemon-tea-2,
otto, modern-versus-tetris-ai, attax, intetrigence, nyctivoe, MisaMino.

---

## 11. Open items (what is still unverified)

1. **No build, no run.** Every build command is documentation-derived. The first team to
   integrate an engine must execute the smoke tests in §8 before citing any number.
2. **`hikari_rei` combo convention** — `combo` maps to `ren` directly; whether our
   `combo+1` is correct is unverified.
3. **Repeated `start` without `play`** — `nana` rebuilds an emulation game per `start`
   and `hikari_rei` parses a new position per `start`; both look compatible with our
   start-per-piece adapter, but neither has been exercised.
4. **`frostetra` SRS+ kick tables and 180 coverage** — README claim only.
5. **`otto` and `modern-versus` API stability and garbage awareness** — trees/READMEs
   only.
6. **Any TETR.IO Season 2 attack engine** — none found that is permissively licensed and
   verified. The arena remains the ruleset authority.
7. **Metadata completeness** — last-push dates, licenses and stars are first-hand for
   every dossier; a handful of one-line rejects have only a name, description and license
   and are marked `[PARTIAL]` where a field is missing.
