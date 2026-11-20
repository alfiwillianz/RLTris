# Engine Group B — Source-Level Audit

**Scope:** three third-party Tetris engines/bots considered as opponents or references for RLTris
(TETR.IO Season 2, SRS+).

| # | Repository | Audited commit |
|---|---|---|
| 1 | <https://github.com/RIKU0804/tetris-ai> | `d3f92d289a24e09ec72679d8ce653bfd8a98679e` (`HEAD`) |
| 2 | <https://github.com/nevjin/ZetrisV2> | `71e964e4481d12a7aebb04f5726f97272d9c4dec` (`HEAD`) |
| 3 | <https://github.com/blockfish/blockfish> | `739953f9331b7648f269fc52cff5aae330108ccd` (`HEAD`) |

**Method.** Read-only audit. No clone, build, install, or modification of any external repository; no
code copied into RLTris. Repo trees were read through the GitHub trees API, then individual files
through `raw.githubusercontent.com`. Licenses were read as full text, not inferred from metadata.
Activity dates come from each repo's `commits/HEAD.atom` feed because the REST metadata endpoint
returned **HTTP 403 (rate limit)** — star counts and the `archived` flag are therefore [UNKNOWN].

**Confidence labels**

- **[VERIFIED]** — read directly in the fetched source, with the file/symbol named.
- **[INFERRED]** — follows from build metadata, docs, or dependency shape, not from reading the
  relevant algorithm.
- **[UNKNOWN]** — could not be established from the public source (e.g. prebuilt binary, missing file).

Line numbers are deliberately omitted: raw file fetches do not carry stable line numbers, so every
claim cites a file and symbol/function instead of an invented line.

---

## 0. Executive summary

| | **RIKU0804/tetris-ai** | **nevjin/ZetrisV2** | **blockfish/blockfish** |
|---|---|---|---|
| License (exact) | **MIT** (© 2026 riku) | **BSD 3-Clause** (© 2018–2021 mat1jaczyyy) | **LGPL-2.1** (GNU Lesser GPL v2.1) |
| Language | Rust 2021 core + Python 3.10 ref | C# / .NET Framework 4.6.1 (WPF) + Python client | Rust (+ JS/Python bindings) |
| Build system | `cargo` (zero deps) / stdlib Python | MSBuild + NuGet (prebuilt AMD64 DLLs) | `cargo` (+ `protoc` for service) |
| Linux build | Yes, [INFERRED] high confidence | **No**, [VERIFIED] | Yes (engine/service), [INFERRED] high |
| GPU needed | No | No | No |
| Headless | Yes (`bench`, `vs`, `tbp`) | **No** (WPF window required) | Yes (`blockfish` service binary) |
| Board | 10×40 (20 visible) | 10×40 (TETR.IO base height 22) | 10×25 (20 visible) |
| 7-bag | Yes | Caller-side (client replicates TETR.IO RNG) | Yes |
| Hold | Yes | Yes | Yes |
| SRS (guideline) | Yes | Delegated to MisaMino | Yes (`support/guideline.json`) |
| **SRS+ I ordering** | **No** (guideline only) | **Configured**, tables in binary [UNKNOWN] | **Not established**; file is labelled "guideline" |
| **180° rotation** | **No** | **Yes** (flag + `180` instruction) | **No** (no 180 input/kick anywhere) |
| Spin detection | T only, 3-corner, full/mini | Delegated (MisaMino `AllSpins`) | **None** |
| All-Mini+ | No | No | No |
| Combo | Yes (attack table) | Tracked, passed to search | Only modulates cheese height |
| B2B | Chaining counter, flat +1 | Search-reported counter; no charging | **Absent** |
| Surge | No | No | No |
| Season 2 attack table | No | No | No |
| Garbage in/out | Pending queue, cancel, ≤8/turn | Incoming only, cancel-first, ≤8/turn | Incoming cheese only |
| Integration surface | TBP JSON-over-stdio subprocess | localhost HTTP + keyboard injection | protobuf-over-stdio subprocess |
| Role for RLTris | reference + approx. sparring opponent | **disqualified** dependency | cheese/downstack specialist |
| Complexity | **MEDIUM** | **HIGH** | **MEDIUM** (cheese mode only) |

---

## 1. RIKU0804/tetris-ai

### 1.1 Provenance and license

- `LICENSE` (fetched in full) is the standard **MIT License**, `Copyright (c) 2026 riku`.
  OSI-approved, MIT-compatible, no copyleft. [VERIFIED]
- Single-commit repository: `commits/HEAD.atom` shows one commit, *"feat: Tetris AI — Rust core,
  beam-search AI, versus training, TBP"*, dated **2026-06-22**. There is no `.github/` directory in
  the tree and no CI configuration. [VERIFIED]

### 1.2 Language, build, dependencies, Linux, GPU

- **Rust core** (`core-rs/`), edition 2021. `core-rs/Cargo.toml` has an **empty `[dependencies]`
  table** and no `build.rs`; the comment explains the author avoided serde/rayon/rand because a
  build-script `.exe` was blocked by an application-control policy. Release profile: `lto = true`,
  `panic = "abort"`. [VERIFIED]
- **Python reference implementation** (`tetris/`, `benchmark.py`, `tune.py`, `play_ai.py`).
  `requirements.txt` contains only `pygame>=2.5`, and its comment states the engine/AI/benchmark need
  only the standard library. [VERIFIED]
- **Builds on Linux:** [INFERRED] yes. Nothing OS-specific appears in the core (bitboards, `std::thread`,
  `OnceLock`); no dependency can pull in a platform constraint. Not built here by instruction, so this
  is inference from a dependency-free, portable source tree, not an executed build.
- **GPU:** no. CPU beam search only; no PyTorch/CUDA/numpy anywhere in the tree. [VERIFIED]

### 1.3 Implemented mechanics (from source)

