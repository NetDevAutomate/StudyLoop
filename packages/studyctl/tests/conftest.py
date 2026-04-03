"""Shared test fixtures — session-scoped cleanup to prevent process leaks."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess

import pytest


@pytest.fixture(autouse=True, scope="session")
def _kill_orphans_on_exit():
    """Safety net: kill orphaned sidebar and mock-agent processes after all tests.

    Integration tests spawn tmux sessions with sidebar and agent subprocesses.
    If a test fails or times out, cleanup may not run, leaving orphaned processes
    that consume ptys and file descriptors. This fixture runs once at suite exit
    to catch anything that escaped.
    """
    yield
    for pattern in ("studyctl.tui.sidebar", "mock-agent"):
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                check=False,
            )
            for pid_str in result.stdout.strip().splitlines():
                with contextlib.suppress(OSError, ValueError):
                    os.kill(int(pid_str), signal.SIGTERM)
        except Exception:
            pass
