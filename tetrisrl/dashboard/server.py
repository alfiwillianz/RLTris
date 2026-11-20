"""Run the TetrisRL dashboard backend.

Usage::

    python -m tetrisrl dashboard                 # from the project CLI
    python -m tetrisrl.dashboard.server --dev    # direct module entry point

The React SPA is served from ``tetrisrl/dashboard/static``.  In dev mode the
backend reloads on Python changes and prints the Vite dev-server instructions;
Vite proxies ``/api`` and ``/ws`` to this process.
"""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from typing import Optional, Sequence

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def run_dashboard(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = False,
    dev: bool = False,
    db_path: Optional[str] = None,
) -> None:
    """Start the dashboard with uvicorn (blocking) and return ``None``.

    ``db_path`` is an optional extension used by ``python -m tetrisrl dashboard
    --db PATH``; the documented signature (host, port, open_browser, dev) is
    preserved.
    """
    import uvicorn

    from .backend.app import create_app, STATIC_DIR

    if db_path:
        os.environ["TETRISRL_DB"] = str(db_path)
    url = f"http://{host}:{port}"
    if dev:
        print("TetrisRL dashboard (dev mode)")
        print(f"  API:     {url}/api/health")
        print("  For hot-reloading UI, run in another terminal:")
        print("    cd tetrisrl/dashboard/frontend && npm run dev")
        print("  Vite serves http://localhost:5173 and proxies /api + /ws here.")
        print("  (Built assets in tetrisrl/dashboard/static are still served here.)")
    else:
        print(f"TetrisRL dashboard: {url}")

    if not (STATIC_DIR / "index.html").is_file():
        print("  Frontend build not found. Build it with:")
        print("    cd tetrisrl/dashboard/frontend && npm install && npm run build")
        print("  The API is available immediately at /api/health and /docs.")

    if open_browser:
        timer = threading.Timer(1.0, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()

    if dev:
        # Reload on Python changes; the factory reads TETRISRL_DB from the env.
        uvicorn.run(
            "tetrisrl.dashboard.backend.app:create_app",
            factory=True,
            host=host,
            port=port,
            reload=True,
            log_level="info",
        )
    else:
        uvicorn.run(create_app(db_path), host=host, port=port, log_level="info")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the TetrisRL dashboard backend.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (default 8000)")
    parser.add_argument("--dev", action="store_true", help="dev mode: reload + Vite dev-server instructions")
    parser.add_argument("--open", action="store_true", help="open the dashboard in a browser")
    parser.add_argument("--db", default=None, help="SQLite database path (default: TETRISRL_DB or results/tetrisrl.sqlite3)")
    args = parser.parse_args(argv)
    run_dashboard(host=args.host, port=args.port, open_browser=args.open, dev=args.dev, db_path=args.db)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