| Mechanic | Finding | Evidence |
|---|---|---|
| Board | 10 × 40, 20 visible, spawn `(3, 18)`; bitboard `[u16; 40]`, one 10-bit row | `tetris/constants.py` (`WIDTH`, `HEIGHT`, `VISIBLE_HEIGHT`, `SPAWN_X/Y`); `core-rs/src/engine.rs` (`WIDTH`, `HEIGHT`, `Board`) |
| 7-bag | Fisher–Yates bag of all seven, refilled when empty; seeded PRNG | `tetris/randomizer.py::SevenBag`; `core-rs/src/main.rs::Bag` + `Rng` (SplitMix64) |
| Hold | Swap or pull-next, once per placement | `tetris/game.py::Game.do_hold`; `core-rs/src/main.rs::Game::do_hold` |
| Rotation | SRS wall/floor kicks, 5 tests per transition, `O` is a no-op | `tetris/constants.py` (`KICKS_JLSTZ`, `KICKS_I`, `KICKS_O`), `tetris/srs.py::try_rotate`, `core-rs/src/engine.rs::try_rotate`/`kicks_i`/`kicks_jlstz` |
| 180° | **Absent.** Kick tables only define adjacent transitions `(0,1),(1,0),(1,2),(2,1),(2,3),(3,2),(3,0),(0,3)`; `try_rotate` only takes `direction = ±1`; TBP exposes only `north/east/south/west` | `tetris/constants.py` (`KICKS_*` keys), `tetris/srs.py::try_rotate`, `core-rs/src/tbp.rs::orientation_name` |
| Spin detection | **T only**, 3-corner rule with front/back corner split: ≥3 corners filled, full if both front corners filled **or** kick index 4 (far kick), else mini. No immobile/all-mini detection, no TST special case, non-T pieces are always `Spin::None` | `tetris/srs.py::tspin_status`, `core-rs/src/engine.rs::tspin_status` |
| Placement search | BFS over left/right/soft-drop/rotate(+kicks) from spawn, keeps every resting state (tucks, spin slots); a lock reached via rotation flags `spin_possible` | `tetris/moves.py::generate_placements`, `core-rs/src/engine.rs::generate_placements` |
| Preview | Configurable; Python default 5, versus default 6–8 | `tetris/game.py::Game.__init__`, `core-rs/src/main.rs::cmd_bench`/`cmd_vs` |
| Lock delay / gravity | **None.** Hard-drop-only model; `game.py` docstring says gravity/lock delay simulation is not needed | `tetris/game.py` module docstring |

**Attack / combo / B2B (this is where the ruleset diverges from TETR.IO):**

- Attack table (`_ATTACK_NONE = (0,0,1,2,4)`, `_ATTACK_TSPIN = (0,2,4,6)`, `_ATTACK_MINI = (0,1,2)`,
  combo table `(0,0,1,1,2,2,3,3,4,4,4,5)`, flat `_B2B_BONUS = 1`, `_PC_BONUS = 10`) in
  `tetris/game.py::Game._apply_clear`; duplicated in `core-rs/src/main.rs::Game::apply_clear`
  (`ATTACK_NONE`, `ATTACK_TSPIN`, `ATTACK_MINI`, `COMBO`). [VERIFIED]
- **B2B is chaining, not charging:** `self.b2b = self.b2b + 1 if difficult else 0` and the bonus is a
  flat `+1` whenever `b2b > 0`. No stored charge, no escalating bonus. [VERIFIED]
- Combo: increments on every consecutive clear, resets on a no-clear; attack bonus read from the
  combo table. [VERIFIED]
- Line-clear classification is `(spin, lines)`; Perfect Clear adds `+10` attack. [VERIFIED]

**Garbage (versus only):** `core-rs/src/vs.rs::play_vs`

