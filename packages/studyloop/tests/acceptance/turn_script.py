"""Versioned turn-script format for the scripted learner actor.

``ACTOR=scripted`` (B1's CI-safe default, D-16 scoping) drives the mentor
through a deterministic, ordered sequence of learner turns — no LLM on the
learner side. A turn script is the data that sequence comes from: plain
data, loaded and validated by :func:`load_turn_script`, never executed code.

The format is versioned (``version``) and STRICT: an unknown top-level or
per-turn field is a loud :class:`TurnScriptError`, not a silently-ignored
key — a typo'd field name in a hand-written script must fail the run that
defines it, not the first run that happens to need the field it meant to
set.

``expect_contains``/``expect_not_contains`` are RESERVED: the fields are
parsed (so they round-trip and a future executor's shape is already
settled), but nothing in this lane evaluates them yet, so a non-empty value
is rejected loudly rather than silently accepted — the exact
strict-unknown-field failure mode this loader otherwise guards against,
arriving through a field that IS known. A later lane that wires an executor
through the field should remove this guard alongside adding one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The only format version this loader understands. A future incompatible
#: format bumps this and the loader rejects anything else by name (never by
#: silently misinterpreting old fields under a new shape).
SUPPORTED_VERSION = 1

_TURN_FIELDS = frozenset({"prompt", "expect_contains", "expect_not_contains"})
_SCRIPT_FIELDS = frozenset({"version", "turns"})


class TurnScriptError(ValueError):
    """Raised for a malformed, unversioned, or unknown-field turn script."""


@dataclass(frozen=True, slots=True)
class Turn:
    """One scripted learner turn."""

    prompt: str
    expect_contains: tuple[str, ...] = field(default_factory=tuple)
    expect_not_contains: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class TurnScript:
    """An ordered, versioned sequence of scripted learner turns."""

    version: int
    turns: tuple[Turn, ...]


def _require_dict(value: Any, *, what: str) -> dict:
    if not isinstance(value, dict):
        raise TurnScriptError(f"{what} must be a mapping, got {type(value).__name__}")
    return value


def load_turn_script(data: dict) -> TurnScript:
    """Validate and parse a raw (e.g. JSON-decoded) turn-script mapping.

    Rejects: missing/unsupported ``version``, any unknown top-level or
    per-turn field, a non-list ``turns``, an empty script, and a turn
    missing its required ``prompt``.
    """
    _require_dict(data, what="turn script")

    unknown_top = set(data) - _SCRIPT_FIELDS
    if unknown_top:
        raise TurnScriptError(f"unknown turn-script field(s): {sorted(unknown_top)}")

    if "version" not in data:
        raise TurnScriptError("turn script is missing required field 'version'")
    version = data["version"]
    if version != SUPPORTED_VERSION:
        raise TurnScriptError(
            f"unsupported turn-script version {version!r}; this loader supports "
            f"version {SUPPORTED_VERSION} only"
        )

    raw_turns = data.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise TurnScriptError("turn script must have a non-empty 'turns' list")

    turns: list[Turn] = []
    for index, raw_turn in enumerate(raw_turns):
        _require_dict(raw_turn, what=f"turns[{index}]")
        unknown_turn = set(raw_turn) - _TURN_FIELDS
        if unknown_turn:
            raise TurnScriptError(f"unknown field(s) on turns[{index}]: {sorted(unknown_turn)}")
        if "prompt" not in raw_turn or not isinstance(raw_turn["prompt"], str):
            raise TurnScriptError(f"turns[{index}] is missing a string 'prompt'")
        for reserved_field in ("expect_contains", "expect_not_contains"):
            if raw_turn.get(reserved_field):
                raise TurnScriptError(
                    f"turns[{index}]: '{reserved_field}' is reserved -- no executor "
                    "evaluates it yet (see docs/acceptance-testing.md); leave it "
                    "unset until one does"
                )
        turns.append(
            Turn(
                prompt=raw_turn["prompt"],
                expect_contains=tuple(raw_turn.get("expect_contains", ())),
                expect_not_contains=tuple(raw_turn.get("expect_not_contains", ())),
            )
        )

    return TurnScript(version=version, turns=tuple(turns))
