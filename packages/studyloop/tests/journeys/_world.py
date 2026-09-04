"""A hermetic world the real StudyLoop CLI can be driven inside, as a learner does.

Why subprocesses rather than ``CliRunner``: the journeys in this package are about
the *experience*, and the experience includes what a command prints and what exit
code it hands back. An in-process runner shares this interpreter's environment, so
an isolation mistake would be masked by pytest's own fixtures. A subprocess gets an
environment and nothing else, which is both more representative and — because the
guards can then check what the child itself resolves — more honestly testable.

The complete-environment idea and the refusal to inherit are lifted from
``tests/e2e/_env.py``, which learned it the hard way: several callers there used to
spawn a real server against the developer's real ``~/.config/studyloop``. This module
reuses that lesson rather than the code, because the e2e helper also starts a web
server and manages IPC, none of which a CLI journey needs.

Nothing here is selectable as a product backend and nothing ships in the wheel.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The repository's package source, so a child can import studyloop without an
#: install step. Resolved from this file rather than from the working directory,
#: which a test is free to change.
_SRC = Path(__file__).resolve().parents[2] / "src"

#: A minimal PATH. The journeys shell out to nothing but Python, so a fuller PATH
#: would only widen what a bug could reach.
_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


#: The statuses the brain commands print, longest prefix first so that
#: "would write" is never parsed as "written".
_REPORT_STATUSES = (
    "would write",
    "unchanged",
    "replaced",
    "written",
    "skipped",
    "warning",
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """One command a learner ran, and everything they would have seen."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def display(self) -> str:
        """The command as a learner would have typed it."""
        return "studyloop " + " ".join(self.argv)

    @property
    def output(self) -> str:
        """Everything on screen. Some Click errors go to stderr; a learner sees both."""
        return self.stdout + self.stderr

    def results(self) -> list[tuple[str, str]]:
        """Parse this command's report into ``(status, detail)`` pairs.

        A validation council found the journey asserting on substrings — "does the
        output contain this path" — which stays green through a product that names
        the path for the wrong reason. ``written Study/Plans/x.md`` and
        ``warning   replaced your edits in 'Study/Plans/x.md'`` both contain the
        path, and only one of them tells a learner their text is gone.

        Parsing lets a beat say *which status* each path got, and that nothing else
        appeared. Longest prefixes first, so "would write" is not read as "written".
        """
        parsed: list[tuple[str, str]] = []
        for raw in self.output.splitlines():
            line = raw.strip()
            if not line:
                continue
            for status in _REPORT_STATUSES:
                if line.startswith(status):
                    parsed.append((status, line[len(status) :].strip()))
                    break
        return parsed

    def statuses_for(self, needle: str) -> list[str]:
        """Every status whose detail mentions ``needle``."""
        return [status for status, detail in self.results() if needle in detail]