- Per-side `pending` counter; **one-turn delay** ("garbage has a one-turn delay before it can be
  cancelled / tanked").
- Outgoing attack cancels own pending first (`cancel = atk.min(pending[p])`), remainder is sent to the
  opponent.
- If the player cleared nothing, up to `MAX_GARBAGE_PER_TURN = 8` pending lines are inserted; the hole
  column is drawn once (`grng.range(WIDTH)`) and reused for the whole dump. Board push via
  `Game::add_garbage`.
- No garbage *queue entries* (no per-row holes, no change-on-attack, no messiness), no garbage speed
  parameter, no cap beyond 8/turn. [VERIFIED]
- Both players share the same piece seed (fair) but use a separate garbage RNG. [VERIFIED]

### 1.4 SRS+ and 180 compatibility

- **Guideline SRS only — explicitly not SRS+.** The I-piece table in `tetris/constants.py::KICKS_I`
  for `(0,1)` is `(0,0), (-2,0), (+1,0), (-2,+1), (+1,-2)` in the code's y-down frame, i.e. the
  guideline ordering `(0,0), (-2,0), (+1,0), (-2,-1), (+1,+2)` after the y flip. SRS+ tries the
  mirrored left kick first (`(+1,0)` before `(-2,0)` for 0→R; see `docs/RULESET.md` §3.3). The same
  guideline ordering is mirrored in Rust (`core-rs/src/engine.rs::kicks_i`). [VERIFIED]
- There is **no second I table, no SRS+ flag, and no 180 table** anywhere in the tree. `try_rotate`
  cannot express a 180 (`direction` is ±1; no `(0,2)`/`(1,3)` kick keys). [VERIFIED]
- Consequence: a placement that requires the SRS+ ordering (double-valid kick cases) or a 180 will
  simply not be proposed by this bot. Rare, but it means "plays SRS+" is false.

### 1.5 TETR.IO Season 2 support

| Season 2 mechanic | Status | Evidence |
|---|---|---|
| B2B charging | **Absent** — counter + flat +1 only | `Game._apply_clear` |
| Surge | **Absent** — no surge state, meter, or release logic anywhere | full tree |
| Season 2 attack table | **Absent** — custom table resembling TETR.IO S1-era values (0/1/2/4, T-spin 2/4/6, mini 1/2); lineage [INFERRED] | `_ATTACK_*` constants |
| Garbage speed / cap | **Approximated only**: 1-turn delay, 8/turn cap, no speed table | `vs.rs::play_vs` |
| All-Mini+ | **Absent** — 3-corner T-only classification, no immobile rule | `tspin_status` |

The ruleset is best described as *guideline-ish versus*, not TETR.IO S1 and certainly not S2.

### 1.6 Headless operation and entry points

Headless: **yes**. `core-rs/src/main.rs::main` dispatches:

```
tetris-core bench        # self-play strength benchmark
tetris-core vs           # bot-vs-bot match, prints per-match attack
tetris-core vs-tune      # GA tuning by match fitness
tetris-core vs-replay    # writes replay.json for viewer.html
tetris-core tune         # solo GA
tetris-core tbp          # Tetris Bot Protocol, JSON lines on stdin/stdout
tetris-core tbp-selftest
```

Python equivalents: `benchmark.py`, `tune.py`, `tests/test_engine.py`. Only `play_ai.py` (pygame) and
`viewer.html` need a display. [VERIFIED]

### 1.7 Protocol / integration surface

- **TBP (Tetris Bot Protocol), JSON-lines over stdio**, implemented in
  `core-rs/src/tbp.rs::cmd_tbp` / `TbpState`.
  - Inputs: `{"type":"rules"}` → `{"type":"ready"}`; `{"type":"start","board":[[...]],"queue":[...],
    "hold":null,"combo":0,"back_to_back":false}`; `{"type":"new_piece","piece":"T"}`;
    `{"type":"suggest"}`; `{"type":"play","move":{...}}`; `{"type":"stop"}`; `{"type":"quit"}`.
  - Output: `{"type":"info",...}` greeting, `{"type":"suggestion","moves":[{"location":{"type":"T",
    "orientation":"north","x":…,"y":…},"spin":"full"}]}`.
  - The bot maintains its *own* board from `play` messages (`TbpState::handle_play`), including hold
    reconciliation and B2B/combo updates — so a referee must feed every placement faithfully or the
    bot desyncs.
  - The file's own doc comment warns the centre convention for **I and O** is "under-specified" in the
    public MVP spec and is isolated in `to_tbp_xy` / `from_tbp_xy`. [VERIFIED]
- No library target: `core-rs` is a binary crate (`main.rs` declares `mod engine; mod eval; …`), so it
  cannot be `use`d as a Rust dependency without refactoring. [VERIFIED]
- The Python engine is importable (`tetris.game.Game.step`, `tetris.ai.best_move`,
  `tetris.moves.generate_placements`) but is a reference implementation, not an environment API.

### 1.8 Role and complexity

**Role:** *reference implementation* (guideline SRS + 3-corner T-spin + reachable-placement BFS is a
useful cross-check) and a *placement-suggesting sparring opponent* via TBP. It is **not** an RL
environment: state is bot-owned, there is no `reset()/step()` contract, the crate is binary-only, and
it cannot accept an external agent's actions except through TBP `play`.

**Complexity: MEDIUM.** Running `bench`/`vs` is trivial, but using it as an opponent means writing a
TBP referee (board serialisation, queue feeding, hold/desync handling), accepting guideline-SRS
divergence (no SRS+, no 180), and explicitly labelling the match "approximate ruleset". The
I/O centre ambiguity adds a small correctness trap.

**Risks:** MIT (safe). Single author, single commit, no CI, one test file → low bus factor and no
maintenance signal; but the code is small and self-contained, so risk is mostly "unmaintained", not
"hostile". Archived status [UNKNOWN] (metadata 403).

### 1.9 What this means for RLTris

tetris-ai is the most *compatible* of the three in spirit — MIT, Rust, headless, genuinely
search-based (beam search over all reachable placements, including tucks and spin slots) — but its
ruleset is guideline SRS with a hand-rolled attack table. Use it in two narrow ways: (a) as a
correctness oracle for our own guideline-SRS/T-spin tests (never as the SRS+ oracle), and (b) as an
"approximate opponent" driven over TBP, always reported as *guideline SRS, no 180, custom attack* so
results are not confused with Season 2 benchmarks. Do not present its win rate as evidence about SRS+
or Season 2 play, and do not link the crate (it is not a library); subprocess only.

---

## 2. nevjin/ZetrisV2

### 2.1 Provenance and license

- `LICENSE` (fetched in full) is **BSD 3-Clause**, `Copyright (c) 2018 - 2021, mat1jaczyyy`.
  OSI-approved, permissive, MIT-compatible with attribution and no-endorsement. [VERIFIED]
- The repository is a **re-upload**, not upstream development: a single commit *"Add files"* dated
  **2025-05-17**, and the copyright holder in `LICENSE` is `mat1jaczyyy`, not the repo owner
  (`nevjin`). The tree contains two near-duplicate WPF projects (`src/` = TETR.IO, `Zetris.PPT/` = PPT)
  and the original `Zetris/` shared library. Treat provenance and binary contents with suspicion.
  [VERIFIED]

### 2.2 Language, build, dependencies, Linux, GPU

- **C# / .NET Framework 4.6.1 WPF**, `OutputType=WinExe`, WPF assemblies (`PresentationFramework`,
  `WindowsBase`), `LangVersion 7.3`, `PlatformTarget x64`. [VERIFIED —
  `src/Zetris.TETRIO.csproj`, `Zetris/Zetris.csproj`]
- NuGet dependencies (`src/packages.config`): `MisaMinoNET 1.9.3` (which brings native
  `MisaMino.dll`, AMD64), `PerfectClearNET 1.4.0.3`, `Newtonsoft.Json 12.0.3`, `MahApps.Metro 1.6.5`,
  `ControlzEx 3.0.2.4`, `ProcessMemory 1.1.1`. [VERIFIED]
- The PPT variant additionally ships **`ScpDriverInterface.dll`, `ScpDriverInstaller.exe`, and
  kernel-mode driver binaries `ScpVBus.sys` (amd64/x86) plus `DIFxAPI_x64/x86.dll`** for virtual
  gamepad emulation. [VERIFIED — tree listing]
- **Linux: no.** WPF + .NET Framework 4.6.1 + `HttpListener` + native AMD64 Windows DLLs; no
  `netcore`/`net6`/Linux project file exists. Running it on Linux would require a Windows VM or Wine,
  neither verified. [VERIFIED negative, [UNKNOWN] for Wine]
- **GPU:** no. CPU search; `PCThreads()` defaults to `Environment.ProcessorCount`. [VERIFIED]

### 2.3 Implemented mechanics (from source)

