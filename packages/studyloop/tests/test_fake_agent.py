"""Fake harness agent — binary behaviour + adapter gating.

The fake agent exists so the e2e journey can walk the real
spawn → PTY → WS → terminal path without an LLM. These unit tests pin:
- the echo contract (banner, reply, clean exit) over a REAL pty
- the registry gate: 'fake' registers ONLY under STUDYLOOP_TEST_AGENT=1
"""

from __future__ import annotations

import os
import pty
import select
import shutil
import subprocess
import sys
import time

import pytest


def _read_until(fd: int, needle: bytes, timeout: float = 5.0) -> bytes:
    """Read from *fd* until *needle* appears or *timeout* elapses."""
    buf = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.2)
        if not r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:  # EIO on child exit — pty semantics
            break
        if not chunk:
            break
        buf += chunk
        if needle in buf:
            return buf
    raise AssertionError(f"needle {needle!r} not seen; got: {buf!r}")


class TestFakeAgentBinary:
    """Drive the real console script under a real pty."""

    @pytest.fixture()
    def agent_bin(self) -> str:
        binary = shutil.which("studyloop-fake-agent")
        if not binary:
            pytest.skip("studyloop-fake-agent not installed (editable install needed)")
        return binary

    def test_banner_echo_and_clean_exit(self, agent_bin: str) -> None:
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            [agent_bin, "/tmp/persona-ignored.md"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        try:
            _read_until(master, b"FAKE-AGENT READY")
            os.write(master, b"what is a closure?\n")
            out = _read_until(master, b"FAKE-AGENT SAYS:")
            assert b"closure" in out
            os.write(master, b"exit\n")
            _read_until(master, b"FAKE-AGENT BYE")
            assert proc.wait(timeout=5) == 0
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()

    def test_sigterm_exits_zero(self, agent_bin: str) -> None:
        master, slave = pty.openpty()
        proc = subprocess.Popen([agent_bin], stdin=slave, stdout=slave, close_fds=True)
        os.close(slave)
        try:
            _read_until(master, b"FAKE-AGENT READY")
            proc.terminate()
            assert proc.wait(timeout=5) == 0
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()


class TestFakeAdapterGating:
    """'fake' must exist ONLY when STUDYLOOP_TEST_AGENT=1."""

    def _fresh_registry(self, monkeypatch: pytest.MonkeyPatch, enabled: bool) -> dict:
        import importlib

        import studyloop.adapters.fake as fake_mod
        from studyloop.adapters import registry

        if enabled:
            monkeypatch.setenv("STUDYLOOP_TEST_AGENT", "1")
        else:
            monkeypatch.delenv("STUDYLOOP_TEST_AGENT", raising=False)
        importlib.reload(fake_mod)  # ADAPTER is computed at import time
        registry.reset_registry()
        try:
            return dict(registry.get_all_adapters())
        finally:
            # Leave the module + registry in the ambient-env state for other tests.
            importlib.reload(fake_mod)
            registry.reset_registry()

    def test_absent_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapters = self._fresh_registry(monkeypatch, enabled=False)
        assert "fake" not in adapters

    def test_present_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapters = self._fresh_registry(monkeypatch, enabled=True)
        assert "fake" in adapters
        assert adapters["fake"].binary == "studyloop-fake-agent"

    def test_launch_cmd_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from pathlib import Path

        monkeypatch.setenv("STUDYLOOP_TEST_AGENT", "1")
        import importlib

        import studyloop.adapters.fake as fake_mod

        importlib.reload(fake_mod)
        try:
            assert fake_mod.ADAPTER is not None
            cmd = fake_mod.ADAPTER.launch_cmd(Path("/tmp/p.md"), False)
            assert "studyloop-fake-agent" in cmd
            assert "/tmp/p.md" in cmd
        finally:
            monkeypatch.delenv("STUDYLOOP_TEST_AGENT", raising=False)
            importlib.reload(fake_mod)


def test_fake_agent_main_is_importable() -> None:
    """The console-script target imports and exposes main()."""
    from studyloop.testing.fake_agent import main

    assert callable(main)


def test_fake_agent_module_runs_via_python_dash_m() -> None:
    """python -m fallback works even without the console script installed."""
    proc = subprocess.run(
        [sys.executable, "-m", "studyloop.testing.fake_agent"],
        input="hi\nexit\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "FAKE-AGENT READY" in proc.stdout
    assert "FAKE-AGENT SAYS:" in proc.stdout
