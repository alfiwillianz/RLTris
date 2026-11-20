"""Training-process supervisor for the dashboard.

The dashboard never trains in-process.  ``POST /api/runs`` spawns::

    python -m tetrisrl train --algorithm ... --run-id ... --config ...

and this module owns the ``Popen`` handles.  The database remains the source of
truth: every state transition is written through ``ExperimentManager``.  A
dashboard restart therefore loses nothing but the in-memory handles, and
``recover_orphans()`` marks runs whose recorded PID is dead as ``stale``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .db import ExperimentManager, utcnow


def _package_root() -> Path:
    """Best guess at the source checkout root (works for editable installs)."""
    root = Path(__file__).resolve().parents[3]
    if (root / "tetrisrl").is_dir():
        return root
    return Path.cwd()


def project_root() -> Path:
    return _package_root()


def results_root() -> Path:
    """Root for large artifacts (checkpoints, replays, configs, logs).

    ``TETRISRL_RESULTS_DIR`` is a dashboard extension used by tests and by
    deployments that keep artifacts outside the checkout.
    """
    override = os.environ.get("TETRISRL_RESULTS_DIR")
    root = Path(override).expanduser().resolve() if override else (project_root() / "results")
    root.mkdir(parents=True, exist_ok=True)
    return root


def pid_alive(pid: Optional[int]) -> bool:
    """Liveness check that never raises and never reaps the process."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but owned by another user.
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


class JobManager:
    """Thread-safe supervisor for training subprocesses keyed by run id."""

    def __init__(
        self,
        manager: ExperimentManager,
        artifacts_root: Optional[Path | str] = None,
        cwd: Optional[Path | str] = None,
    ) -> None:
        self.manager = manager
        self.results_root = Path(artifacts_root) if artifacts_root else results_root()
        self.cwd = str(cwd) if cwd else str(project_root())
        self._lock = threading.RLock()
        self._processes: Dict[str, subprocess.Popen[Any]] = {}
        self._stop_requested: set[str] = set()
        self._logs: Dict[str, str] = {}

    # -- introspection -----------------------------------------------------
    def is_running(self, run_id: str) -> bool:
        with self._lock:
            proc = self._processes.get(run_id)
            return bool(proc is not None and proc.poll() is None)

    def tracked(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._processes

    def pid(self, run_id: str) -> Optional[int]:
        with self._lock:
            proc = self._processes.get(run_id)
            return proc.pid if proc is not None and proc.poll() is None else None

    def running_runs(self) -> List[str]:
        with self._lock:
            return [rid for rid, proc in self._processes.items() if proc.poll() is None]

    def log_path(self, run_id: str) -> Path:
        path = self.results_root / "runs" / run_id / "train.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # -- lifecycle ---------------------------------------------------------
    def start(
        self,
        run_id: str,
        argv: Sequence[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> int:
        """Spawn ``argv`` for ``run_id`` and mark the run as running."""
        with self._lock:
            existing = self._processes.get(run_id)
            if existing is not None and existing.poll() is None:
                return existing.pid
            self._stop_requested.discard(run_id)

            log_path = self.log_path(run_id)
            log = open(log_path, "a", encoding="utf-8", buffering=1)
            try:
                proc = subprocess.Popen(
                    list(argv),
                    cwd=cwd or self.cwd,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=False,
                )
            except Exception:
                log.close()
                raise
            finally:
                # The child inherited the descriptor; the parent's copy is no
                # longer needed (relevant on platforms with ref-counted fds).
                try:
                    log.close()
                except Exception:
                    pass
            self._processes[run_id] = proc
            self._logs[run_id] = str(log_path)

        # DB writes are outside the lock: sqlite has its own (short) lock and
        # holding ours would serialise unrelated requests.
        try:
            self.manager.set_status(run_id, "running", error=None)
            self.manager.update_run(run_id, pid=proc.pid)
        except Exception:
            # A DB failure must not orphan the child silently; keep tracking it.
            pass
        watcher = threading.Thread(
            target=self._watch,
            args=(run_id, proc),
            name=f"tetrisrl-job-{run_id}",
            daemon=True,
        )
        watcher.start()
        return proc.pid

    def stop(self, run_id: str, grace: float = 5.0) -> Dict[str, Any]:
        """Terminate the tracked process (SIGTERM, then SIGKILL) and mark stopped."""
        with self._lock:
            self._stop_requested.add(run_id)
            proc = self._processes.get(run_id)
            self._processes.pop(run_id, None)

        was_running = False
        if proc is not None and proc.poll() is None:
            was_running = True
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:  # pragma: no cover
                        pass
            except Exception:
                pass

        try:
            self.manager.set_status(run_id, "stopped")
            self.manager.update_run(run_id, pid=None)
        except Exception:
            pass
        return {
            "run_id": run_id,
            "was_running": was_running,
            "returncode": proc.returncode if proc is not None else None,
            "stopped_at": utcnow(),
        }

    def shutdown(self, terminate: bool = False) -> None:
        """Optionally stop every tracked child (used by tests / dev)."""
        if not terminate:
            return
        with self._lock:
            run_ids = list(self._processes.keys())
        for run_id in run_ids:
            self.stop(run_id)

    # -- orphan recovery ---------------------------------------------------
    def recover_orphans(self) -> List[str]:
        """Mark runs left ``running``/``starting`` by a dead process as stale."""
        stale: List[str] = []
        try:
            runs = self.manager.list_runs(limit=None)
        except Exception:
            return stale
        for run in runs:
            if run.get("status") not in ("running", "starting"):
                continue
            pid = run.get("pid")
            if pid_alive(pid):
                continue
            try:
                self.manager.set_status(
                    run["id"],
                    "stale",
                    error="dashboard restarted: no live training process for this run",
                )
                self.manager.update_run(run["id"], pid=None)
            except Exception:
                continue
            stale.append(run["id"])
        return stale

    # -- internal ----------------------------------------------------------
    def _watch(self, run_id: str, proc: subprocess.Popen[Any]) -> None:
        returncode = proc.wait()
        with self._lock:
            current = self._processes.get(run_id)
            if current is proc:
                self._processes.pop(run_id, None)
            stop_requested = run_id in self._stop_requested
        if stop_requested:
            try:
                self.manager.set_status(run_id, "stopped")
                self.manager.update_run(run_id, pid=None)
            except Exception:
                pass
            return
        try:
            run = self.manager.get_run(run_id)
        except Exception:
            return
        if run is None or run.get("status") in ("completed", "failed", "stopped", "stale"):
            return
        log_path = self._logs.get(run_id, str(self.log_path(run_id)))
        try:
            if returncode == 0:
                self.manager.set_status(run_id, "completed")
            else:
                self.manager.set_status(
                    run_id,
                    "failed",
                    error=f"training process exited with code {returncode}; see {log_path}",
                )
            self.manager.update_run(run_id, pid=None)
        except Exception:
            pass


__all__ = ["JobManager", "pid_alive", "project_root", "results_root"]