| Mechanic | Finding | Evidence |
|---|---|---|
| Board | `int[10, 40]`; TETR.IO base height 22 (`baseBoardHeight = 22`, adjusted by `FitPieceWithConvert`); PPT variant base 21/25 | `Zetris/Bot.cs` (`board` field, `baseBoardHeight`), `src/TetrioBot.cs::startThinking`/`LoopIteration` |
| Piece supply | The bot **does not generate pieces**; the caller supplies `pieces[]` and `hold` | `src/TetrioBot.cs::Starting` → `/newGame` handler |
| 7-bag | Caller-side only. `client/main.py` re-implements TETR.IO's RNG (16807 LCG, `MODULUS=0x7fffffff`, `shuffle`) and emits 50 bags | `client/main.py::RNG`, `generate_queue` |
| Hold | `hold` field, `Instruction.HOLD`, client maps to Left Shift; gated by `HoldAllowed()` | `Zetris/Bot.cs`, `client/main.py::hold` |
| Rotation / SRS+ | **Delegated:** `UpdateConfig()` calls `MisaMino.Configure(param, HoldAllowed(), AllSpins(), TSDOnly(), Intelligence(), Allow180(), SRSPlus())` | `Zetris/Bot.cs::UpdateConfig` |
| SRS+ flag | `protected override bool SRSPlus() => true;` | `src/TetrioBot.cs` |
| 180° | `protected override bool Allow180() => true;`; `Instruction.SPIN2` maps to TETR.IO move `"180"`, client presses `a` | `src/TetrioBot.cs` (`Allow180`, `ToTetrio`), `client/main.py::spin180` |
| Spin detection | Delegated to MisaMino (`AllSpins()` preference). In-repo code only has a PPT input heuristic `FixTspinMini`; no 3-corner implementation | `Zetris/Bot.cs`, `Zetris.PPT/PPTBot.cs::FixTspinMini` |
| Combo | `combo` field, incremented when `clear > 0`, passed into `MisaMinoAOT` | `src/TetrioBot.cs` (`/nextMove` handler) |
| B2B | Taken from the search result (`b2b = MisaMino.LastSolution.B2B`), with a fallback heuristic `FuckItJustDoB2B(board, 25)` and a "hack" `b2b = 1` at game start. Not a charging model | `Zetris/Bot.cs::MakeDecision`, `NewGame`, `MisaMinoAOT` |
| Attack | `atk = MisaMino.LastSolution.Attack` (table inside the DLL) | `Zetris/Bot.cs::MakeDecision` |
| Garbage | `AddGarbage(board, garbage, attack, out leftover)`: `leftover = garbage - attack`, then insert `min(8, leftover.Length)` lines, one hole column per line; leftover recomputed by skipping `m`. Cancel-first, cap 8/turn | `src/TetrioBot.cs::AddGarbage`, `/nextMove` (`garbage - atk`, `Math.Max(0, garbage - 8)`) |
| Garbage holes | `AddGarbageLine` fills a row, clears one column; PPT version randomises a column per line with a 1-in-99 column shift | `Zetris/Bot.cs::AddGarbageLine`, `Zetris.PPT/PPTBot.cs::AddGarbage` |

### 2.4 SRS+ and 180 compatibility

- **Flags are real and reach the search core.** `src/TetrioBot.cs` overrides `Allow180() => true` and
  `SRSPlus() => true`, and `Zetris/Bot.cs::UpdateConfig` passes both into
  `MisaMino.Configure(...)`. The TETR.IO move vocabulary includes `"180"`, and the Python client
  presses the 180 key (`a`). [VERIFIED]
- **The tables themselves are not in the repository.** They live in `MisaMino.dll` /
  `MisaMinoNET.dll` (NuGet `MisaMinoNET 1.9.3`, prebuilt AMD64 binaries). No license, source, or
  versioned table accompanies them in this repo. Whether MisaMino 1.9.3's `SRSPlus` matches TETR.IO's
  SRS+ I ordering and whether its 180 table matches TETR.IO's 180 table is **[UNKNOWN]** — it cannot
  be verified from source here.
- The PPT variant explicitly disables both (`Allow180() => false; SRSPlus() => false`), confirming
  these are deliberate per-game toggles rather than dead code. [VERIFIED]

### 2.5 TETR.IO Season 2 support

| Season 2 mechanic | Status | Evidence |
|---|---|---|
| B2B charging | **Absent** — B2B is a bare integer from `LastSolution.B2B`; no charge accumulation | `Bot.cs::MakeDecision` |
| Surge | **Absent** — no surge state or release logic | full tree |
| Season 2 attack table | **Absent/unverifiable** — attack comes from the 2021-era MisaMino 1.9.3 package, i.e. before Season 2 | `MisaMino.LastSolution.Attack` [UNKNOWN table] |
| Garbage speed / cap | **Approximated**: cap 8/turn, cancel-first, single hole per line; no speed table | `TetrioBot.AddGarbage` |
| All-Mini+ | **Absent** — `AllSpins()` is a MisaMino option (All-Spins, not All-Mini+) | `Bot.cs::UpdateConfig`, `src/TetrioBot.cs::AllSpins` |

The bot is a TETR.IO-era (pre-Season 2) MisaMino wrapper: SRS+/180 yes, Season 2 no.

### 2.6 Headless operation and entry points

**Headless: no.** The application is a WPF `WinExe`; `Bot.Start(UI window)` stores the window and the
TETR.IO loop sets `Window.Active = true`, `Window?.SetPortTitle(...)`, `Window?.SetConfidence(...)`.
A null window is not supported (`Window.Active` is an unconditional dereference in
`/newGame`). [VERIFIED]

Entry points:

- Launch the WPF app (`Zetris.TETRIO.exe`); it hosts an `HttpListener` on
  `http://127.0.0.1:47326/` (auto-increments the port if busy) — `src/TetrioBot.cs::Starting`.
- Drive it with `client/main.py` (Python 3, `requests` + `keyboard`), which types keystrokes into the
  TETR.IO desktop client.

### 2.7 Protocol / integration surface

