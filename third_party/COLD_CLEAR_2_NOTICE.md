# Third-party notice: Cold Clear 2

This project can use [Cold Clear 2](https://github.com/MinusKelvin/cold-clear-2)
as an **optional external opponent**, launched as a separate subprocess. Its
source is **not** vendored into the `tetrisrl` Python package.

| Field | Value |
|---|---|
| Project | Cold Clear 2 (`MinusKelvin/cold-clear-2`) |
| Author | MinusKelvin |
| Upstream URL | https://github.com/MinusKelvin/cold-clear-2 |
| Pinned commit | `ed8b19327b6bd1410ddd873d8611485bd45d8fae` (2022-06-29, "improve move generation performance") |
| License | **MIT OR Apache-2.0**, at your option |
| License texts | [`LICENSE-cold-clear-2-MIT`](LICENSE-cold-clear-2-MIT), [`LICENSE-cold-clear-2-APACHE-2.0`](LICENSE-cold-clear-2-APACHE-2.0) (copies of the upstream files) |
| Build artifact | `cold-clear-2/target/release/cold-clear-2` (not committed) |
| SHA-256 of the binary built for `docs/BENCHMARKS_INTEGRATION.md` | `656af2b8d14fc1562d6769c9d03423f18747e3786126eacb05f1a4c32c47c7cd` |

## Redistribution notes

* Cold Clear 2 is dual-licensed MIT / Apache-2.0. Redistributing the compiled
  binary requires including the applicable license text and copyright notice.
  The copies in this directory satisfy that for either option.
* The `tetrisrl` Python package contains only our own adapter code
  (`tetrisrl/agents/opponents/tbp.py`). No Cold Clear 2 source is copied,
  translated, or linked into the package; the engine runs as a separate process
  speaking JSON lines over stdin/stdout.
* `third_party/cold-clear-2/` is a local clone + build tree. It should be
  treated as a build artifact (add `third_party/` to `.gitignore` or commit only
  this notice and the license files). Recreate it with the commands in
  `docs/BENCHMARKS_INTEGRATION.md`.
