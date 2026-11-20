# Third-party notice: Cold Clear (original)

This project uses [Cold Clear](https://github.com/MinusKelvin/cold-clear) as an
**optional external opponent**, loaded at runtime as a shared library through
its own C ABI. Its source is **not** vendored into the `tetrisrl` Python
package, and no Cold Clear source file has been copied, translated, or
relicensed into this repository.

| Field | Value |
|---|---|
| Project | Cold Clear (`MinusKelvin/cold-clear`) |
| Author | MinusKelvin |
| Upstream URL | https://github.com/MinusKelvin/cold-clear |
| Pinned commit | `279edd7c3177ff8077f6a930193397814b281f27` (2022-01-18, "don't count long moves that are part of tspin doubles") |
| License | **Mozilla Public License 2.0 (MPL-2.0)** |
| License text | The upstream `LICENSE` file in the clone at `third_party/cold-clear/LICENSE`; upstream URL: https://github.com/MinusKelvin/cold-clear/blob/master/LICENSE |
| Build command | `cargo build --release -p c-api` (run inside `third_party/cold-clear`) |
| Build artifact | `third_party/cold-clear/target/release/libcold_clear.so` (not committed) |
| SHA-256 of the library built for `docs/integration_coldclear1.md` | `189bf1233b60de12b6553dcf914907c77a16f4fa01e28a5d7c25059953753892` |
| Adapter | `tetrisrl/agents/opponents/coldclear1.py` (our code, not upstream code) |

## Integration mode and MPL-2.0 obligations

* Integration is **dynamic linking at runtime** via Python `ctypes`:
  `ctypes.CDLL("libcold_clear.so")`. The library is a separate, unmodified
  build of the upstream `c-api` crate.
* The clone under `third_party/cold-clear/` is kept at the pinned commit and is
  **unmodified**. It is a local build tree, not a vendored source dependency of
  the Python package.
* MPL-2.0 is file-scoped copyleft. Under §3.3, distributing a "Larger Work"
  that links the library is permitted under other terms, provided the MPL
  Source Code Form and notices for the MPL-covered files are made available.
  Accordingly:
  * no MPL-covered file is copied into a `tetrisrl` source file;
  * the upstream `LICENSE` and this provenance notice are retained;
  * anyone redistributing the compiled library must also make the corresponding
    Cold Clear source available (the pinned upstream commit above is the
    Source Code Form; build it with the command above).
* If the clone is ever modified locally, the modified MPL files must remain
  MPL-2.0 and their source must be published. The adapter does not require any
  patches: the library built from the pinned commit without changes.

## Rebuild

```bash
cd /home/alfi/Active/tetrlio
git clone https://github.com/MinusKelvin/cold-clear third_party/cold-clear
git -C third_party/cold-clear checkout 279edd7c3177ff8077f6a930193397814b281f27
(cd third_party/cold-clear && cargo build --release -p c-api)
```

The clone/build tree is a build artifact (compare
`third_party/cold-clear-2/`, which is ignored by `.gitignore`). Commit this
notice, not the upstream source tree or the compiled `.so`.