- **Local HTTP JSON API** (`src/TetrioBot.cs::Starting`, `LoopIteration`):
  - `POST /newGame` — body `{id, board: 40×10 transposed array, pieces: ["T",…], hold, garbage}`;
    resets state, loads the board (`loadBoardFromJSON` reads `reset[39-j, i]`), sets previews.
  - `POST /newPieces` — append pieces.
  - `POST /nextMove` — body `garbage`; returns
    `{id, moves: ["Left"|"Right"|"Cw"|"Ccw"|"180"|"Hold"|"SonicDrop"|"HardDrop"|"DASLeft"|"DASRight"],
    expected_cells: [[x,y],…]}`.
  - `POST /resetBoard`, `/endGame`, `/speedUp`, `/speedDown`, `/chatCommand`.
- **Caveat [INFERRED]:** the bundled `client/main.py` posts `{"garbage": 0}` (a JSON object), while
  `/nextMove` executes `garbage = (int)e;` on the whole parsed body. That is inconsistent, so the
  client should be treated as an unsupported sample rather than an SDK.
- The move list is a **timed input sequence**, not a placement; the caller must simulate key timing
  and the game's own lock delay.

### 2.8 Role and complexity

**Role:** *external placement-suggesting bot for the live TETR.IO client*, not an engine, not an
environment. It reads/serves a board snapshot and returns key presses; the actual rules are enforced
by TETR.IO. The PPT variant goes further (process-memory reading plus virtual gamepad injection) and
even ships a kernel driver.

**Complexity: HIGH.** Windows-only GUI app, .NET Framework 4.6.1, closed native search DLLs, no
headless mode, no Linux path, no tests, timing-dependent input protocol, and a client/server payload
mismatch to debug. Making it a benchmark on Linux would require a Windows VM plus a referee that
emulates the TETR.IO client's board/queue feed and replays keystrokes — a large amount of
unverifiable glue for a bot whose rules can't be inspected.

**Risks (material):**

- **Not permissible under this project's own rules.** RLTris's AGENTS.md forbids depending on a
  closed-source implementation; the search core here is a prebuilt binary with no license text in the
  repo. [VERIFIED absence of third-party license files]
- The repository includes **Windows kernel-mode driver binaries** (`ScpVBus.sys`) and installer EXEs.
  Shipping or running these is a supply-chain and legal risk far outside a research dependency.
- Cheating-adjacent design: the TETR.IO build injects inputs into the live client, and the README
  warns it is not intended for competitive play. Using it against online opponents would violate
  TETR.IO's terms.
- BSD-3 covers *this* code, but the bundled binaries are **license-unknown** [UNKNOWN]; the mirror is a
  single unreviewed commit.

### 2.9 What this means for RLTris

ZetrisV2 is the only one of the three that actually turns on SRS+ and 180 — and that is exactly why it
is tempting and exactly why it must be rejected. The flags are visible, but the tables are inside a
closed DLL, so we cannot verify SRS+ ordering or 180 parity; it cannot run headless on Linux; and it
depends on binaries with no license. It therefore fails both the technical and the policy bar for a
benchmark. Keep it only as a *design reference*: it shows the clean shape of the configuration surface
(`SRSPlus`, `Allow180`, `AllSpins` booleans plumbed into one `Configure` call), which is a good model
for our own `ruleset.py` toggles. Do not vendor, link, or invoke it, and do not cite its play strength
as a Season 2 result.

---

## 3. blockfish/blockfish

### 3.1 Provenance and license

- `LICENSE.txt` (fetched in full) is the **GNU Lesser General Public License, Version 2.1**
  (February 1999). The text does **not** include an "or later" clause. The commit that added it says
  *"[v0.8.8] add license and .deb builder … add LICENSE.txt (LGPL 2.1)"*. [VERIFIED]
- Actively maintained around 2020–2022 and again in 2025: `commits/HEAD.atom` shows
  *"Merge pull request #11 from yaahc/rate-last-move"* dated **2025-07-13**, with earlier history back
  to 2020. Not dead, not archived as far as the feed shows (archived flag [UNKNOWN], metadata 403).
  [VERIFIED dates]

### 3.2 Language, build, dependencies, Linux, GPU

- **Rust** workspace (`Cargo.toml`: members `blockfish-engine`, `blockfish-client`, `block-stacker`),
  plus `blockfish-js` (Node bindings) and `blockfish-python` (asyncio bindings).
- Engine dependencies (`blockfish-engine/Cargo.toml`): `thiserror`, `log`, `red_union_find`, `serde`,
  `serde_json`; optional `argh`, `signal-hook` (race), `protobuf` + `pretty_env_logger` (service);
  build-dependency `protoc-rust` for the `protos` feature. Requires `rustc` 1.48+ and **`protoc`** to
  build the service. [VERIFIED]
- The **client** needs SDL2 + SDL2_ttf dev libraries (README); the engine/service does not. [VERIFIED]
- **Linux:** [INFERRED] yes — `scripts/build-dpkg.sh` exists (Debian packaging), the engine has no
  platform-specific code, and SDL2 is cross-platform. Not built here.
- **GPU:** no. CPU B*/A* search.

### 3.3 Implemented mechanics (from source)