@dataclass
class JourneyWorld:
    """An isolated home, config, plans directory, vault and database.

    Deliberately not frozen: the transcript grows as the journey runs, and that
    growth IS the evidence.
    """

    root: Path
    home: Path
    config: Path
    plans: Path
    vault: Path
    session_db: Path
    env: dict[str, str]
    transcript: list[CommandResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # -- driving the CLI ----------------------------------------------------

    def run(self, *argv: str) -> CommandResult:
        """Run one ``studyloop`` command inside the world and record it."""
        completed = subprocess.run(
            [sys.executable, "-m", "studyloop.cli", *argv],
            env=self.env,
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        result = CommandResult(
            argv=tuple(argv),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        self.transcript.append(result)
        return result

    def run_python(self, source: str) -> CommandResult:
        """Run a snippet in a child with the world's environment.

        Exists for the guards: the only trustworthy answer to "where does a child
        think HOME is" comes from asking a child.
        """
        completed = subprocess.run(
            [sys.executable, "-c", source],
            env=self.env,
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        result = CommandResult(
            argv=("<python>",),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        return result

    # -- reading the vault as a learner would -------------------------------

    def vault_tree(self) -> list[str]:
        """Every file under the vault, vault-relative, sorted."""
        return sorted(
            path.relative_to(self.vault).as_posix()
            for path in self.vault.rglob("*")
            if path.is_file() and ".obsidian" not in path.parts
        )

    def read(self, relative: str) -> str:
        return (self.vault / relative).read_text(encoding="utf-8")

    def digest(self, relative: str) -> str | None:
        """A short content digest, or ``None`` when the file is absent.

        ``None`` rather than an exception so a beat can assert "still absent" and
        "still unchanged" with the same call.
        """
        try:
            raw = (self.vault / relative).read_bytes()
        except OSError:
            return None
        return hashlib.sha256(raw).hexdigest()[:16]

    # -- the evidence -------------------------------------------------------

    def note(self, line: str) -> None:
        """Record a beat boundary in the transcript."""
        self.notes.append(line)

    def redact(self, text: str) -> str:
        """Replace machine-specific paths with stable placeholders.

        Not cosmetic. A pytest tmp path is ``/private/var/.../pytest-of-<username>/``,
        so an unredacted transcript files the operator's account name into an evidence
        artefact — which the plan forbids, and which would have shipped unnoticed
        because the path looks like scaffolding rather than personal data. Redacting
        also makes the transcript readable, which is the whole point of the artefact.
        """
        cleaned = text.replace(str(self.root), "<world>")
        home = str(Path.home())
        cleaned = cleaned.replace(home, "<home>")
        # The tmp root sits above `self.root` and carries the username too.
        return re.sub(r"/pytest-of-[^/\s]+", "/pytest-of-<user>", cleaned)

    def transcript_text(self) -> str:
        parts: list[str] = []
        for entry in self.transcript:
            parts.append(f"$ {self.redact(entry.display)}")
            body = self.redact(entry.output).rstrip()
            if body:
                parts.append(body)
            if entry.exit_code:
                parts.append(f"[exit {entry.exit_code}]")
            parts.append("")
        return "\n".join(parts)


def _write_config(config: Path, session_db: Path) -> None:
    """A config with topics and a database, and deliberately NO second_brain.

    The journey's own first act is enabling a provider. A world that arrived
    configured would skip the step a learner is most likely to get wrong.
    """
    config.write_text(
        yaml.dump(
            {
                "topics": [{"name": "Python Decorators", "slug": "python-decorators"}],
                "session_db": str(session_db),
            },
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


#: Environment keys that legitimately point at the repository or the system, and so
#: are exempt from the "nothing outside the world" rule.
_EXEMPT_KEYS = frozenset({"PATH", "PYTHONPATH"})


class UnsafeJourneyWorldError(AssertionError):
    """Raised when a world would hand a child a path outside itself."""


def assert_root_is_outside_the_home(root: Path) -> None:
    """Refuse a world root inside the operator's own home, before anything is created.

    Two findings in one, both from running the test rather than reading the code:

    1. Every other check compares a value against the root, so a root of
       ``~/journey`` satisfied all of them — each path *did* start with the root —
       while the world was assembled inside the operator's own directory.
    2. The first fix ran after ``mkdir``, so it refused correctly and left
       ``~/journey/`` behind anyway. A guard that cleans up after itself is worth
       more than a guard that is merely right.

    Hence a separate function, called as the first statement of the builder.
    """
    real_home = Path.home().resolve()
    resolved = root.resolve() if root.exists() else root
    if resolved == real_home or real_home in resolved.parents:
        msg = (
            f"journey root {resolved} is inside the operator's home ({real_home}). "
            "A journey world must live under a temporary directory: every other check "
            "compares paths against the root, so a root inside your home passes all "
            "of them while the world is built in your own files."
        )
        raise UnsafeJourneyWorldError(msg)


def assert_world_is_hermetic(env: dict[str, str], root: Path) -> None:
    """Refuse an environment that could reach the developer's own directories.

    Extracted from :func:`journey_world` so it can be tested with a deliberately
    poisoned environment. When the check lived inline, mutating the builder made
    every guard ERROR during fixture setup rather than fail with a name — so the
    guards were never proven to work, and a later refactor that dropped the inline
    check would have left nothing behind. Two layers now: the builder refuses, and
    the refusal itself is exercised with real bad input.
    """
    if "VIRTUAL_ENV" in env:
        msg = "journey env inherited VIRTUAL_ENV, so the child may resolve host packages"
        raise UnsafeJourneyWorldError(msg)

    real_home = str(Path.home())
    root_prefix = str(root)
    offenders = [
        f"{key}={value}"
        for key, value in env.items()
        if key not in _EXEMPT_KEYS
        and value.startswith(real_home)
        and not value.startswith(root_prefix)
    ]
    if offenders:
        msg = "journey env points outside the world: " + ", ".join(sorted(offenders))
        raise UnsafeJourneyWorldError(msg)


@contextlib.contextmanager
def journey_world(tmp_path: Path) -> Iterator[JourneyWorld]:
    """Build an isolated world under ``tmp_path``.

    A context manager so a journey cannot forget to tear down, and so the evidence
    write has an obvious place to sit.
    """
    root = (tmp_path / "journey").resolve()
    # First statement, deliberately: everything below this line creates directories.
    assert_root_is_outside_the_home(root)
    home = root / "home"
    plans = root / "plans"
    vault = root / "vault"
    session_dir = root / "session-ipc"
    for directory in (home, plans, vault / ".obsidian", session_dir):
        directory.mkdir(parents=True, exist_ok=True)

    config = root / "config.yaml"
    session_db = root / "sessions.db"
    _write_config(config, session_db)

    env = {
        "PATH": _PATH,
        "HOME": str(home),
        "TMPDIR": str(root / "tmp"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "TERM": "dumb",
        # Rich wraps to the terminal width, and a wrapped absolute path defeats
        # redaction: the root no longer appears as one substring, so the machine
        # path survives into the evidence in two halves. Found by reading a real
        # transcript. A wide, fixed width also makes the artefact readable.
        "COLUMNS": "200",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(_SRC),
        "PYTHONIOENCODING": "utf-8",
        "STUDYLOOP_CONFIG": str(config),
        "STUDYLOOP_PLANS_DIR": str(plans),
        "STUDYLOOP_SESSION_DIR": str(session_dir),
        # The vault isolation override the settings layer reads. Set here as well
        # as in `second_brain.vault_path` so that a bug in either path still cannot
        # reach the real vault.
        "STUDYLOOP_SECOND_BRAIN_VAULT": str(vault),
    }
    (root / "tmp").mkdir(exist_ok=True)

    assert_world_is_hermetic(env, root)

    world = JourneyWorld(
        root=root,
        home=home,
        config=config,
        plans=plans,
        vault=vault,
        session_db=session_db,
        env=env,
    )
    try:
        yield world
    finally:
        # Nothing to tear down: everything lives under tmp_path, which pytest
        # removes. The contextmanager exists for the evidence hook, not cleanup.
        pass


def write_evidence(world: JourneyWorld, destination: Path, extra: dict[str, str]) -> None:
    """File the journey's evidence.

    Called only after the last assertion has passed, following the lesson from
    ``test_obsidian_live.py``: a bundle written mid-run describes a pass that may
    not have happened.
    """
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "transcript.txt").write_text(
        "# Journey transcript — every command a learner ran, and what they saw\n"
        "#\n"
        "# Generated by a test in packages/studyloop/tests/journeys/. Written only\n"
        "# after every assertion passed.\n\n"
        + "\n".join(f"beat: {line}" for line in world.notes)
        + "\n\n"
        + world.transcript_text(),
        encoding="utf-8",
    )
    (destination / "tree.txt").write_text("\n".join(world.vault_tree()) + "\n", encoding="utf-8")
    for name, body in extra.items():
        (destination / name).write_text(body, encoding="utf-8")


def evidence_root() -> Path:
    """Where journey evidence lands: the gitignored review tree."""
    return Path(__file__).resolve().parents[4] / "reviews" / "2026-09-04-user-harness" / "evidence"


__all__ = [
    "CommandResult",
    "JourneyWorld",
    "UnsafeJourneyWorldError",
    "assert_root_is_outside_the_home",
    "assert_world_is_hermetic",
    "evidence_root",
    "journey_world",
    "write_evidence",
]
