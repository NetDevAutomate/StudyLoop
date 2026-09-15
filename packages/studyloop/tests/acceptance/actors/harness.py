"""``ACTOR=harness`` -- a second harness instance plays the learner over tmux.

Council D-11 (verified, B1's isolation contract): a scratch acceptance run
already gets its own ``TMUX_TMPDIR`` for the MENTOR's tmux socket, if the
mentor's own transport uses tmux at all. The learner's second harness
process must never share that socket, or any tmux server started under the
developer's real environment -- two independent coding-agent processes must
never see, or be able to attach to, each other's panes or sessions. This
backend therefore always requires its OWN ``socket_dir`` and drives tmux
against it explicitly, on every call -- never by mutating this process's
real ``os.environ["TMUX_TMPDIR"]`` (which would race any other tmux use in
the same process) and never by relying on ``studyloop.tmux``'s helpers
(they always inherit whatever ``TMUX_TMPDIR`` this process happens to have,
by design -- correct for the mentor's own tmux use, wrong here). The
env-override-per-call pattern below mirrors
``tests/acceptance/isolation.py``'s own ``_kill_scratch_tmux_server``.

Token/usage accounting is honestly "unknown" (council D-15): a generic
harness gives terminal output, not a token count.

Protocol, not pane text: this backend's OWN job is plumbing (start a
process, send it a line, read its next line) -- it does not parse or judge
what the second harness says, matching D-17's "pane text is evidence, never
an assertion target" from the harness-matrix lane's brief.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from acceptance.actors.protocol import (
    ActorError,
    ConversationResult,
    LearnerTurn,
    TerminationOutcome,
    TokenUsage,
)

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from acceptance.actors.protocol import MentorTransport

from acceptance.actors.budget import BudgetGuard

#: A mock harness under test writes this exact line (and nothing else on
#: it) to signal "the conversation is over" -- the ONLY way this backend
#: ever reports ``TerminationOutcome.COMPLETED`` (a real second harness
#: would need to be told to emit this too; wiring that up for a specific
#: real harness is a later lane's job, same scoping as ``_loop.py``'s note).
DONE_SENTINEL = "STUDYLOOP_ACTOR_DONE"

_POLL_INTERVAL = 0.2

ENV_COMMAND = "STUDYLOOP_ACC_HARNESS_ACTOR_CMD"

#: A unix domain socket's path is capped by ``sockaddr_un.sun_path``: 104
#: bytes on macOS/BSD, 108 on Linux. Take the smaller so the same
#: ``socket_dir`` works on both, and subtract what tmux appends underneath
#: it (``/tmux-<uid>/default``) plus headroom for a longer uid.
#: A caller under pytest's own ``tmp_path`` will EXCEED this -- the
#: generated per-test directory names are long -- which is exactly why this
#: is a named, actionable error rather than tmux's own "File name too long"
#: from deep inside a subprocess.
_SUN_PATH_LIMIT = 104
_TMUX_SOCKET_SUFFIX_BUDGET = 24


class HarnessActorError(ActorError):
    """A tmux or second-harness-process failure while driving this actor."""


def max_socket_dir_length() -> int:
    """Longest ``socket_dir`` path tmux can still build a socket under."""
    return _SUN_PATH_LIMIT - _TMUX_SOCKET_SUFFIX_BUDGET


def _tmux(*args: str, socket_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run one tmux command against a DEDICATED socket directory.

    See the module docstring: this never touches the real process
    environment, and never delegates to ``studyloop.tmux`` (whose helpers
    have no ``env=`` override point).
    """
    return subprocess.run(
        ["tmux", *args],
        env={**os.environ, "TMUX_TMPDIR": str(socket_dir)},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@dataclass
class HarnessActor:
    """Drives a second, isolated harness process that plays the learner."""

    name = "harness"

    command: Sequence[str]
    socket_dir: Path
    budget: BudgetGuard = field(default_factory=lambda: BudgetGuard(max_turns=8))
    session_name: str = field(default_factory=lambda: f"studyloop-actor-{uuid.uuid4().hex[:8]}")
    reply_timeout: float = 15.0
    _started: bool = field(default=False, init=False, repr=False)
    #: How many NON-BLANK captured lines have already been consumed --
    #: never a raw line count: ``capture-pane -p`` pads its output to the
    #: pane's full height with blank lines, so a raw ``len(lines)`` is
    #: constant from the first turn onward and would never register a
    #: second one.
    _consumed: int = field(default=0, init=False, repr=False)
    #: Lines this actor sent into the pane and therefore expects to see
    #: captured back: a tmux pane echoes ``send-keys`` input, so the
    #: mentor's own reply appears in the capture and must not be misread
    #: as the learner's next turn.
    _pending_echo: deque[str] = field(default_factory=deque, init=False, repr=False)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        socket_dir: Path,
        harness_command: Sequence[str] | None = None,
        budget: BudgetGuard | None = None,
    ) -> HarnessActor:
        """Build from ``STUDYLOOP_ACC_HARNESS_ACTOR_CMD`` (or an explicit
        ``harness_command=``) plus a caller-supplied, ALREADY-DEDICATED
        ``socket_dir`` -- this backend never invents its own scratch
        directory; the caller (an acceptance fixture) owns that lifecycle,
        the same way ``tests/acceptance/isolation.py`` owns the mentor's.

        Raises :class:`ActorError` if ``tmux`` is missing from ``PATH`` or
        no command is configured -- callers should call
        :func:`acceptance.actors.factory.skip_reason` first and skip by
        name instead of reaching this constructor.
        """
        if shutil.which("tmux") is None:
            raise ActorError(
                "HarnessActor requires tmux on PATH -- call "
                "skip_reason('harness', env=...) before constructing this backend"
            )
        command = harness_command
        if command is None:
            raw = (env.get(ENV_COMMAND) or "").strip()
            if not raw:
                raise ActorError(
                    f"HarnessActor requires harness_command= or {ENV_COMMAND} -- call "
                    "skip_reason('harness', env=...) before constructing this backend"
                )
            command = shlex.split(raw)
        kwargs: dict = {"command": tuple(command), "socket_dir": socket_dir}
        if budget is not None:
            kwargs["budget"] = budget
        return cls(**kwargs)

    def _ensure_started(self) -> None:
        if self._started:
            return
        limit = max_socket_dir_length()
        if len(str(self.socket_dir)) > limit:
            raise HarnessActorError(
                f"socket_dir path is {len(str(self.socket_dir))} characters, over the "
                f"{limit}-character unix-socket limit tmux can build under: "
                f"{self.socket_dir}. Pass a SHORTER directory (e.g. one under /tmp) -- "
                "a path derived from pytest's tmp_path is typically too long."
            )
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        self.socket_dir.chmod(0o700)
        shell_command = shlex.join(self.command)
        result = _tmux(
            "new-session",
            "-d",
            "-s",
            self.session_name,
            "-P",
            "-F",
            "#{pane_id}",
            shell_command,
            socket_dir=self.socket_dir,
        )
        if result.returncode != 0:
            raise HarnessActorError(f"tmux new-session failed: {result.stderr.strip()}")
        self._started = True

    def _send_line(self, text: str) -> None:
        result = _tmux(
            "send-keys", "-t", self.session_name, text, "Enter", socket_dir=self.socket_dir
        )
        if result.returncode != 0:
            raise HarnessActorError(f"tmux send-keys failed: {result.stderr.strip()}")
        # A tmux pane echoes what send-keys typed into it, so this exact
        # text will come back out of capture-pane. Queue it so the reader
        # skips it instead of handing the mentor's own words back to the
        # mentor as the learner's next turn.
        self._pending_echo.append(text.strip())

    def _capture(self) -> list[str]:
        result = _tmux("capture-pane", "-p", "-t", self.session_name, socket_dir=self.socket_dir)
        if result.returncode != 0:
            raise HarnessActorError(f"tmux capture-pane failed: {result.stderr.strip()}")
        # Non-blank only, in order: capture-pane pads to the pane's height.
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _read_next_line(self) -> tuple[str | None, bool]:
        """Poll ``capture-pane`` until the next unconsumed learner line appears.

        Consumes non-blank captured lines strictly IN ORDER (never "the
        newest one") so a turn is never skipped when two lines land between
        polls, dropping any line that is this actor's own echoed
        ``send-keys`` input.

        Returns ``(learner_message, done)``. ``(None, False)`` means "timed
        out waiting" -- the caller reports
        ``TerminationOutcome.ERRORED``. ``(None, True)`` means the sentinel
        arrived: the caller reports ``TerminationOutcome.COMPLETED``.

        Known limitation, stated rather than hidden: a line longer than the
        pane's width is wrapped by the terminal and comes back as two
        captured lines, so echo-matching on it fails. The mock harness this
        lane tests against sends short lines; a real second harness with a
        full TUI needs a richer reader than "one line at a time", which is
        the same later-lane boundary ``_loop.py``'s scoping note draws.
        """
        deadline = time.monotonic() + self.reply_timeout
        while time.monotonic() < deadline:
            lines = self._capture()
            while self._consumed < len(lines):
                line = lines[self._consumed]
                self._consumed += 1
                if self._pending_echo and line == self._pending_echo[0]:
                    self._pending_echo.popleft()
                    continue
                if line == DONE_SENTINEL:
                    return None, True
                return line, False
            time.sleep(_POLL_INTERVAL)
        return None, False

    async def converse(
        self,
        mentor: MentorTransport,
        *,
        cancel: asyncio.Event | None = None,
    ) -> ConversationResult:
        import asyncio as _asyncio

        transcript: list[LearnerTurn] = []
        try:
            await _asyncio.to_thread(self._ensure_started)
        except HarnessActorError as exc:
            return ConversationResult(
                outcome=TerminationOutcome.ERRORED, transcript=(), error=str(exc)
            )

        while True:
            if cancel is not None and cancel.is_set():
                return ConversationResult(
                    outcome=TerminationOutcome.CANCELLED, transcript=tuple(transcript)
                )
            if not self.budget.has_budget_for_next_turn():
                return ConversationResult(
                    outcome=TerminationOutcome.BUDGET_EXHAUSTED, transcript=tuple(transcript)
                )

            try:
                learner_message, done = await _asyncio.to_thread(self._read_next_line)
            except HarnessActorError as exc:
                return ConversationResult(
                    outcome=TerminationOutcome.ERRORED,
                    transcript=tuple(transcript),
                    error=str(exc),
                )
            if done:
                return ConversationResult(
                    outcome=TerminationOutcome.COMPLETED, transcript=tuple(transcript)
                )
            if learner_message is None:
                return ConversationResult(
                    outcome=TerminationOutcome.ERRORED,
                    transcript=tuple(transcript),
                    error=(
                        f"timed out after {self.reply_timeout}s waiting for the "
                        "harness actor's next line"
                    ),
                )

            try:
                mentor_reply = await mentor.send(learner_message)
            except Exception as exc:  # becomes an outcome, never a raise
                return ConversationResult(
                    outcome=TerminationOutcome.ERRORED,
                    transcript=tuple(transcript),
                    error=str(exc),
                )

            try:
                await _asyncio.to_thread(self._send_line, mentor_reply)
            except HarnessActorError as exc:
                return ConversationResult(
                    outcome=TerminationOutcome.ERRORED,
                    transcript=tuple(transcript),
                    error=str(exc),
                )

            transcript.append(
                LearnerTurn(
                    learner_message=learner_message,
                    mentor_reply=mentor_reply,
                    usage=TokenUsage.unknown(),
                )
            )
            self.budget.record_turn(output_tokens=None)

    async def aclose(self) -> None:
        import asyncio as _asyncio

        if not self._started:
            return
        await _asyncio.to_thread(
            _tmux, "kill-session", "-t", self.session_name, socket_dir=self.socket_dir
        )


__all__ = ["DONE_SENTINEL", "ENV_COMMAND", "HarnessActor", "HarnessActorError"]
