# Frostetra — vendored upstream notice

This directory contains an unmodified local clone and release build of
[frostetra](https://github.com/ruelalarcon/frostetra), used as an external
placement-suggestion opponent for the TetrisRL arena. It is not linked into any
TetrisRL source file; it is launched as a subprocess and spoken to over SBP/1
(JSON lines on stdin/stdout). The Python adapter
(`tetrisrl/agents/opponents/frostetra.py`) is an independent implementation of
the protocol's field semantics and contains no upstream source.

## Pin

| Field | Value |
|---|---|
| Repository | https://github.com/ruelalarcon/frostetra |
| Commit | `b92dc7606414776eb2bf2dfc67cb3119b41338ea` |
| Commit date | 2026-11-03 |
| Commit subject | `Revert "Implement garbage pressure"` |
| Version | `0.1.0` (binary reports `0.1.0 b92dc76`) |
| Crate | `frostetra`, Rust 2021 |
| Licence | **MIT** (`LICENSE.txt`, retained in this directory) |

The clone was made with:

```bash
git clone https://github.com/ruelalarcon/frostetra third_party/frostetra
git -C third_party/frostetra checkout b92dc7606414776eb2bf2dfc67cb3119b41338ea
```

No source file was modified. The clone is a build tree (it is ignored by the
repository's `.gitignore`); the `LICENSE.txt` and this notice are the
distributed attribution.

## Licence

Frostetra is a derivative of [Cold Clear 2](https://github.com/MinusKelvin/cold-clear-2)
by Mark Carlson and is distributed under the MIT License:

```text
MIT License

Copyright (c) 2021 Mark Carlson
Copyright (c) 2026 Ruel Nathaniel Alarcon
```

The full MIT text is retained verbatim in
[`third_party/frostetra/LICENSE.txt`](frostetra/LICENSE.txt). Its permission
notice requires that the copyright notice and permission notice be included in
all copies or substantial portions of the Software; that is why the upstream
clone and this notice are kept in the repository alongside the adapter.

## Build

```bash
cd third_party/frostetra
cargo build --release
# -> target/release/frostetra
```

Build machine: Rust/Cargo 1.100.0 (2026-11-09), Linux x86_64. Result:
success, warnings only (`unused dependency enum_dispatch`). Binary SHA-256 at
build time: `e4324d0eeaca994258d0415d01e390dc09b8956ab3c28a1b0a181752f8e87394`.

Override the binary location for the adapter with
`TETRISRL_FROSTETRA_BIN=/path/to/frostetra`. See
`docs/integration_frostetra.md` for the protocol dialect, limitations and
measured match results.
