# Third-party notice: RIKU0804/tetris-ai

This project can use [RIKU0804/tetris-ai](https://github.com/RIKU0804/tetris-ai)
as an **optional external opponent**, launched as a separate subprocess over the
Tetris Bot Protocol. Its source is **not** vendored into the `tetrisrl` Python
package.

| Field | Value |
|---|---|
| Project | RIKU0804/tetris-ai (`RIKU0804/tetris-ai`) |
| Author | riku |
| Upstream URL | https://github.com/RIKU0804/tetris-ai |
| Pinned commit | `d3f92d289a24e09ec72679d8ce653bfd8a98679e` (2026-06-22, "feat: Tetris AI — Rust core, beam-search AI, versus training, TBP") |
| License | **MIT** (Copyright (c) 2026 riku) |
| Build artifact | `riku-tetris-ai/core-rs/target/release/tetris-core` (not committed) |
| SHA-256 of the binary built for `docs/integration_riku.md` | `bcee2640f8e1e07383ef64008b12835f1e4271dfbe2a6226c06f2156f2f17db3` |
| Adapter | `tetrisrl/agents/opponents/riku.py` |
| Integration document | `docs/integration_riku.md` |

## Licence text (copied verbatim from `LICENSE` at the pinned commit)

```
MIT License

Copyright (c) 2026 riku

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

## Redistribution notes

* `tetrisrl` is not distributed with RIKU0804/tetris-ai source or binaries. It
  launches a locally built `tetris-core` as a separate process speaking JSON
  lines over stdin/stdout and contains only our own adapter code
  (`tetrisrl/agents/opponents/riku.py`). No upstream source is copied,
  translated, or linked into the package.
* If you redistribute a compiled `tetris-core`, include the MIT licence text
  above, which is that project's only licence obligation.
* `third_party/riku-tetris-ai/` is a local clone + build tree and **must not be
  committed**. Unlike `third_party/cold-clear-2/`, the repository's
  `.gitignore` does not yet list it: either add `third_party/riku-tetris-ai/`
  (or `third_party/`) to `.gitignore`, or keep it out of commits manually.
  This notice and `docs/integration_riku.md` are the files that should be
  committed.
* Recreate the clone and the binary with the commands in
  `docs/integration_riku.md` §2 and §9.
