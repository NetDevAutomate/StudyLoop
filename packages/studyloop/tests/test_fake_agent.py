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


def test_practice_check_sentinel_matches_the_product() -> None:
    """The helper spells the sentinel out rather than importing the product; pin them equal
    so a renamed sentinel cannot silently turn delivered results back into graded answers."""
    from studyloop.session.module_delivery import BEGIN_SENTINEL

    helper_path = Path(__file__).with_name("_fake_agent.py")
    spec = importlib.util.spec_from_file_location("studyloop_test_agent_pin", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert BEGIN_SENTINEL.startswith(module.PRACTICE_CHECK_SENTINEL)


class TestDeliveredPracticeCheckIsNotAnAnswer:
    """A practice_check block posted into the session by the product (one printable line,
    M0 Q3 fallback) is acknowledged and never graded -- the open question stays open and
    the agent stays alive. Red before 2026-10-12: the generic bank's keyword grader accepted
    the block, printed DONE and exited, ending the session the Labs journey still needed."""

    @staticmethod
    def _block() -> bytes:
        from studyloop.session.module_delivery import BEGIN_SENTINEL, END_SENTINEL

        inner = "drill: echo-drills/echo-basics/echo-01 exit: passed (code 0) so it means when"
        return f"{BEGIN_SENTINEL} {inner} {END_SENTINEL}\n".encode()

    def test_socratic_mode_notes_the_block_and_keeps_the_question_open(
        self, tmp_path: Path
    ) -> None:
        persona = tmp_path / "persona.md"
        persona.write_text("**Topic:** Lab: echo-drills/echo-basics/echo-01\n", encoding="utf-8")
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            _helper_command(str(persona)),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        try:
            _read_until(master, b"FAKE-AGENT ASKS:")
            os.write(master, self._block())
            noted = _read_until(master, b"FAKE-AGENT NOTED: practice_check result received")
            assert b"VERDICT" not in noted and b"FAKE-AGENT DONE" not in noted
            assert proc.poll() is None, "the agent exited on a delivered result"
            # The learner's own answer is still what closes the question.
            os.write(master, b"it is a lab because I know the echo part\n")
            closing = _read_until(master, b"FAKE-AGENT BYE")
            assert b"FAKE-AGENT VERDICT: correct" in closing
            assert b"FAKE-AGENT DONE: 1/1" in closing
            assert proc.wait(timeout=5) == 0
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()

    def test_echo_mode_notes_the_block_instead_of_echoing_it(self) -> None:
        proc = subprocess.run(
            _helper_command(),
            input=self._block().decode() + "exit\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert "FAKE-AGENT NOTED: practice_check result received" in proc.stdout
        assert "I hear you on" not in proc.stdout