| Mechanic | Finding | Evidence |
|---|---|---|
| Board | 10 × 25, 20 visible, 5 previews | `support/guideline.json` (`cols`, `rows`, `visible_rows`, `previews`) |
| 7-bag | `Pieces::with_random_bag(prng, types)`; previews refilled from the bag; seed configurable | `block-stacker/src/stacker.rs::Next`, `Config.prng_seed` |
| Hold | `Stacker::hold` (with a `TODO: prevent repeat holds`) | `block-stacker/src/stacker.rs::hold` |
| Rotation | SRS kicks per transition; `Piece::try_rot_by` walks the kick list; only `Input::CW`/`Input::CCW` | `block-stacker/src/stacker.rs::Piece::try_rot_by`, `block-stacker/src/ruleset.rs::Ruleset::kicks` |
| kick data | 8 entries per piece (4 CW + 4 CCW), 5 tests each for JLSTZ and I, empty for O; labels `>r`/`<r` | `support/guideline.json`, `ruleset.rs::Kick` |
| 180° | **Absent.** `Kick` enum has only `CW`/`CCW`; `Input` has `LEFT, RIGHT, CW, CCW, HOLD, SD, HD`; `PlaceFinder::expand` only tries those four | `block-stacker/src/ruleset.rs::Kick`, `blockfish.proto::Input`, `blockfish-engine/src/place.rs::PlaceFinder::expand` |
| Spin detection | **None.** No T-spin/mini logic; evaluation has no spin term | `blockfish-engine/src/ai/eval.rs` (only `rows`, `piece_estimate`, `i_dependencies`) |
| Evaluation | Mystery's residue-based minimum-piece estimate + I-dependency count; **lower is better** | `ai/eval.rs::Eval::score`, `piece_estimate`, `i_dependencies` |
| Search | B* / A*-style best-first over placements, node limit configurable | `ai/b_star.rs`, `ai/analysis.rs`, `bin/service.rs::set_config` |
| Garbage | **Incoming cheese only**: `Cheese::generate` inserts rows at the bottom with random hole columns; `GarbageConfig { min_height: 4, max_height: 9, total_lines }`; a combo makes the next garbage shorter | `block-stacker/src/stacker.rs::Cheese`, `GarbageConfig` |
| Attack / out-garbage | **Absent.** `hard_drop` returns `(lines_cleared, garbage_cleared)`; nothing is sent anywhere | `stacker.rs::hard_drop`, `matrix.sift` |
| Combo | Only `combo: bool` affecting cheese height; no combo attack | `stacker.rs::Cheese::generate`, `hard_drop` |
| B2B | **Absent** | full engine |
| Board height | Dynamic (vector of lines), fixed 10 columns | `stacker.rs::Matrix` |

### 3.4 SRS+ and 180 compatibility

- **180: definitively no.** There is no 180 input in the protobuf (`Input` enum), no 180 key in the
  kick map (only `CW(r)`/`CCW(r)`), and no `(rot+2)` path in placement expansion. [VERIFIED]
- **SRS vs SRS+: not established → [UNKNOWN].** The kick data is named `support/guideline.json` and
  the project targets Jstris cheese race, which strongly suggests guideline SRS [INFERRED]. However,
  blockfish's `I` rotation numbering is non-canonical (state 0 is the *vertical* I, unlike SRS spawn),
  so I did not bit-compare its ordering to TETR.IO's SRS+ I table. What is certain: the data is
  CW/CCW-only, five tests per transition, `O` empty, i.e. a guideline-shaped SRS table.
- Practical consequence: do not claim SRS+ parity for Blockfish; treat it as guideline SRS.

### 3.5 TETR.IO Season 2 support

| Season 2 mechanic | Status | Evidence |
|---|---|---|
| B2B charging | **Absent** | no B2B state at all |
| Surge | **Absent** | no meter/attack model |
| Season 2 attack table | **Absent** | no attack generation |
| Garbage speed / cap | **Not applicable**: cheese rises in fixed slabs (min 4 / max 9 rows) | `GarbageConfig` |
| All-Mini+ | **Absent** | no spin detection |

Blockfish models neither versus nor Season 2. It models *cheese race*: clear 100 lines of garbage
using as few pieces as possible.

### 3.6 Headless operation and entry points

Headless: **yes** for the engine.

- `blockfish` binary (`blockfish-engine/src/bin/service.rs`, feature `service`): protobuf
  length-delimited request/response over **stdin/stdout**. No display needed.
- `blockfish-race` (`bin/race.rs`, feature `race`): CLI self-play/benchmark of cheese races.
- `blockfish-gen-shtb`: regenerates the shape/kick table from `support/guideline.json`.
- The SDL2 GUI client (`blockfish-client`) is optional and needs a display.

### 3.7 Protocol / integration surface

From `blockfish.proto` (described, not copied):

| Message | Fields observed |
|---|---|
| `Request` (oneof) | `set_config`, `set_ruleset`, `analyze` |
| `Request.Config` | `node_limit`, `max_results`, `max_placements` |
| `Request.Analyze` | `id`, `snapshot` |
| `Snapshot` | `hold` (string), `queue` (string), `rows` (repeated string) |
| `Response` (oneof) | `greeting`, `finished` |
| `Response.Greeting` | `version`, `motd` |
| `Response.Analysis` | `id`, `stats`, repeated `suggestions` |
| `Suggestion` | `rating` (sint64), repeated `inputs` (enum `Input`) |
| `Input` enum | `LEFT, RIGHT, CW, CCW, HOLD, SD, HD` |

- `rows` are strings of piece letters per row, **bottom line first** (documented in
  `blockfish-js/src/ai.js`); `hold`/`queue` are piece letters (`IOTSZJL`), `' '`/non-letter = empty.
- `rating` is a cost: **lower is better**; `inputs` is a key sequence (`left, right, cw, ccw, hold, sd,
  hd`) that produces the placement — not a final `(x, y, rot)`.
- `set_ruleset` is a no-op: `bin/service.rs::set_ruleset` logs *"`set_ruleset` is useless currently"*.
  The engine always uses the compiled-in guideline SRS table. [VERIFIED]
- **Python binding:** `blockfish-python/blockfish/ai.py` — `AI.start()`, `AI.analyze(snapshot,
  node_limit=…)`, `Suggestion(rating, inputs)`; `blockfish/ipc.py::create_subprocess_ipc()` spawns the
  binary and frames messages with protobuf varints. It needs generated `blockfish_pb2` (protoc) and the
  `protobuf` package. This is the cleanest integration surface.
- **JS binding:** `blockfish-js/src/ai.js` — `new AI(path)`, `ai.analyze(snapshot, options, cb)`.

### 3.8 Role and complexity

**Role: cheese-race / downstacking evaluator only — confirmed from source, not just the README.**
Three independent signals: (1) the evaluation minimizes remaining garbage rows, an estimated minimum
piece count, and I-dependencies; (2) the garbage model only *inserts* cheese and never sends anything
(`hard_drop` returns counts, `Cheese::generate` only adds rows); (3) the wire protocol has no opponent,
no pending garbage, and no attack fields — just `hold`, `queue`, `rows`. There is no versus mode to
enable.

