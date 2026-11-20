# Third-party notice: blockfish

This project can use [blockfish](https://github.com/blockfish/blockfish) as an
**optional external cheese/downstacking specialist**, launched as a separate
subprocess. Its source is **not** vendored into the `tetrisrl` Python package.

| Field | Value |
|---|---|
| Project | blockfish (`blockfish/blockfish`) |
| Authors | iitalics and mystery (as declared in `blockfish-engine/Cargo.toml`) |
| Upstream URL | https://github.com/blockfish/blockfish |
| Pinned commit | `739953f9331b7648f269fc52cff5aae330108ccd` (2025-07-13, "Merge pull request #11 from yaahc/rate-last-move") |
| License | **LGPL-2.1** (GNU Lesser General Public License, version 2.1; no "or later" clause) |
| License text | [`blockfish/LICENSE.txt`](blockfish/LICENSE.txt) (retained from the upstream clone) |
| Build artifact | `blockfish/target/release/blockfish` (not committed) |
| Build command | `cargo build --release -p blockfish --features service` (needs `protoc`) |
| SHA-256 of the binary built for `docs/integration_blockfish.md` | `b564d61775268b955ed5a6baae3dd16e2c1cd965dab197be46075d82a3c803cb` |

## Redistribution notes

* blockfish is licensed under **LGPL-2.1**. The upstream `LICENSE.txt` is kept
  in the clone at `third_party/blockfish/LICENSE.txt`; any redistribution of
  the built binary must include that license text and the upstream copyright
  notice.
* The `tetrisrl` Python package contains only our own adapter code
  (`tetrisrl/agents/opponents/blockfish.py`). No blockfish source is copied,
  translated, linked, or otherwise embedded. The engine runs as a separate
  process speaking its own protobuf-over-stdin/stdout service protocol
  (`blockfish-engine/src/bin/service.rs`); the subprocess boundary is the
  LGPL compliance mechanism. The protobuf *wire format* is a public interface
  description (`blockfish.proto`); our encoder/decoder is written from that
  interface and does not copy the engine implementation.
* If you distribute a build that includes blockfish, satisfy LGPL-2.1 §6 by
  including `LICENSE.txt` and making the corresponding blockfish source
  available (the pinned upstream commit above is sufficient).
* `third_party/blockfish/` is a local clone + build tree. `.gitignore` ignores
  `third_party/*` except `*.md` and `LICENSE-*`, so this notice is tracked but
  the clone and its 100+ MB `target/` directory are not. Recreate it with the
  commands in `docs/integration_blockfish.md`.

## Scope warning

blockfish is a **cheese-race / downstacking specialist**. It has no versus
model, no attack, no B2B charging, no Surge, no spin detection, no 180-degree
rotation and no TETR.IO Season 2 mechanics. Its match results must never be
presented as a competitive versus benchmark; `BlockfishAgent.specialist` is
`"cheese"` and `BlockfishAgent.is_versus_benchmark` is `False` to keep that
label explicit in code.
