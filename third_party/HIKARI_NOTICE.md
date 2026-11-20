# Third-party notice: Hikari (Rust reimplementation, `hikari_rei`)

This project can use [hikari_rei](https://github.com/SoRA-X7/hikari_rei) as an
**optional external opponent**, launched as a separate subprocess. Its source is
**not** vendored into the `tetrisrl` Python package.

| Field | Value |
|---|---|
| Project | Hikari Rust (`SoRA-X7/hikari_rei`) |
| Author | SoRA_X7 (port author; original Hikari by the same author) |
| Upstream URL | https://github.com/SoRA-X7/hikari_rei |
| Pinned commit | `21b63c652f232d64016b2af72876d7a4b0e238fd` (2026-11-20, "Merge pull request #22 from SoRA-X7/feature/targeted-physical-path-search") |
| Ported from | GitLab `SoRA_X7/hikari` commit `90aef085a53d6048cbd19de7f4c9c53a6f3c8960` (reported by the upstream README and the binary's `info.reference_commit`) |
| License | **MIT** (`LICENSE`, "Copyright (c) 2026 Hikari Rei contributors") |
| License text | reproduced below; the clone keeps the upstream `LICENSE` file |
| Language / toolchain | Rust, edition 2024 (Rust ≥ 1.85); crates `clap`, `rayon`, `serde`, `serde_json`, pinned by `Cargo.lock` |
| Build | `cargo build --release` in the clone root |
| Build artifact | `hikari_rei/target/release/hikari_rei` (not committed) |
| SHA-256 of the binary built for `docs/integration_hikari.md` | `2f746bf37872cf13b63b9780dc4bfd171d08f3e32af296a3a59723704afde51d` |
| Binary size | 1,830,968 bytes |
| Engine self-report | `{"type":"info","name":"Hikari Rust","version":"0.2.0","author":"SoRA_X7","features":["randomizer","move_info"],"reference_commit":"90aef085a53d6048cbd19de7f4c9c53a6f3c8960"}` |

## How it is used

* `hikari_rei tbp --threads 1` speaks the Tetris Bot Protocol (JSON lines over
  stdin/stdout). It is a **placement suggester**: it receives a board, queue,
  hold, combo and back-to-back flag and answers where to put the current piece.
  It never receives attack, garbage, cancellation or surge state, and it does
  not decide any competitive rule.
* All match rules are adjudicated by `tetrisrl` (`environment/engine.py`,
  `environment/versus.py`, `environment/scoring.py`, `environment/garbage.py`).
* The adapter is `tetrisrl/agents/opponents/hikari.py`; the generic TBP
  transport is `tetrisrl/agents/opponents/tbp.py` (unmodified for this engine).
* Hikari's own versus rules (24-row board, its attack table, 60-frame garbage
  delays) are **not** used by this project.

## Redistribution notes

* The engine is MIT-licensed. Redistributing the compiled binary requires
  including the MIT copyright and permission notice; the text below satisfies
  that.
* `third_party/hikari_rei/` is a local clone + build tree and is gitignored
  (`.gitignore`: `third_party/*` with exceptions for `*.md` and `LICENSE-*`).
  Recreate it with the commands in `docs/integration_hikari.md`.
* No upstream source is copied, translated, or linked into the Python package.

## MIT license text (upstream `LICENSE`)

```
MIT License

Copyright (c) 2026 Hikari Rei contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