**Complexity: MEDIUM (cheese mode).** Build with `cargo build --release --features service`, which
needs `protoc`; then either use the Python binding (needs `blockfish_pb2` generation) or speak the
varint-framed protobuf yourself. Board rows are easy to produce from our engine; suggestions are input
sequences, so our adapter must either replay them or map them to a placement. It cannot be used as a
versus opponent at all.

**Risks:** LGPL-2.1 (weak copyleft; see §4). MSRV 1.48-era dependencies (`protobuf 2.27`,
`log 0.4.8`) are old; `protoc-rust` requires a matching `protoc`. No security issues observed in the
audited files. Archived status [UNKNOWN]; last commit 2025-07.

### 3.9 What this means for RLTris

Blockfish is a high-quality, genuinely search-based downstacking engine, and that is precisely the
scope to use it in. It is **not** a general versus benchmark and must never be reported as one: its
objective is "finish 100 lines of cheese in the fewest pieces", with no attack, no B2B, no spins and
no opponent. The honest use is a *cheese/downstack specialist baseline* — e.g. a garbage-clearing
side-event or an efficiency metric ("pieces per 100 garbage lines") — or a sanity check that our
engine's garbage insertion and hole patterns behave. For the main Season 2 arena, it is out of scope
by construction. Because it is LGPL-2.1, integrate it strictly as a subprocess through its protobuf
service; do not copy or statically link it.

---

## 4. Compatibility matrix

Legend: **✔** implemented from source · **≈** approximate / partial · **✘** absent · **?** delegated to
an unreadable binary or unresolved.

| Mechanic | tetris-ai | ZetrisV2 | blockfish |
|---|---|---|---|
| Board size | 10×40 (20 vis.) | 10×40 (base 22) | 10×25 (20 vis.) |
| 7-bag | ✔ | ✔ (caller/client) | ✔ |
| Hold | ✔ | ✔ | ✔ |
| Guideline SRS kicks | ✔ (5 tests) | ✔ (delegated) | ✔ (guideline.json) |
| **SRS+ I ordering** | ✘ guideline only | ✔ flag / ? table | ✘/? labelled guideline |
| **TETR.IO 180 table** | ✘ | ✔ flag / ? table | ✘ |
| T-spin full/mini | ✔ (3-corner, T only) | ? (MisaMino) | ✘ |
| All-Mini / All-Mini+ | ✘ | ✘ (`AllSpins` ≠ All-Mini+) | ✘ |
| Combo | ✔ (attack table) | ✔ (tracked) | ≈ (cheese height only) |
| B2B chaining | ✔ (flat +1) | ✔ (from search) | ✘ |
| **B2B charging** | ✘ | ✘ | ✘ |
| **Surge** | ✘ | ✘ | ✘ |
| **S2 attack table** | ✘ | ✘ / ? | ✘ |
| Garbage queue + cancel | ≈ (counter, 1-turn delay) | ≈ (counter, cancel-first) | ✘ (incoming cheese only) |
| Garbage cap | 8/turn | 8/turn | n/a (slab 4–9) |
| Garbage speed table | ✘ | ✘ | ✘ |
| Headless | ✔ | ✘ | ✔ |
| Linux build | ✔ [INFERRED] | ✘ | ✔ [INFERRED] |
| GPU required | ✘ | ✘ | ✘ |
| Machine protocol | TBP JSON-lines | HTTP JSON + keystrokes | protobuf over stdio |
| Tests in repo | 1 test file | none | unit tests + fishtest |

---

## 5. Licensing and safe integration mode

> **Question: does any license forbid linking/embedding into an MIT project?**

No license here *forbids* linking in the absolute sense, but the obligations differ sharply:

| Repo | License | Link/embed into MIT? | Copy code into MIT repo? | Safe mode for RLTris |
|---|---|---|---|---|
| tetris-ai | MIT | Yes, with copyright + permission notice | Yes, with notice (but we are not copying) | subprocess (TBP); notice if ever vendored |
| ZetrisV2 | BSD-3-Clause (own code) | Yes, with copyright + conditions + no-endorsement | Yes, with notice | **subprocess only, and only if the binary problem is solved — not recommended** |
| blockfish | LGPL-2.1 | Allowed, but the combined binary becomes subject to LGPL §6 (provide source of the library, allow relinking, notices) | **No** — copying into an MIT file would relicense the copied code, which LGPL does not permit | **subprocess over protobuf** (arm's-length IPC; the executable stays a separate work) |

**Detailed notes**

- **MIT (tetris-ai):** fully compatible. Attribution required in distributions. No copyleft, no
  linking restriction.
- **BSD-3 (ZetrisV2):** the *repository's own* C# is permissive and MIT-compatible (keep the notice,
  don't use the author's name to endorse). The blocker is not BSD-3 — it is that `MisaMino.dll`,
  `MisaMinoNET.dll`, and `PerfectClearNET.dll` are **prebuilt binaries with no license text in the
  repo** [UNKNOWN], and the PPT folder ships kernel drivers. Linking or redistributing those is not
  something BSD-3 grants.
- **LGPL-2.1 (blockfish):** weak copyleft. You may link against it, but a *distributed* binary that
  contains it must satisfy §6: prominent notice, a copy of the license, and a way for the recipient to
  relink with a modified library. Static linking into `tetrisrl` would drag the whole binary under
  those terms. Running `blockfish` as a **separate process** (its intended `service` design,
  with the shipped Python/JS bindings) keeps it at arm's length and is the compliant, low-friction
  mode. Note the license text has no "or later" clause, so it is LGPL-**2.1**-only as distributed.

**Project rule restated:** no external code is copied into this repository by this audit. Adapters, if
built later, must live behind a subprocess boundary and carry the upstream license notice and a
`docs/BENCHMARKS.md` entry describing the ruleset mismatch.

---

## 6. Cross-cutting conclusions for RLTris

1. **None of the three is a Season 2 engine.** All three lack B2B charging, Surge, the Season 2 attack
   table, and All-Mini+. Only ZetrisV2 even claims SRS+/180, and it does so through a closed binary we
   cannot verify. Our own engine remains the only source of truth for S2; these repos are sparring
   partners at best.
