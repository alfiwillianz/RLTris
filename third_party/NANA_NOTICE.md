# NANA — provenance, license and build identity

**Upstream:** [nightcrab/nana](https://github.com/nightcrab/nana) — a parallel
MCTS/TDS engine for versus Tetris with an explicit opponent model.

**Pinned commit:** `3cb49c6cc680f07282382de2862f1aa656d9afa1`
(2026-11-10, described by `git describe` as `v0.2.0-9-g3cb49c6`).
Cloned with `--recurse-submodules`; the SHA was reachable, so no fallback to
HEAD was needed.

**License:** MIT — `LICENSE`, "Copyright (c) 2026 Paul Anderson". The full
upstream MIT text is reproduced below.

**Submodule:** `cpp/Tetris/game/ShakTrisLib` →
[nightcrab/ShakTrisLib](https://github.com/Nightcrab/ShakTrisLib), pinned by
nana at `d8093fa9a592a3b5b2cc0daf1d9dde34a31bf49c` (branch `master`), also
MIT. Its `LICENSE.txt` still contains the placeholder
`Copyright (c) [year] [fullname]`; this is a legal-hygiene flag on the
upstream project, not a change made here, and it does not restrict use of
nana under its own MIT grant.

**Build-time dependency:** mimalloc `v3.5.4` is fetched by CMake
`FetchContent` at configure time (`cpp/CMakeLists.txt`; MIT license, see
`third_party/nana/build/_deps/mimalloc-src/LICENSE`). It is not vendored into
the Python package.

**No source is vendored into `tetrisrl`.** The clone lives at
`third_party/nana/` (gitignored: `.gitignore` has `third_party/*` with an
exception only for `*.md` and `LICENSE-*`). This notice is the committed
provenance record; the adapter is an independent Python subprocess client.

## Build identity (this machine)

```bash
git clone --recurse-submodules https://github.com/nightcrab/nana third_party/nana
git -C third_party/nana checkout 3cb49c6cc680f07282382de2862f1aa656d9afa1
git -C third_party/nana submodule update --init --recursive
# cmake was installed into the project venv because it was not on PATH:
#   uv pip install --python .venv/bin/python cmake   # cmake 4.4.5
/home/alfi/Active/tetrlio/.venv/bin/cmake -S third_party/nana -B third_party/nana/build \
    -DCMAKE_BUILD_TYPE=Release
/home/alfi/Active/tetrlio/.venv/bin/cmake --build third_party/nana/build -j
```

Result: exit code 0, `nana_tbp` built at
`third_party/nana/build/cpp/nana_tbp` (1,233,320 bytes). The default build also
produced `nana_interactive`, `nana_emulate`, `nana_bench`, `nana_speed`,
`nana_msgbench`, `nana_eval_dump`; X11/OpenGL/libpng were present, so
`NANA_GUI=OFF` was not needed.

Binary hash and handshake:

```text
$ sha256sum third_party/nana/build/cpp/nana_tbp
bcb1452666a391fc31e85c230bb166d6c4029c6ca5b40860bff12dd5987817ad
$ printf '%s\n' '{"type":"quit"}' | third_party/nana/build/cpp/nana_tbp
{"author":"Shakkar + Awyzza","features":["set_threads","set_thinks"],"name":"Nana","type":"info","version":"0.1"}
```

Minimal config written beside the executable (nana reads `nana.json` from
`executableDirectory()` in TBP mode; argv and `NANA_CONFIG` are ignored there):

```json
{
  "rules": "tetrio",
  "threads": 2
}
```

## How it is used

`tetrisrl/agents/opponents/nana.py` launches `nana_tbp` as a subprocess and
speaks **TBP2** (JSON lines) over stdin/stdout. nana is a **placement
suggester only**: `tetrisrl.environment.versus` / `engine.py` remain the sole
authority for attack, garbage, cancellation, B2B charging, surge, spin
classification and top-out. See `docs/integration_nana.md` for the protocol
quirks, results and limitations.

## Upstream MIT license text

```text
MIT License

Copyright (c) 2026 Paul Anderson

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
