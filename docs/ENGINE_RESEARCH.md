# Engine Research — Reuse, Opponents, and Protocol Options

**Status:** research complete. Source-level audits were run in parallel against
GitHub trees + raw files (Group A: `nyctivoe/tetris-engine-in-rust`,
Cold Clear 2, Cold Clear; Group B: RIKU `tetris-ai`, ZetrisV2, Blockfish;
Group C: NullpoMino, TBP spec, Battletris). No repository was cloned, built,
vendored, or copied; no engine changes were made as a result of this research.

Confidence labels: **[VERIFIED]** = read in the repository's source/licence file;
**[INFERRED]** = from README/metadata; **[UNKNOWN]** = could not confirm (often
because the unauthenticated GitHub API rate-limited metadata calls after the
tree listings, or because a table lives inside a closed binary).

Detailed per-repo evidence lives in `docs/research/engine_group_{a,b,c}.md`.

---

## 0. Executive answer

1. **There is no legally reusable, verified TETR.IO Season 2 rules engine among
   these projects.** The only repository with a broad Season 2 surface
   (`nyctivoe/tetris-engine-in-rust`: B2B charge, three-segment surge, all-spin
   mini, clutch, garbage timers) has **no licence file and no licence field**,
   so it cannot be linked, embedded, vendored, or copied into this MIT project.
   Its README also claims SRS+ while its I-piece kicks are the guideline table
   **[VERIFIED]**.
2. **Keep our engine authoritative.** `docs/RULESET.md` + `environment/` remain
   the rules source of truth. External engines are **placement suggesters** or
   clearly-labelled **compatibility baselines**; our arena owns attack, charging,
   Surge, garbage and spin classification.
3. **The most valuable reusable asset is the protocol, not the engine.** TBP
   (JSON lines) is sufficient to run external bots headlessly, and we already
   drive Cold Clear 2 with it. Its limitation is structural: TBP cannot express
   incoming garbage, B2B charge, Surge or All-Mini+ — so it is approximate
   compatibility, never full parity.
4. **Opponent variety for training comes from three places:** the verified Cold
   Clear 2 adapter, an approximate RIKU TBP adapter (MIT, guideline SRS), and the
   in-repo seeded variants (`agents/variants.py`: jittered heuristic weights,
   noise, beam width/depth).
5. **Do not integrate** `nyctivoe` (no licence), ZetrisV2 (closed MisaMino DLLs,
   Windows GUI), NullpoMino (mixed/non-OSI files, GUI-first), or Battletris
   (no licence, non-deterministic wall-clock host). Blockfish is a cheese-race
   specialist only, never a versus benchmark.

---

## 1. Comparison matrix

Roles: **ENV** = could serve as a headless RL environment; **OPP** = placement
or move suggester for our arena; **REF** = reference/spec/reference-only;
**HOST** = match runner/referee.

