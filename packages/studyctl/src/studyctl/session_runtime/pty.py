"""PTY-backed transport for current terminal-native agent CLIs."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from typing import TYPE_CHECKING

import pexpect

from studyctl.session_runtime.protocol import SessionEvent, SessionStartSpec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping


class PtyAgentSessionTransport:
    """Run an agent CLI in a pseudo-terminal and stream terminal output."""

    def __init__(self, spec: SessionStartSpec) -> None:
        self.spec = spec
        self.session_id = spec.session_id
        self._child: pexpect.spawn | None = None
        self._stopped = False

    async def start(self) -> None:
        """Spawn the configured command in a PTY."""
        env = _merged_env(self.spec.env)
        command = self.spec.command
        if isinstance(command, str):
            shell = os.environ.get("SHELL", "/bin/zsh")
            child = pexpect.spawn(
                shell,
                ["-lc", command],
                cwd=str(self.spec.cwd),
                env=env,  # pyright: ignore[reportArgumentType]
                encoding="utf-8",
                codec_errors="replace",
                echo=False,
                timeout=0.1,
            )
        else:
            child = pexpect.spawn(
                command[0],
                command[1:],
                cwd=str(self.spec.cwd),
                env=env,  # pyright: ignore[reportArgumentType]
                encoding="utf-8",
                codec_errors="replace",
                echo=False,
                timeout=0.1,
            )
        self._child = child

    async def send(self, text: str) -> None:
        """Write learner input to the PTY."""
        child = self._require_child()
        payload = text if text.endswith(("\n", "\r")) else f"{text}\r"
        await asyncio.to_thread(child.send, payload)

    async def events(self) -> AsyncIterator[SessionEvent]:
        """Yield PTY output until the child exits or the transport stops."""
        child = self._require_child()
        yield SessionEvent(
            "started",
            self.session_id,
            {
                "agent": self.spec.agent,
                "transport": self.spec.transport,
                "topic": self.spec.topic,
                "energy": self.spec.energy,
                "command": _display_command(self.spec.command),
            },
        )

        while not self._stopped:
            if not child.isalive():
                break
            try:
                chunk = await asyncio.to_thread(child.read_nonblocking, 4096, 0.1)
            except pexpect.TIMEOUT:
                await asyncio.sleep(0.05)
                continue
            except pexpect.EOF:
                break
            text = clean_terminal_output(chunk)
            if text.strip():
                yield SessionEvent("output", self.session_id, {"text": text})

        exitstatus = child.exitstatus
        signalstatus = child.signalstatus
        yield SessionEvent(
            "ended",
            self.session_id,
            {"exitstatus": exitstatus, "signalstatus": signalstatus},
        )

    async def stop(self) -> None:
        """Terminate the child process."""
        self._stopped = True
        child = self._child
        if child and child.isalive():
            await asyncio.to_thread(child.terminate, True)

    def _require_child(self) -> pexpect.spawn:
        if self._child is None:
            raise RuntimeError("PTY transport has not been started")
        return self._child


def _merged_env(extra: Mapping[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(extra)
    agent = env.get("STUDYLOOP_AGENT", "")
    default_term = "dumb" if agent == "claude" else "xterm-256color"
    env["TERM"] = env.get("STUDYLOOP_TERM", default_term)
    env["NO_COLOR"] = "1"
    env["CLICOLOR"] = "0"
    return env


def _display_command(command: str | list[str]) -> str:
    if isinstance(command, str):
        return command
    return " ".join(shlex.quote(part) for part in command)


_ANSI_RE = re.compile(
    r"""
    \x1b
    (?:
        \[[0-?]*[ -/]*[@-~] |
        \][^\x07]*(?:\x07|\x1b\\) |
        [@-Z\\-_]
    )
    """,
    re.VERBOSE,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def clean_terminal_output(text: str) -> str:
    """Convert full-screen terminal output into readable plain text."""
    cleaned = _ANSI_RE.sub("", text)
    cleaned = _CONTROL_RE.sub("", cleaned)
    return cleaned.replace("\r\n", "\n").replace("\r", "\n")
