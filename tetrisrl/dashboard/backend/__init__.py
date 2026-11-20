"""Dashboard backend package.

Public entry points:
    ``create_app``   FastAPI application factory
    ``JobManager``   training subprocess supervisor
    ``DashboardDB``  ExperimentManager-backed persistence wrapper
"""

from .app import BroadcastBus, create_app
from .db import DashboardDB, downsample_series
from .jobs import JobManager, pid_alive

__all__ = [
    "BroadcastBus",
    "DashboardDB",
    "JobManager",
    "create_app",
    "downsample_series",
    "pid_alive",
]
