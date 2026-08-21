"""Terminal-multiplexer seam, herdr-first.

StudyLoop's older session paths shell out to ``tmux`` directly.  herdr
(https://github.com/herdrdev/herdr) replaces it: same prefix-key model, but a
socket API built for agent panes (``herdr pane split/run/send-text``,
``herdr agent start/prompt/wait``), which is what a study session actually
needs.

This module is the seam.  New code — starting with the study-plan workspace —
talks to :class:`Multiplexer` instead of shelling out to a specific binary, so
the remaining tmux call sites can be migrated onto it incrementally without
another rewrite.

Command construction only: every method returns the argv it would run, and
``run`` is injectable, so the mapping is unit-testable without a live
multiplexer.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)

#: Preference order. herdr first — tmux remains only as a migration fallback.
BACKEND_PREFERENCE = ("herdr", "tmux")

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)


class MultiplexerBackend(Protocol):
    """The operations a study session needs from a terminal multiplexer."""

    #: Human-readable backend name ("herdr", "tmux").
    name: str
    #: The executable to look for on PATH. Read by ``Multiplexer.installed``,
    #: so it belongs in the Protocol rather than only on the concrete backends.
    binary: str

    def session_list_argv(self) -> list[str]: ...
    def new_session_argv(self, session: str, cwd: str = "") -> list[str]: ...
    def attach_argv(self, session: str) -> list[str]: ...
    def split_argv(self, session: str, *, direction: str, ratio: float) -> list[str]: ...
    def run_argv(self, pane: str, command: list[str]) -> list[str]: ...
    def send_text_argv(self, pane: str, text: str) -> list[str]: ...


@dataclass
class HerdrBackend:
    """herdr backend — the supported target."""

    name: str = "herdr"
    binary: str = "herdr"

    def session_list_argv(self) -> list[str]:
        return [self.binary, "session", "list", "--json"]

    def new_session_argv(self, session: str, cwd: str = "") -> list[str]:
        # `herdr --session <name>` launches or attaches; herdr owns persistence,
        # so "create" and "attach" are deliberately the same verb.
        argv = [self.binary, "--session", session]
        if cwd:
            argv += ["--cwd", cwd]
        return argv

    def attach_argv(self, session: str) -> list[str]:
        return [self.binary, "session", "attach", session]

    def split_argv(
        self, session: str, *, direction: str = "right", ratio: float = 0.3
    ) -> list[str]:
        if direction not in {"right", "down"}:
            msg = f"herdr split direction must be right|down, got {direction!r}"
            raise ValueError(msg)
        return [
            self.binary,
            "pane",
            "split",
            "--current",
            "--direction",
            direction,
            "--ratio",
            str(ratio),
        ]

    def run_argv(self, pane: str, command: list[str]) -> list[str]:
        return [self.binary, "pane", "run", pane, *command]

    def send_text_argv(self, pane: str, text: str) -> list[str]:
        return [self.binary, "pane", "send-text", pane, text]

    def agent_prompt_argv(self, agent: str, prompt: str) -> list[str]:
        """herdr-only: push a prompt into a running agent pane."""
        return [self.binary, "agent", "prompt", agent, prompt]


@dataclass
class TmuxBackend:
    """Legacy tmux backend — retained only so migration is incremental.

    Do not add new call sites. New features target :class:`HerdrBackend`.
    """

    name: str = "tmux"
    binary: str = "tmux"

    def session_list_argv(self) -> list[str]:
        return [self.binary, "list-sessions", "-F", "#{session_name}"]

    def new_session_argv(self, session: str, cwd: str = "") -> list[str]:
        argv = [self.binary, "new-session", "-d", "-s", session]
        if cwd:
            argv += ["-c", cwd]
        return argv

    def attach_argv(self, session: str) -> list[str]:
        return [self.binary, "attach-session", "-t", session]

    def split_argv(
        self, session: str, *, direction: str = "right", ratio: float = 0.3
    ) -> list[str]:
        flag = "-h" if direction == "right" else "-v"
        return [self.binary, "split-window", flag, "-t", session, "-p", str(int(ratio * 100))]

    def run_argv(self, pane: str, command: list[str]) -> list[str]:
        return [self.binary, "send-keys", "-t", pane, " ".join(command), "Enter"]

    def send_text_argv(self, pane: str, text: str) -> list[str]:
        return [self.binary, "send-keys", "-t", pane, text]


_BACKENDS: dict[str, Callable[[], MultiplexerBackend]] = {
    "herdr": HerdrBackend,
    "tmux": TmuxBackend,
}


def available_backends(which=shutil.which) -> list[str]:
    """Return installed backends, in preference order."""
    return [name for name in BACKEND_PREFERENCE if which(name)]


def preferred_backend(which=shutil.which) -> str:
    """Return the backend to use — herdr when present, else tmux, else ''."""
    found = available_backends(which)
    return found[0] if found else ""


@dataclass
class Multiplexer:
    """Backend-agnostic façade over the multiplexer in use."""

    backend: MultiplexerBackend = field(default_factory=HerdrBackend)
    run: Runner = _default_runner

    @classmethod
    def detect(cls, *, run: Runner | None = None, which=shutil.which) -> Multiplexer:
        """Build a Multiplexer for the best available backend.

        Falls back to herdr command construction when nothing is installed, so
        callers get a coherent "herdr not installed" error rather than a
        surprise tmux invocation.
        """
        name = preferred_backend(which)
        factory = _BACKENDS.get(name, HerdrBackend)
        if not name:
            logger.warning("No terminal multiplexer found on PATH (looked for herdr, tmux)")
        return cls(backend=factory(), run=run or _default_runner)

    @property
    def name(self) -> str:
        return self.backend.name

    @property
    def installed(self) -> bool:
        return bool(shutil.which(self.backend.binary))

    def session_names(self) -> list[str]:
        """Return live session names (empty when the backend is unavailable)."""
        try:
            result = self.run(self.backend.session_list_argv())
        except Exception:
            logger.debug("session list failed for %s", self.name, exc_info=True)
            return []
        if result.returncode != 0:
            return []
        text = (result.stdout or "").strip()
        if not text:
            return []
        if text.startswith("[") or text.startswith("{"):
            import json

            try:
                data = json.loads(text)
            except ValueError:
                return []
            rows = data.get("sessions", data) if isinstance(data, dict) else data
            names = []
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and row.get("name"):
                    names.append(str(row["name"]))
                elif isinstance(row, str):
                    names.append(row)
            return names
        # Tabular / plain output: first whitespace-separated column, minus header.
        names = []
        for line in text.splitlines():
            first = line.split()[0] if line.split() else ""
            if not first or first.lower() == "name":
                continue
            names.append(first)
        return names

    def session_exists(self, session: str) -> bool:
        return session in self.session_names()

    def ensure_session(self, session: str, *, cwd: str = "") -> bool:
        """Create the session if absent. Returns True when it exists after."""
        if self.session_exists(session):
            return True
        try:
            result = self.run(self.backend.new_session_argv(session, cwd))
        except Exception:
            logger.debug("session create failed for %s", session, exc_info=True)
            return False
        return result.returncode == 0

    def attach_command(self, session: str) -> list[str]:
        """The argv a human runs to attach — printed, not executed for them."""
        return self.backend.attach_argv(session)