| # | Repository | Language | Licence | Headless | Role | SRS+ I kicks | 180 | Season 2 | Integration | Complexity |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | [nyctivoe/tetris-engine-in-rust](https://github.com/nyctivoe/tetris-engine-in-rust) | Rust + PyO3 | **none** (all rights reserved) | yes (Python module) | ENV/REF technically, **unusable** | ✘ guideline **[VERIFIED]** | ✔ present; table parity **[UNKNOWN]** | partial (charge+surge, all-spin, clutch; not parity) | none legal | — |
| 2 | [MinusKelvin/cold-clear-2](https://github.com/MinusKelvin/cold-clear-2) | Rust | **MIT OR Apache-2.0** | yes | OPP (TBP) | ✘ guideline | ✘ | none | subprocess TBP (already done) | LOW–MEDIUM |
| 3 | [RIKU0804/tetris-ai](https://github.com/RIKU0804/tetris-ai) | Rust + Python ref | **MIT** | yes (`tetris-core tbp/vs/bench`) | OPP (TBP), REF | ✘ guideline **[VERIFIED]** | ✘ | none (flat B2B, additive combo) | subprocess TBP | MEDIUM |
| 4 | [nevjin/ZetrisV2](https://github.com/nevjin/ZetrisV2) | C# WPF | **BSD-3** wrapper; bundled MisaMino DLLs **unlicensed** | ✘ Windows GUI | REF only | flag passed to closed DLL **[UNKNOWN]** | flag passed, table **[UNKNOWN]** | none | none | HIGH / disqualified |
| 5 | [blockfish/blockfish](https://github.com/blockfish/blockfish) | Rust | **LGPL-2.1** | yes (protobuf stdio) | downstack specialist only | ✘ guideline | ✘ | none | subprocess protobuf | MEDIUM |
| 6 | [MinusKelvin/cold-clear](https://github.com/MinusKelvin/cold-clear) | Rust / C ABI | **MPL-2.0** | yes | OPP + reference versus sim | ✘ guideline | ✘ | pre-S2 (boolean B2B) | subprocess or C ABI | MEDIUM |
| 7 | [nullpomino/nullpomino](https://github.com/nullpomino/nullpomino) | Java 8 | mixed: BSD-3 core + non-OSI file + unlicensed files + LGPL libs | ✘ GUI-first (no match runner) | REF only | ✘ guideline I order **[VERIFIED]** | own table, not TETR.IO's | none | subprocess only | HIGH |
| 8 | [tetris-bot-protocol/tbp-spec](https://github.com/tetris-bot-protocol/tbp-spec) | Markdown spec | **none** | n/a | REF (protocol) | n/a | n/a | n/a | implement host/client | LOW–MEDIUM |
| 9 | [tetris-bot-protocol/battletris](https://github.com/tetris-bot-protocol/battletris) | Rust | **none** (separate `tbp` crate is MIT/Apache) | yes (referee) | HOST | ✘ guideline | ✘ | none (PPT attack table) | referee only, no licence | MEDIUM/HIGH |

Mechanics detail for the two "usable" opponents:

| Mechanic | Cold Clear 2 | RIKU tetris-ai | Our engine (authoritative) |
|---|---|---|---|
| Board | placement oracle, no board rules | 10×40 (20 visible) | 10×40 (20 visible) |
| 7-bag / hold | absent (host owns) | ✔ / ✔ | ✔ / ✔ |
| Kick table | guideline | guideline, 5 tests | **SRS+** with TETR.IO order |
| 180 | ✘ | ✘ | ✔ (directional tables) |
| T-spin | ✘ | T-only 3-corner full/mini | full/mini + spin-in reconstruction |
| Attack | absent (host owns) | 0/1/2/4, TS 2/4/6, mini 1/2, PC +10 | **Season 2 table** (mini 0/1/2, AC 5) |
| B2B | absent | flat +1 (chaining) | **charging + 3-segment Surge** |
| Garbage | absent (host owns) | counter, 1-turn delay, cap 8 | queue, FIFO partial cancel, tank cap 8, holes RNG |

---

## 2. Licensing

| Repository | Licence | Can we link/embed? | Copy code into MIT files? | Safe integration |
|---|---|---|---|---|
| nyctivoe/tetris-engine-in-rust | none | **No** — no grant at all | **No** | none |
| cold-clear-2 | MIT OR Apache-2.0 | yes | yes (with notices) | subprocess preferred |
| RIKU tetris-ai | MIT | yes | yes (notice) | subprocess TBP |
| ZetrisV2 | BSD-3 wrapper | wrapper yes; bundled DLLs no | wrapper only | none (use as reference) |
| blockfish | LGPL-2.1 | yes, with §6 obligations if distributed | **No** | subprocess |
| cold-clear | MPL-2.0 | yes (§3.3); modified MPL files stay MPL | **No** | subprocess or dynamic link |
| nullpomino | mixed (BSD-3 + non-OSI RC4 + unlicensed files + LGPL libs) | **No** as a whole | **No** | none |
| tbp-spec | none | n/a (spec text) | no | implement the protocol independently |
| battletris | none | **No** | **No** | none (use `tbp` crate instead) |

The missing licence on the single most TETR.IO-like project is decisive: a
subprocess wrapper does not cure a missing distribution grant, and we will not
"study and reimplement" its code into ours.

---

## 3. What the TBP protocol can and cannot express

From `tbp-spec` (4 Markdown files, no code):

* frontend → bot: `rules`, `start` (`hold`, `queue`, `combo`,
  `back_to_back`, `board[40][10]` with `null | piece-letter | "G"`), `suggest`,
  `play {move}`, `new_piece {piece}`, `stop`, `quit`;
* bot → frontend: `info`, `ready`, `suggestion {moves:[{location:{type,
  orientation,x,y}, spin}], move_info}`, `error`;
* orientation `north/east/south/west`; `x` center 0 = leftmost, `y` center 0 =
  bottommost, true-rotation centres; board row order is **not stated** in the
  spec (Battletris sends bottom-first **[INFERRED]**).

**Absent:** incoming-garbage count/queue, B2B charge/surge, combo multiplier,
attack table, hold-availability, Season 2 semantics. Consequences:

* external TBP bots cannot plan around pending garbage;
* our arena must recompute all attack/charge/garbage from the placements the bot
  returns (which is exactly what the dashboard/arena does today);
* C API engines (original Cold Clear) are the only audited interface that
  accepts an incoming-garbage count per move — relevant if we want a
  garbage-aware external opponent.

---

## 4. Recommendations

### 4.1 Rules engine
Keep the in-repo engine (`environment/`) as the single source of truth. No
audited project is both legally reusable and Season 2-complete. A future Rust
rules core would be our own code, or an MPL-compliant `libtetris` fork with
notices — not a copy of any project above.

### 4.2 Opponents for training (ranked)
1. **Cold Clear 2** — already integrated, MIT/Apache, best measured strength
   (20 real matches: 10–0 vs heuristic, 10–0 vs random; 0.42% fallback actions
   that our hard-drop action space cannot encode).
2. **RIKU `tetris-ai`** — MIT, zero-dependency Rust, TBP, approximate sparring
   partner (guideline SRS only). Integration: build `tetris-core`, add a
   `TBPAgent` variant with its binary + optional `--tbp` arguments.
3. **In-repo variants** — already implemented (`variant` spec): jittered
   heuristic weights/noise and randomised beam search per episode, seeded and
   reproducible. Best defence against single-opponent overfitting.

Not for versus: Blockfish (cheese/downstack only), NullpoMino (licence + GUI),
Battletris (no licence, non-deterministic), ZetrisV2 (closed core), Cold Clear 1
(guideline-only baseline; possible future garbage-aware C-ABI experiment).

### 4.3 Protocol work (highest leverage)
Implement a **Python TBP frontend/host** in our repo:

* lets us validate any TBP bot against our Season 2 arena in a uniform way;
* reuses the existing `TBPAgent` transport and `docs/BENCHMARKS_INTEGRATION.md`
  findings;
* optional inverse: a thin TBP **bot wrapper** exposing our PPO/DQN policies to
  external TBP frontends (useful for third-party evaluation);
* must document approximate compatibility (no garbage/B2B-charge fields).

### 4.4 Integration plan
1. (Done) Cold Clear 2 adapter + real matches + integration doc.
2. Add RIKU TBP adapter: clone at a pinned commit into `third_party/`, build with
   `cargo build --release`, adapter spec `riku`, smoke match, licence notice.
3. Implement the Python TBP host for uniform benchmarking; add a replay-verified
   match runner that records external-engine metadata.
4. Extend curriculum Stage 5 to sample `coldclear`/`riku`/`variant` (external
   engines are slow; use them for evaluation-heavy stages, not every step).
5. Do **not** attempt SRS+/180/Season 2 parity claims for any external engine;
   label results "guideline-SRS opponent, arena-owned Season 2 rules".

### 4.5 Rejected / reference-only, with reasons
* `nyctivoe/tetris-engine-in-rust` — no licence; also not SRS+ in code
  (residual value: read-only design reference for Season 2 surface).
* `nevjin/ZetrisV2` — closed MisaMino DLLs with no licence, Windows-only GUI,
  keystroke injection; design reference only.
* `nullpomino` — mixed licensing including a non-OSI file and unlicensed
  sources, GUI-first, no headless versus runner; reference only.
* `battletris` — no licence, wall-clock/non-deterministic referee; protocol
  ideas only, use the MIT/Apache `tbp` crate if needed.
* `tbp-spec` — protocol only; text used for field documentation, no code copied.

---

## 5. Known gaps / follow-ups

* GitHub unauthenticated API rate limits prevented metadata calls (stars,
  archived flags) for several repos; these are marked `[UNKNOWN]` in the group
  reports.
* TETR.IO's 180 table is published as an image on the wiki; external 180 parity
  claims are therefore `[UNKNOWN]` and irrelevant to our engine, whose table is
  documented in `docs/RULESET.md`.
* No external engine was built or executed during this research except the
  already-documented Cold Clear 2 integration. RIKU remains unbuilt until the
  adapter task starts.

---

## 6. Addendum — `iclyxcly/MisaMino` (fork) assessment

Evaluated after the nine-repo audit; source inspected via a throwaway clone in
`/tmp` (nothing copied into this repository).

* **Identity:** a fork of `misakamm/MisaMino` ("forked from misakamm/MisaMino"
  on GitHub), with commits from 2021–2023 adding a TETR.IO attack table
  (`tetris_setting.h: TETRIO_ATTACK_TABLE 1`), 180° rotation
  (`tetris.h::trySpin180`), T-spin mini fixes, garbage/ping handling,
  adjustable preview and infinity hold.
* **Licence:** `LICENSE` is still the upstream 21-byte
  `Copyleft by Misakamm` — **non-OSI, no grant text**. All rights reserved; no
  linking, embedding, vendoring or code copying. Even for a course project this
  is not an appropriate dependency.
* **Mechanics:** MisaMino's classic wall-kick tables (`gamefield.h`,
  4 tests after the implicit basic rotation, separate I table); **guideline
  ordering, not SRS+** — the I-piece test order differs from TETR.IO. 180° is a
  **basic rotation with no kick tests** (`trySpin180` fails on collision), not
  the TETR.IO directional 180 table. T-spin/mini heuristics exist
  (`wallkick_spin` 1 = spin, 2 = mini) but there is no All-Mini+ and no Season 2
  attack model: the added "TETR.IO attack table" is the Season 1-style table,
  and there is no B2B charging, Surge, surge segmentation or Season 2 garbage
  speed/cap.
* **Platform:** Windows-only C++ (`.vcxproj`, EGE/graphics `.lib`, DirectX-era
  toolchain). `tetris_ai/main.cpp` is a GUI game; `dllai/` is the classic
  MisaMino Windows DLL AI interface (`TetrisAI_t`), not a line protocol. No
  headless mode, no Linux build, no TBP/SBP/JSON interface.
* **Role:** reference-only. It cannot serve as an RL environment (state lives in
  the DLL/GUI), and as an opponent it would require a Windows/Wine process plus a
  custom DLL bridge for a non-OSI binary — high effort with no redistribution
  rights.
* **Verdict: REJECT for integration; read-only reference.** Use the in-repo
  variants / RIKU / Cold Clear engines for opponent diversity instead.
