"""Data model for doctor check results."""

from __future__ import annotations

from dataclasses import dataclass

VALID_STATUSES = frozenset({"pass", "warn", "fail", "info"})
VALID_CATEGORIES = frozenset(
    {"core", "database", "config", "agents", "deps", "voice", "updates", "eval"}
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Single diagnostic check result. This is the contract for --json output."""

    category: str
    name: str
    status: str
    message: str
    fix_hint: str
    fix_auto: bool

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            msg = f"status must be one of {VALID_STATUSES}, got {self.status!r}"
            raise ValueError(msg)
        if self.category not in VALID_CATEGORIES:
            msg = f"category must be one of {VALID_CATEGORIES}, got {self.category!r}"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "category": self.category,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "fix_hint": self.fix_hint,
            "fix_auto": self.fix_auto,
        }
