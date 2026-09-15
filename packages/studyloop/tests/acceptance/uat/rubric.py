"""The UAT sign-off rubric loader (council D-22/kimi F13, "never gate at the
point estimate").

The rubric is a single markdown+YAML document (YAML frontmatter, prose
body): criteria, scale anchors, the evidence each criterion cites, and an
explicit ``reject_if`` list -- failure conditions that fail a run
independent of what a weighted average of per-criterion scores would
otherwise say.

Hash-pinned exactly like :mod:`acceptance.uat.redaction`'s rules file, and
for the same reason: "the rubric version+hash used by a run enters the
manifest BEFORE grading; edits = a new version, and the loader rejects an
edited-in-place file by hash." :func:`load_rubric` computes the file's
sha256 and rejects it, raising :class:`RubricTamperedError`, unless that
hash matches what :data:`DEFAULT_REGISTRY_PATH` (or a caller-given
registry) has pinned for the file's own declared ``version``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

_DATA_DIR = Path(__file__).parent / "data"
DEFAULT_RUBRIC_PATH = _DATA_DIR / "rubric_v1.md"
DEFAULT_REGISTRY_PATH = _DATA_DIR / "rubric_registry.json"

#: YAML frontmatter delimited by a leading and trailing ``---`` line, the
#: same shape used across the ecosystem (Jekyll, Hugo, ...) -- chosen so a
#: contributor already knows how to read/edit this file.
_FRONTMATTER_PATTERN = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)


class RubricError(Exception):
    """Base class for every rubric loading failure."""


class RubricFormatError(RubricError):
    """The rubric file has no valid YAML frontmatter block."""


class RubricVersionUnregisteredError(RubricError):
    """The rubric file names a version the registry has no pinned hash for."""


class RubricTamperedError(RubricError):
    """The rubric file's sha256 does not match its registered, pinned hash --
    an edit made in place without bumping ``version`` AND registering a new
    hash (council D-22/kimi F13)."""


@dataclass(frozen=True, slots=True)
class Criterion:
    """One rubric criterion: a prompt, a scale, anchors, and cited evidence."""

    id: str
    prompt: str
    scale: tuple[int, ...]
    anchors: Mapping[int, str]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Rubric:
    """One pinned, versioned rubric document."""

    version: int
    content_hash: str
    criteria: tuple[Criterion, ...]
    reject_if: tuple[str, ...]
    body: str


def sha256_of_text(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _split_frontmatter(raw: str) -> tuple[str, str]:
    match = _FRONTMATTER_PATTERN.match(raw)
    if not match:
        raise RubricFormatError("rubric file has no leading '---'-delimited YAML frontmatter block")
    return match.group(1), raw[match.end() :]


def _parse_criteria(raw_criteria: list[dict]) -> tuple[Criterion, ...]:
    criteria = []
    for entry in raw_criteria:
        criteria.append(
            Criterion(
                id=entry["id"],
                prompt=entry["prompt"],
                scale=tuple(entry["scale"]),
                anchors=dict(entry.get("anchors", {})),
                evidence=tuple(entry.get("evidence", [])),
            )
        )
    return tuple(criteria)


def load_rubric(
    rubric_path: Path = DEFAULT_RUBRIC_PATH,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> Rubric:
    """Load and hash-verify one rubric document.

    Raises :class:`RubricFormatError` if the frontmatter block is missing,
    :class:`RubricVersionUnregisteredError` if the declared ``version`` has
    no registry entry, and :class:`RubricTamperedError` if it does, but the
    file's current sha256 no longer matches the pinned one.
    """
    raw = rubric_path.read_text(encoding="utf-8")
    frontmatter_raw, body = _split_frontmatter(raw)
    data = yaml.safe_load(frontmatter_raw)
    version = data["version"]
    digest = sha256_of_text(raw)

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    expected = registry.get(str(version))
    if expected is None:
        raise RubricVersionUnregisteredError(
            f"rubric version {version} has no pinned hash in {registry_path}"
        )
    if expected != digest:
        raise RubricTamperedError(
            f"{rubric_path} does not match its pinned hash for version {version} "
            f"(expected {expected}, got {digest}) -- an edited-in-place rubric "
            "must bump 'version' and register a new hash, never reuse an old "
            "one for changed content"
        )

    return Rubric(
        version=version,
        content_hash=digest,
        criteria=_parse_criteria(data.get("criteria", [])),
        reject_if=tuple(data.get("reject_if", [])),
        body=body,
    )


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_RUBRIC_PATH",
    "Criterion",
    "Rubric",
    "RubricError",
    "RubricFormatError",
    "RubricTamperedError",
    "RubricVersionUnregisteredError",
    "load_rubric",
    "sha256_of_text",
]