2. **Only one repo is policy-compliant as a dependency.** tetris-ai (MIT, source-only, headless) and
   blockfish (LGPL, source, subprocess) clear the bar; ZetrisV2 fails the "no closed-source
   dependency" rule and is Windows-only.
3. **The realistic benchmark ladder is:** our engine + random/heuristic baselines → tetris-ai over TBP
   (labelled *guideline SRS, no 180, custom attack*) → blockfish as a *cheese/downstack* specialist
   metric, not a versus opponent. There is no open, source-verifiable SRS+/S2 versus engine in this
   group.
4. **Ruleset mismatches must be explicit in results.** Any match against Group B engines should be
   stored with a `ruleset=approximate-guideline-srs` tag so Season 2 win rates are never conflated
   with guideline results.
5. **Protocol work is the real cost, not the build.** All three integration paths require a referee or
   adapter (TBP lines, protobuf frames, or keystroke timing). Budget for adapters and desync tests, not
   for compilation.

### Per-repo bottom line

- **tetris-ai:** the best fit of the three — MIT, headless, real beam search — usable as a
  *placement-suggesting approximate opponent* and as a guideline-SRS/T-spin reference. Not an RL
  environment, not SRS+, not Season 2. **MEDIUM** complexity, subprocess via TBP.
- **ZetrisV2:** attractive because it toggles SRS+ and 180, but the tables are in a closed DLL, it
  needs a Windows GUI and keystroke injection, and it ships unlicensed binaries (and a kernel driver
  in the PPT variant). **Disqualified** as a dependency; design reference only. **HIGH** complexity.
- **blockfish:** excellent, actively maintained cheese-race/downstacking engine, confirmed
  non-versus from source (no attack, no B2B, no spins, no opponent in the protocol). Use as a
  *specialist downstacking baseline* via its protobuf subprocess service; LGPL-2.1 forbids copying and
  makes static linking awkward. **MEDIUM** complexity, cheese mode only.

---

## 7. Sources actually fetched

All fetched on 2026-11-20 (Asia/Jakarta). GitHub REST metadata calls returned **HTTP 403 — rate
limit**; that is the only failed category.

### Repo 1 — RIKU0804/tetris-ai

| URL | Status |
|---|---|
| `https://api.github.com/repos/RIKU0804/tetris-ai/git/trees/HEAD?recursive=1` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/LICENSE` | 200 (MIT) |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/README.md` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/requirements.txt` | 200 (pygame only) |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/core-rs/Cargo.toml` | 200 (no deps) |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/tetris/constants.py` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/tetris/srs.py` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/tetris/randomizer.py` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/tetris/game.py` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/tetris/moves.py` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/tetris/ai.py` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/core-rs/src/engine.rs` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/core-rs/src/main.rs` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/core-rs/src/vs.rs` | 200 |
| `https://raw.githubusercontent.com/RIKU0804/tetris-ai/HEAD/core-rs/src/tbp.rs` | 200 |
| `https://github.com/RIKU0804/tetris-ai/commits/HEAD.atom` | 200 (1 commit, 2026-06-22) |
| `https://api.github.com/repos/RIKU0804/tetris-ai` | **403 rate limit** |

### Repo 2 — nevjin/ZetrisV2

| URL | Status |
|---|---|
| `https://api.github.com/repos/nevjin/ZetrisV2/git/trees/HEAD?recursive=1` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/LICENSE` | 200 (BSD-3-Clause) |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/README.md` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/client/main.py` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/src/TetrioBot.cs` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/src/UI.xaml.cs` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/src/Zetris.TETRIO.csproj` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/src/packages.config` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/Zetris/Bot.cs` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/Zetris/Zetris.csproj` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/Zetris.PPT/PPTBot.cs` | 200 |
| `https://raw.githubusercontent.com/nevjin/ZetrisV2/HEAD/src/Bot.cs` | **404** (file lives in `Zetris/`) |
| `https://github.com/nevjin/ZetrisV2/commits/HEAD.atom` | 200 (1 commit, 2025-05-17) |
| `https://api.github.com/repos/nevjin/ZetrisV2` | **403 rate limit** |

### Repo 3 — blockfish/blockfish

| URL | Status |
|---|---|
| `https://api.github.com/repos/blockfish/blockfish/git/trees/HEAD?recursive=1` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/LICENSE.txt` | 200 (LGPL-2.1) |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/README.md` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/Cargo.toml` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/support/guideline.json` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish.proto` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/block-stacker/src/ruleset.rs` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/block-stacker/src/stacker.rs` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish-engine/Cargo.toml` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish-engine/src/ai/eval.rs` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish-engine/src/place.rs` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish-engine/src/shape.rs` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish-engine/src/bin/service.rs` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish-python/blockfish/ai.py` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish-python/blockfish/ipc.py` | 200 |
| `https://raw.githubusercontent.com/blockfish/blockfish/HEAD/blockfish-js/src/ai.js` | 200 |
| `https://github.com/blockfish/blockfish/commits/HEAD.atom` | 200 (latest 2025-07-13) |
| `https://api.github.com/repos/blockfish/blockfish` | **403 rate limit** |

### Local reference used for SRS+ comparison

- `docs/RULESET.md` §3.3 (SRS+ I-kick ordering) — used to compare the audited tables; no external repo
  was fetched for this section.

---

## 8. Open questions ([UNKNOWN])

1. **Star counts / archived flags** for all three repos — REST metadata returned 403.
2. **Exact SRS+ and 180 tables inside `MisaMinoNET 1.9.3`** — prebuilt binary, not in the repository;
   cannot be source-verified.
3. **Blockfish's I-piece kick ordering vs SRS+** — its rotation numbering is non-canonical for `I`;
   not bit-compared. The file is labelled "guideline", so treat as guideline SRS.
4. **Whether `tetris-ai`'s Rust core has ever been built/tested on Linux** — no CI, no artifacts;
   inference from a zero-dependency portable tree only.
5. **Licensing of the bundled MisaMino/PerfectClear binaries** — no license file anywhere in the tree.
6. **Whether ZetrisV2 runs under Wine** — not attempted (and out of scope for this project's rules).
