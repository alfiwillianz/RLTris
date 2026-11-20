#!/usr/bin/env python3
"""Start the TetrisRL experiment dashboard on 0.0.0.0:8765."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.is_file() and Path(sys.executable).resolve() != venv_python.resolve():
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])

    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from tetrisrl.dashboard.server import main as server_main

    return server_main(["--host", "0.0.0.0", "--port", "8765", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
