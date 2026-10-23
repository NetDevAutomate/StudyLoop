"""Data model for doctor check results."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VALID_STATUSES = frozenset({"pass", "warn", "fail", "info"})
VALID_CATEGORIES = frozenset(
    {"core", "database", "config", "agents", "deps", "voice", "updates", "harness"}
)

#: The one shape ``fix_hint`` renders a command-plus-note in, and the inverse
#: :func:`split_fix_hint` reads: the command, two spaces, the note in parentheses.
_HINT_SEPARATOR = "  "
_COMMAND_WITH_NOTE_RE = re.compile(r"^(?P<command>\S.*?)  \((?P<note>.*)\)$", re.DOTALL)
#: First tokens that make a bare hint a command rather than prose.
_COMMAND_LEADERS = frozenset(
    {
        "studyloop",
        "studyloop-mcp",
        "session-maint",
        "session-query",
        "session-export",
        "session-db-mcp",
        "uv",
        "uvx",
        "pip",
        "brew",
        "apt",
        "mkdir",
        "rm",
        "cd",
        "git",
        "npm",
        "./scripts/install.sh",
    }
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Single diagnostic check result. This is the contract for --json output.

    ``fix_command`` is an exact, copy-pasteable command and nothing else;
    ``fix_note`` is prose (what the command does, or what to do when there is
    no command). Both are keyword-only so a producer that still passes the old
    positional ``fix_hint`` fails at construction rather than mis-filing it.
    ``fix_hint`` is derived from the two for readers that predate the split.
    """

    category: str
    name: str
    status: str
    message: str
    fix_command: str | None = field(default=None, kw_only=True)
    fix_note: str | None = field(default=None, kw_only=True)
    fix_auto: bool = field(default=False, kw_only=True)

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            msg = f"status must be one of {VALID_STATUSES}, got {self.status!r}"
            raise ValueError(msg)
        if self.category not in VALID_CATEGORIES:
            msg = f"category must be one of {VALID_CATEGORIES}, got {self.category!r}"
            raise ValueError(msg)
        # "" and None both mean "nothing to show"; store one spelling so the
        # renderer and --json consumers test a single condition.
        if self.fix_command is not None and not self.fix_command.strip():
            object.__setattr__(self, "fix_command", None)
        if self.fix_note is not None and not self.fix_note.strip():
            object.__setattr__(self, "fix_note", None)

    @property
    def fix_hint(self) -> str:
        """The command and the note as one line: ``<command>  (<note>)``.

        Read-only and derived; kept so ``studyloop upgrade``'s table, ``--json``
        consumers and older tests that read ``fix_hint`` keep working.
        """
        if self.fix_command and self.fix_note:
            return f"{self.fix_command}{_HINT_SEPARATOR}({self.fix_note})"
        return self.fix_command or self.fix_note or ""

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "category": self.category,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "fix_command": self.fix_command,
            "fix_note": self.fix_note,
            "fix_hint": self.fix_hint,
            "fix_auto": self.fix_auto,
        }


def split_fix_hint(hint: str) -> tuple[str | None, str | None]:
    """``(fix_command, fix_note)`` for a one-line hint built outside ``doctor/``.

    The inverse of :attr:`CheckResult.fix_hint` for the ``<command>  (<note>)``
    shape (``agent_session_tools.embedding_store.install_hint`` emits it); a
    bare line is a command when its first token is one, otherwise prose.
    """
    text = hint.strip()
    if not text:
        return None, None
    match = _COMMAND_WITH_NOTE_RE.match(text)
    if match:
        return match.group("command"), match.group("note")
    if text.split(maxsplit=1)[0] in _COMMAND_LEADERS:
        return text, None
    return None, text
