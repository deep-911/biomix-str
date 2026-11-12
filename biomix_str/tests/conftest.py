"""Pytest fixtures and session lifecycle hooks."""

from __future__ import annotations

import atexit
import time
import pytest


def _cleanup_logs():
    """Clean up any stray Fluent transcript or log files left in working directories."""
    try:
        time.sleep(1.0)
        from biomix.fluent_runner import FluentSimulationRunner
        FluentSimulationRunner.cleanup_stray_fluent_logs()
    except Exception:
        pass


atexit.register(_cleanup_logs)


def pytest_sessionfinish(session, exitstatus):
    _cleanup_logs()
