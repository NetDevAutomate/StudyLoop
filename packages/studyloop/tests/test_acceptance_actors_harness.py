"""HarnessActor: tmux plumbing, argv-mocked -- no real tmux in this file.

Per the lane's binding TEST SHAPE rule: "subprocess calls to external CLIs
are asserted by argv via a patched runner, never executed for real in unit
tests (opt-in integration/acceptance-marked tests may run real binaries
when present)". The REAL-tmux, real-mock-'sh'-harness proof lives in
test_acceptance_actors_harness_integration.py, marked ``integration`` and
skipped cleanly when tmux is absent -- same split ``test_tmux.py`` (mocked)
vs ``test_herdr_integration.py`` (real, marked, skip-guarded) already
uses in this repo.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.actors.budget import BudgetGuard  # noqa: E402
from acceptance.actors.harness import (  # noqa: E402
    DONE_SENTINEL,
    ENV_COMMAND,
    HarnessActor,
    HarnessActorError,
    max_socket_dir_length,
)
from acceptance.actors.protocol import ActorError, TerminationOutcome, TokenUsage  # noqa: E402


@pytest.fixture
def socket_dir() -> Generator[Path, None, None]:
    """A SHORT-path socket directory, swept on exit.

    Even a fully mocked test uses a realistic path: ``HarnessActor`` refuses
    a ``socket_dir`` no unix socket could ever live under (see
    ``max_socket_dir_length``), and pytest's own ``tmp_path`` exceeds that
    limit. Using ``tmp_path`` here would test a configuration the real
    thing rejects.
    """
    root = Path(tempfile.mkdtemp(prefix="sl-b3u-", dir="/tmp"))
    try:
        yield root / "sock"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _ok(stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str = "boom") -> SimpleNamespace:
    return SimpleNamespace(returncode=1, stdout="", stderr=stderr)


class EchoMentor:
    def __init__(self) -> None:
        self.received: list[str] = []

    async def send(self, message: str) -> str:
        self.received.append(message)
        return f"mentor said: {message}"


class MultiLineMentor:
    """A mentor whose reply spans more than one line -- any normal
    LLM/tutor answer, and exactly the case the module docstring's
    "long lines wrapping" note does NOT cover: this is about tmux echoing
    an embedded newline in ``send-keys`` text as SEPARATE pane lines, not
    about a single long line wrapping."""

    async def send(self, message: str) -> str:
        assert message  # never empty; the reply itself is what matters here
        return "line one\nline two"


class ParagraphBreakMentor:
    """A mentor whose reply has a BLANK line in the middle -- an ordinary
    paragraph break, the common shape of a real tutoring reply. Real tmux
    still echoes the blank line as its own (empty) pane line, but
    ``capture-pane`` output is filtered to non-blank lines only, so that
    echoed blank line never appears in what ``_capture()`` returns and must
    never be queued as something the reader waits to see."""

    async def send(self, message: str) -> str:
        assert message
        return "para one\n\npara two"


class TestFromEnv:
    def test_missing_command_names_the_env_var(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/tmux")
        with pytest.raises(ActorError) as exc:
            HarnessActor.from_env({}, socket_dir=socket_dir)
        assert ENV_COMMAND in str(exc.value)

    def test_missing_tmux_binary_raises_actor_error(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: None)
        with pytest.raises(ActorError, match="tmux"):
            HarnessActor.from_env({ENV_COMMAND: "sh /tmp/mock.sh"}, socket_dir=socket_dir)

    def test_parses_command_from_env_via_shlex(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/tmux")
        actor = HarnessActor.from_env(
            {ENV_COMMAND: "sh '/path/with spaces/mock.sh'"}, socket_dir=socket_dir
        )
        assert actor.command == ("sh", "/path/with spaces/mock.sh")

    def test_explicit_harness_command_overrides_env(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/tmux")
        actor = HarnessActor.from_env(
            {ENV_COMMAND: "ignored"},
            socket_dir=socket_dir,
            harness_command=("python3", "-c", "pass"),
        )
        assert actor.command == ("python3", "-c", "pass")


class TestTmuxArgvShape:
    def test_ensure_started_uses_dedicated_socket_env(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        calls: list[dict] = []

        def fake_run(argv, *, env, **kwargs):
            calls.append({"argv": argv, "env": env})
            return _ok()

        monkeypatch.setattr("acceptance.actors.harness.subprocess.run", fake_run)
        actor = HarnessActor(command=("sh",), socket_dir=socket_dir)

        actor._ensure_started()

        assert len(calls) == 1
        argv, env = calls[0]["argv"], calls[0]["env"]
        assert argv[0] == "tmux"
        assert "new-session" in argv
        assert env["TMUX_TMPDIR"] == str(socket_dir)
        assert socket_dir.exists()
        assert oct(socket_dir.stat().st_mode)[-3:] == "700"

    def test_ensure_started_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        call_count = 0

        def fake_run(argv, *, env, **kwargs):
            nonlocal call_count
            call_count += 1
            return _ok()

        monkeypatch.setattr("acceptance.actors.harness.subprocess.run", fake_run)
        actor = HarnessActor(command=("sh",), socket_dir=socket_dir)
        actor._ensure_started()
        actor._ensure_started()
        assert call_count == 1

    def test_over_long_socket_dir_fails_by_name_before_tmux_is_called(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A unix socket path is capped (104 bytes on macOS). A socket_dir
        derived from pytest's own tmp_path routinely exceeds it, and tmux's
        own failure ("File name too long", from inside a subprocess) names
        neither the limit nor the fix -- so the guard runs first.
        """
        called = False

        def fake_run(*args, **kwargs):
            nonlocal called
            called = True
            return _ok()

        monkeypatch.setattr("acceptance.actors.harness.subprocess.run", fake_run)
        too_long = tmp_path / ("d" * (max_socket_dir_length() + 1))
        actor = HarnessActor(command=("sh",), socket_dir=too_long)

        with pytest.raises(HarnessActorError, match="unix-socket limit"):
            actor._ensure_started()
        assert not called, "the guard must run before tmux is invoked"
        assert not too_long.exists(), "an unusable socket_dir must not be created"

    def test_socket_dir_within_the_limit_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("acceptance.actors.harness.subprocess.run", lambda *a, **k: _ok("%0"))
        short = Path("/tmp/sl-b3-guard-ok")
        try:
            actor = HarnessActor(command=("sh",), socket_dir=short)
            actor._ensure_started()
            assert short.exists()
        finally:
            if short.exists():
                short.rmdir()

    def test_new_session_failure_raises_harness_actor_error(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        monkeypatch.setattr(
            "acceptance.actors.harness.subprocess.run", lambda *a, **k: _fail("no server")
        )
        actor = HarnessActor(command=("sh",), socket_dir=socket_dir)
        with pytest.raises(HarnessActorError):
            actor._ensure_started()

    def test_send_line_argv_includes_text_and_enter(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        calls: list[list[str]] = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return _ok()

        monkeypatch.setattr("acceptance.actors.harness.subprocess.run", fake_run)
        actor = HarnessActor(command=("sh",), socket_dir=socket_dir)
        actor._send_line("hello mentor")

        argv = calls[0]
        assert "send-keys" in argv
        assert "hello mentor" in argv
        assert argv[-1] == "Enter"


@pytest.mark.asyncio
class TestConverseLoop:
    async def test_drives_two_turns_then_completes_on_sentinel(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        """The fake pane reproduces two REAL tmux behaviours (both verified
        against tmux 3.7b while building this backend), because a mock
        without them would pass while the real thing hangs:

        1. ``capture-pane -p`` pads its output to the pane's full height
           with blank lines, so the raw line count stops changing after the
           first turn.
        2. The pane ECHOES what ``send-keys`` typed into it, so the mentor's
           own reply reappears in the capture and must not be handed back
           to the mentor as the learner's next turn.
        """
        pane: list[str] = ["learner turn 1"]
        script_replies = ["learner turn 2", DONE_SENTINEL]
        send_keys_calls: list[str] = []
        pane_height = 24

        def fake_tmux(*args, socket_dir):
            cmd = args[0]
            if cmd == "new-session":
                return _ok()
            if cmd == "send-keys":
                text = args[3]
                send_keys_calls.append(text)
                pane.append(text)  # (2) the pane echoes typed input
                if script_replies:
                    pane.append(script_replies.pop(0))
                return _ok()
            if cmd == "capture-pane":
                # (1) padded to the pane height with blank lines
                padded = pane + [""] * (pane_height - len(pane))
                return _ok("\n".join(padded))
            if cmd == "kill-session":
                return _ok()
            raise AssertionError(f"unexpected tmux command: {cmd}")

        monkeypatch.setattr("acceptance.actors.harness._tmux", fake_tmux)
        actor = HarnessActor(
            command=("sh",),
            socket_dir=socket_dir,
            reply_timeout=2.0,
            budget=BudgetGuard(max_turns=10),
        )
        mentor = EchoMentor()

        result = await actor.converse(mentor)

        assert result.outcome is TerminationOutcome.COMPLETED
        assert [t.learner_message for t in result.transcript] == [
            "learner turn 1",
            "learner turn 2",
        ]
        assert send_keys_calls == ["mentor said: learner turn 1", "mentor said: learner turn 2"]
        assert all(t.usage == TokenUsage.unknown() for t in result.transcript)
        await actor.aclose()

    async def test_multiline_mentor_reply_is_not_misread_as_a_learner_turn(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        """Verified against real tmux 3.7b: sending text containing an
        embedded literal newline plus ``Enter`` echoes back as MULTIPLE
        separate pane lines, not one. A multi-line ``mentor_reply`` must
        have every one of its lines queued for echo-suppression, or the
        mentor's own echoed words are misread as new learner turns.
        """
        pane: list[str] = ["learner turn 1"]
        script_replies = [DONE_SENTINEL]
        pane_height = 24

        def fake_tmux(*args, socket_dir):
            cmd = args[0]
            if cmd == "new-session":
                return _ok()
            if cmd == "send-keys":
                text = args[3]
                # Real tmux: an embedded literal newline in `text` is
                # echoed back as separate pane lines, never one.
                pane.extend(text.splitlines())
                if script_replies:
                    pane.append(script_replies.pop(0))
                return _ok()
            if cmd == "capture-pane":
                padded = pane + [""] * (pane_height - len(pane))
                return _ok("\n".join(padded))
            if cmd == "kill-session":
                return _ok()
            raise AssertionError(f"unexpected tmux command: {cmd}")

        monkeypatch.setattr("acceptance.actors.harness._tmux", fake_tmux)
        actor = HarnessActor(
            command=("sh",),
            socket_dir=socket_dir,
            reply_timeout=2.0,
            budget=BudgetGuard(max_turns=10),
        )

        result = await actor.converse(MultiLineMentor())

        assert result.outcome is TerminationOutcome.COMPLETED
        assert [t.learner_message for t in result.transcript] == ["learner turn 1"]
        await actor.aclose()

    async def test_mentor_reply_with_blank_paragraph_break_is_not_misread(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        """A blank line inside ``mentor_reply`` (a paragraph break) must not
        get queued as a pending-echo entry that can never be dequeued --
        ``_capture()`` only ever returns NON-BLANK lines, so an empty
        pending-echo entry would sit at the head of the queue forever,
        blocking every later echo match and causing the NEXT real line
        ("para two") to be misread as a new learner turn.
        """
        pane: list[str] = ["learner turn 1"]
        script_replies = [DONE_SENTINEL]
        pane_height = 24

        def fake_tmux(*args, socket_dir):
            cmd = args[0]
            if cmd == "new-session":
                return _ok()
            if cmd == "send-keys":
                text = args[3]
                # Real tmux: an embedded literal newline in `text` is
                # echoed back as separate pane lines, INCLUDING a blank
                # line for an embedded blank line -- never one.
                pane.extend(text.splitlines())
                if script_replies:
                    pane.append(script_replies.pop(0))
                return _ok()
            if cmd == "capture-pane":
                padded = pane + [""] * (pane_height - len(pane))
                return _ok("\n".join(padded))
            if cmd == "kill-session":
                return _ok()
            raise AssertionError(f"unexpected tmux command: {cmd}")

        monkeypatch.setattr("acceptance.actors.harness._tmux", fake_tmux)
        actor = HarnessActor(
            command=("sh",),
            socket_dir=socket_dir,
            reply_timeout=2.0,
            budget=BudgetGuard(max_turns=10),
        )

        result = await actor.converse(ParagraphBreakMentor())

        assert result.outcome is TerminationOutcome.COMPLETED
        assert [t.learner_message for t in result.transcript] == ["learner turn 1"]
        await actor.aclose()

    async def test_stops_at_max_turns_when_no_sentinel_ever_arrives(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        line_count = 0

        def fake_tmux(*args, socket_dir):
            nonlocal line_count
            cmd = args[0]
            if cmd == "new-session":
                return _ok()
            if cmd == "send-keys":
                return _ok()
            if cmd == "capture-pane":
                line_count += 1
                return _ok("\n".join(f"learner turn {i}" for i in range(1, line_count + 1)))
            if cmd == "kill-session":
                return _ok()
            raise AssertionError(f"unexpected tmux command: {cmd}")

        monkeypatch.setattr("acceptance.actors.harness._tmux", fake_tmux)
        actor = HarnessActor(
            command=("sh",),
            socket_dir=socket_dir,
            reply_timeout=2.0,
            budget=BudgetGuard(max_turns=3),
        )

        result = await actor.converse(EchoMentor())

        assert result.outcome is TerminationOutcome.BUDGET_EXHAUSTED
        assert len(result.transcript) == 3
        await actor.aclose()

    async def test_timeout_waiting_for_next_line_is_errored_not_a_hang(
        self, monkeypatch: pytest.MonkeyPatch, socket_dir: Path
    ) -> None:
        def fake_tmux(*args, socket_dir):
            cmd = args[0]
            if cmd == "new-session":
                return _ok()
            if cmd == "capture-pane":
                return _ok("")  # never produces a line
            if cmd == "kill-session":
                return _ok()
            raise AssertionError(f"unexpected tmux command: {cmd}")

        monkeypatch.setattr("acceptance.actors.harness._tmux", fake_tmux)
        actor = HarnessActor(command=("sh",), socket_dir=socket_dir, reply_timeout=0.3)

        result = await actor.converse(EchoMentor())

        assert result.outcome is TerminationOutcome.ERRORED
        assert "timed out" in (result.error or "")
        await actor.aclose()
