"""R-49c: the tmux test harness must not leak processes past a killed session.

Machine-observed (not council-flagged): `pgrep -f pytest-of-user` found 75
orphaned wrapper-agent shell processes from four finished pytest runs, hours
after those runs ended, with no tmux session and no pytest process left
tracking them -- the most plausible cause of harness-matrix contention another
lane hit.

`tmux kill-session` sends SIGHUP to each pane's leader process and hopes it
(and anything it forked) dies. That is not a promise: a pane leader that
ignores or is slow to act on SIGHUP survives the session being torn down --
`tmux has-session` reports the session gone regardless, since that is tmux's
own bookkeeping, not evidence about the process. Confirmed directly: a pane
whose command is `trap '' HUP; sleep 300` survives a real `tmux kill-session`
untouched, reparented to PID 1, with no tmux session left pointing at it.

`TmuxHarness.kill_session` now captures every pane's PID (which is also its
process-group id -- tmux makes each pane's leader a new group leader) before
asking tmux to kill the session, then sends SIGTERM/SIGKILL to that group
directly afterward, independent of whether tmux's own signal delivery worked.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import ClassVar

import pytest

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from harness.tmux import TmuxHarness  # noqa: E402


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


class TestKillSessionReapsProcessesTmuxsOwnSignalMisses:
    # Class-scoped, not module-scoped: `TestKillProcessGroupsIsAQuietBackstop`
    # below needs neither tmux nor `-m integration` -- it exercises
    # `kill_process_groups` directly against a plain `subprocess.Popen`.
    pytestmark: ClassVar = [
        pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
        pytest.mark.integration,
    ]

    def test_a_pane_leader_that_ignores_sighup_is_still_reaped(self):
        """The exact failure mode this item fixes: a pane whose leader
        traps/ignores SIGHUP survives `tmux kill-session` on its own.
        `kill_session` must still reap it via the captured pgid.
        """
        tmux = TmuxHarness()
        session_name = f"r49c-test-{os.getpid()}"
        tmux._tmux("new-session", "-d", "-s", session_name, "trap '' HUP; sleep 300")
        try:
            pane_pid = int(tmux.list_panes(session_name)[0]["pid"])
            assert _pid_alive(pane_pid), "the pane's sleep process never started"

            tmux.kill_session(session_name)

            assert not tmux.session_exists(session_name), (
                "tmux still reports the session alive after kill_session"
            )
            assert not _pid_alive(pane_pid), (
                f"pid {pane_pid} (a pane leader that ignores SIGHUP) survived "
                "kill_session -- the same shape as the 75 orphaned wrapper-agent "
                "processes this item fixes"
            )
        finally:
            # Best-effort: if the assertion above failed, don't leave a real
            # sleep(300) running for the rest of this machine's day.
            tmux._tmux("kill-session", "-t", session_name)

    def test_a_well_behaved_pane_is_still_reaped_normally(self):
        """Regression guard: the common case (a pane that *does* die from
        SIGHUP on its own) must not regress -- kill_session must still
        report the session gone and leave no process behind.
        """
        tmux = TmuxHarness()
        session_name = f"r49c-test-normal-{os.getpid()}"
        tmux._tmux("new-session", "-d", "-s", session_name, "sleep 300")
        try:
            pane_pid = int(tmux.list_panes(session_name)[0]["pid"])
            assert _pid_alive(pane_pid)

            tmux.kill_session(session_name)

            assert not tmux.session_exists(session_name)
            assert not _pid_alive(pane_pid)
        finally:
            tmux._tmux("kill-session", "-t", session_name)


class TestKillProcessGroupsIsAQuietBackstop:
    """Fast, no-tmux-needed coverage of `kill_process_groups` itself."""

    def test_empty_list_is_a_no_op(self):
        TmuxHarness.kill_process_groups([])  # must not raise

    def test_an_already_dead_pgid_does_not_raise(self):
        # A pgid vanishingly unlikely to exist -- os.killpg must not blow up
        # a test teardown just because the thing it's cleaning up is already
        # gone (the common case: tmux's own signal delivery already worked).
        TmuxHarness.kill_process_groups([2**30])

    def test_kills_a_real_detached_process_group(self, tmp_path):
        import subprocess

        proc = subprocess.Popen(
            ["sleep", "300"],
            start_new_session=True,  # its own process group, like a pane leader
        )
        try:
            assert proc.poll() is None, "the sleep process never started"
            TmuxHarness.kill_process_groups([proc.pid])
            # kill_process_groups sleeps 0.3s between TERM and KILL itself.
            # `proc.poll()` (not a bare os.kill probe) both checks liveness
            # AND reaps the child once it exits -- this process is a direct
            # child of the test itself, so a killed-but-unreaped child is a
            # zombie: still a valid PID that a raw os.kill(pid, 0) probe
            # would report as "alive" until something calls wait()/poll().
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and proc.poll() is None:
                time.sleep(0.05)
            assert proc.poll() is not None, "process survived kill_process_groups"
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
