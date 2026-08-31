"""Source-test helper coverage and proof it cannot become a product adapter."""

from __future__ import annotations

import importlib.util
import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _read_until(fd: int, needle: bytes, timeout: float = 5.0) -> bytes:
    buffer = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
        if needle in buffer:
            return buffer
    raise AssertionError(f"needle {needle!r} not seen; got: {buffer!r}")


def _helper_command(*args: str) -> list[str]:
    return [sys.executable, str(Path(__file__).with_name("_fake_agent.py")), *args]


class TestSourceTestAgent:
    def test_banner_echo_and_clean_exit(self) -> None:
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            _helper_command("/tmp/persona-ignored.md"),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        try:
            _read_until(master, b"FAKE-AGENT READY")
            os.write(master, b"what is a closure?\n")
            output = _read_until(master, b"FAKE-AGENT SAYS:")
            assert b"closure" in output
            os.write(master, b"exit\n")
            _read_until(master, b"FAKE-AGENT BYE")
            assert proc.wait(timeout=5) == 0
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()

    def test_sigterm_exits_zero(self) -> None:
        master, slave = pty.openpty()
        proc = subprocess.Popen(_helper_command(), stdin=slave, stdout=slave, close_fds=True)
        os.close(slave)
        try:
            _read_until(master, b"FAKE-AGENT READY")
            proc.terminate()
            assert proc.wait(timeout=5) == 0
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()


def test_no_product_fake_adapter_even_when_legacy_env_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from studyloop.adapters import registry

    assert importlib.util.find_spec("studyloop.adapters.fake") is None
    monkeypatch.setenv("STUDYLOOP_TEST_AGENT", "1")
    registry.reset_registry()
    try:
        assert "fake" not in registry.get_all_adapters()
    finally:
        registry.reset_registry()


def test_source_test_agent_main_is_importable() -> None:
    helper_path = Path(__file__).with_name("_fake_agent.py")
    spec = importlib.util.spec_from_file_location("studyloop_test_agent", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.main)


def test_source_test_agent_runs_as_module() -> None:
    proc = subprocess.run(
        _helper_command(),
        input="hi\nexit\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "FAKE-AGENT READY" in proc.stdout
    assert "FAKE-AGENT SAYS:" in proc.stdout
