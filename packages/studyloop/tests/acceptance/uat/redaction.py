"""The UAT redacted-summary generator (council D-22 / kimi F12).

A private evidence bundle (council D-14's full schema) is never itself
publishable: it can carry a learner's real transcripts, screenshots,
absolute home paths, and (if a caller was careless upstream) a stray key.
This module produces the ONE thing that IS allowed into ``releases/``: a
redacted summary containing only allowlisted, structured fields.

The redaction rule list is VERSIONED AND HASH-PINNED exactly like the
rubric (:mod:`acceptance.uat.rubric`) -- :func:`load_redaction_rules`
computes the rules file's sha256 and rejects it, by raising
:class:`RedactionRulesTamperedError`, unless that hash matches what the
registry has pinned for the file's own declared ``version``. Editing the
rules file in place, without bumping ``version`` and registering the new
hash, is exactly the tamper this loader exists to catch.

The allowlist alone is never trusted on its own: :func:`redact_summary`
additionally scans every field VALUE (allowlisted or not) for forbidden
content -- a home path, a key-shaped token -- before returning. A positive
control belongs in every caller's test suite: prove the detector
(:func:`contains_forbidden_content`) actually flags dirty input BEFORE
relying on it to certify redacted output as clean.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

_DATA_DIR = Path(__file__).parent / "data"
DEFAULT_RULES_PATH = _DATA_DIR / "redaction_rules_v1.yaml"
DEFAULT_REGISTRY_PATH = _DATA_DIR / "redaction_registry.json"


class RedactionRulesError(Exception):
    """Base class for every redaction-rules loading failure."""


class RedactionRulesUnregisteredVersionError(RedactionRulesError):
    """The rules file names a version the registry has no pinned hash for."""


class RedactionRulesTamperedError(RedactionRulesError):
    """The rules file's sha256 does not match its registered, pinned hash.

    This is what an edit made in place -- without bumping ``version`` AND
    registering a new hash -- looks like to the loader (council D-22/kimi
    F12: hash-pinned exactly like the rubric).
    """


class RedactionLeakError(RedactionRulesError):
    """A redacted summary still carries forbidden content after filtering.

    Raised naming every violation found -- the allowlist is filtered
    first, but its output is still scanned before being trusted.
    """


@dataclass(frozen=True, slots=True)
class RedactionRules:
    """One pinned, versioned redaction-rules document."""

    version: int
    content_hash: str
    allowed_fields: frozenset[str]


def sha256_of_text(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_redaction_rules(
    rules_path: Path = DEFAULT_RULES_PATH,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> RedactionRules:
    """Load and hash-verify one redaction-rules document.

    Raises :class:`RedactionRulesUnregisteredVersionError` if the file's
    ``version`` has no entry in the registry at all, and
    :class:`RedactionRulesTamperedError` if it does, but the file's current
    sha256 no longer matches the pinned one.
    """
    raw = rules_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    version = data["version"]
    digest = sha256_of_text(raw)

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    expected = registry.get(str(version))
    if expected is None:
        raise RedactionRulesUnregisteredVersionError(
            f"redaction rules version {version} has no pinned hash in {registry_path}"
        )
    if expected != digest:
        raise RedactionRulesTamperedError(
            f"{rules_path} does not match its pinned hash for version {version} "
            f"(expected {expected}, got {digest}) -- an edited-in-place rules "
            "file must bump 'version' and register a new hash, never reuse an "
            "old one for changed content"
        )
    return RedactionRules(
        version=version,
        content_hash=digest,
        allowed_fields=frozenset(data["allowed_fields"]),
    )


# ---------------------------------------------------------------------------
# Forbidden-content detection
# ---------------------------------------------------------------------------
#
# A conservative, narrowly-scoped set of patterns a redacted summary must
# never carry -- this module's job is the UAT redaction allowlist, not a
# general-purpose secrets scanner (detect-secrets already owns that job for
# the repository as a whole).

_HOME_PATH_PATTERN = re.compile(r"(?:^|[\s\"'=:])(/(?:Users|home)/[^\s\"']+)")
_KEY_LIKE_PATTERN = re.compile(
    r"\b(sk-[A-Za-z0-9_-]{8,}|sk-ant-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{8,})\b"
)


def _iter_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for v in value:
            yield from _iter_strings(v)


def contains_forbidden_content(value: object) -> list[str]:
    """Return every forbidden-pattern violation found in ``value``.

    Empty when clean. Walks nested dicts/lists/tuples so a violation buried
    inside a nested ``journeys`` or ``per_criterion_scores`` structure is
    still caught, not only a top-level string field.
    """
    violations: list[str] = []
    for text in _iter_strings(value):
        for match in _HOME_PATH_PATTERN.finditer(text):
            violations.append(f"home path leaked: {match.group(1)!r}")
        for match in _KEY_LIKE_PATTERN.finditer(text):
            violations.append(f"key-like token leaked: {match.group(1)!r}")
    return violations


def redact_summary(
    bundle_summary: Mapping[str, object], rules: RedactionRules
) -> dict[str, object]:
    """Filter ``bundle_summary`` down to ``rules.allowed_fields``, then verify.

    The allowlist alone is never trusted: even an allowlisted field's VALUE
    is scanned for forbidden content, so a badly-formed ``arbitration_note``
    that happens to quote a home path or a key is still caught. Raises
    :class:`RedactionLeakError`, naming every violation, rather than
    shipping one silently.
    """
    filtered = {k: v for k, v in bundle_summary.items() if k in rules.allowed_fields}
    violations = contains_forbidden_content(filtered)
    if violations:
        raise RedactionLeakError(f"redacted summary still carries forbidden content: {violations}")
    return filtered


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_RULES_PATH",
    "RedactionLeakError",
    "RedactionRules",
    "RedactionRulesError",
    "RedactionRulesTamperedError",
    "RedactionRulesUnregisteredVersionError",
    "contains_forbidden_content",
    "load_redaction_rules",
    "redact_summary",
    "sha256_of_text",
]
