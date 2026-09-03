"""Provider-agnostic core of the second-brain layer.

A "second brain" is wherever the learner already keeps their thinking — an
Obsidian vault, xTiles, a notebook. StudyLoop publishes **projections** of a
study plan and of today's study into it. The plan Markdown under
``STUDYLOOP_PLANS_DIR`` stays the only source of truth: nothing here, in the
CLI, or in an agent protocol writes a plan file (ADR-0010).

This module holds the contract and the two backends that need no provider code:

* :class:`SecondBrain` — the six-method protocol every backend satisfies.
* :class:`BrainDescription`, :class:`PublishResult`, :class:`PullNotesResult` —
  stable result types with fixed JSON shapes, because an agent parses them.
* :class:`NullBackend` — what ``provider: none`` returns. Inert: no plan
  lookup, no filesystem access, no log above DEBUG.
* :class:`XtilesStageOneBackend` — configured, but with no programmatic
  backend; served by documentation, prompts and an opt-in assistant skill.

Nothing in this module imports a provider module. That is what makes "with
``provider: none`` StudyLoop imports nothing" checkable with ``sys.modules``
rather than merely asserted in prose.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Providers a learner may select. ``none`` is the default and means "off".
Provider = Literal["none", "obsidian", "xtiles"]

#: Every operation a backend can be asked to perform.
Operation = Literal[
    "publish_plan",
    "publish_today",
    "publish_learning_record",
    "pull_notes",
]

PublishOperation = Literal["publish_plan", "publish_today", "publish_learning_record"]

#: The exact reason string a disabled backend reports for every operation.
NOT_CONFIGURED_DETAIL = "Second brain is not configured."

#: The exact reason string the xTiles stage-1 object reports.
XTILES_STAGE_ONE_DETAIL = "xTiles stage 1 has no programmatic backend; see docs/second-brain.md"


class SecondBrainError(Exception):
    """A controlled failure a backend raises.

    The CLI maps this to a one-line message and exit 1, never a traceback:
    every case it covers (a vault that has moved, a user note in the way, a
    plan id that does not exist) is something the learner can act on.
    """


def _reject_absolute(values: tuple[str, ...], field: str) -> list[str]:
    """Return ``values`` as a list, refusing anything that looks absolute.

    Reported paths are vault-relative POSIX strings. An absolute path in JSON
    an agent may echo, log or paste identifies the machine and its user, which
    is the leak class the public-hygiene rules exist to stop. Windows drive
    letters are rejected too, so the check does not depend on the host OS.
    """
    for value in values:
        text = str(value)
        if text.startswith("/") or text.startswith("\\") or ":\\" in text or ":/" in text:
            raise ValueError(f"{field} must contain vault-relative POSIX paths, got {text!r}")
    return [str(v) for v in values]


@dataclass(frozen=True)
class BrainDescription:
    """What a backend is, and what it can currently do.

    Nine fields, so an agent (and ``studyloop doctor``) can decide everything
    it needs from one ``studyloop brain status --json`` call: whether to offer a
    publish at wind-down (``configured and supports_publish``), whether a pull
    is possible, and where notes would land.

    ``vault_path`` is the only absolute path any ``brain`` JSON may carry: it is
    the learner's own configured path, and hiding it would make a
    "wrong vault" diagnosis impossible.
    """

    provider: str
    configured: bool
    available: bool
    supports_publish: bool
    supports_pull_notes: bool
    vault_path: str | None
    folder: str | None
    #: The EFFECTIVE Obsidian-CLI mode, not the configured one: ``use_cli:
    #: auto`` resolves to a real yes/no at call time, and the learner needs to
    #: know which they got.
    use_cli: bool
    detail: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "configured": bool(self.configured),
            "available": bool(self.available),
            "supports_publish": bool(self.supports_publish),
            "supports_pull_notes": bool(self.supports_pull_notes),
            "vault_path": self.vault_path,
            "folder": self.folder,
            "use_cli": bool(self.use_cli),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PublishResult:
    """The outcome of one publish operation.

    Three buckets rather than a boolean, because "nothing happened" has three
    different meanings the learner cares about: ``written`` (the projection
    changed), ``unchanged`` (it was already correct — republishing is free and
    leaves mtimes alone) and ``skipped`` (StudyLoop declined, with a reason).
    """

    provider: str
    operation: PublishOperation
    written: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "operation": self.operation,
            "written": _reject_absolute(self.written, "written"),
            "unchanged": _reject_absolute(self.unchanged, "unchanged"),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PullNotesResult:
    """The outcome of an explicit ``pull_notes``.

    ``found=False`` is a normal answer, not an error: a learner who has not
    written notes yet has nothing to pull, and failing there would make the
    command unusable as a routine step.
    """

    provider: str
    plan_id: str
    found: bool
    notes: str = ""
    sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "plan_id": self.plan_id,
            "found": bool(self.found),
            "notes": self.notes,
            "sources": _reject_absolute(self.sources, "sources"),
            "warnings": list(self.warnings),
        }


@runtime_checkable
class SecondBrain(Protocol):
    """The whole surface a second-brain provider must implement.

    Six methods, deliberately: three writes StudyLoop initiates, one read the
    learner initiates, and two introspection calls so nothing has to guess
    whether a provider is usable. ``tests/test_second_brain_protocol.py`` pins
    the set, so a seventh method cannot arrive without a decision.
    """

    def describe(self) -> BrainDescription: ...

    def is_available(self) -> bool: ...

    def publish_plan(self, plan_id: str) -> PublishResult: ...

    def publish_today(self) -> PublishResult: ...

    def publish_learning_record(self, plan_id: str, record_number: int) -> PublishResult: ...

    def pull_notes(self, plan_id: str) -> PullNotesResult: ...


class _InertBackend:
    """Shared body for the backends that never touch the filesystem.

    Both of them answer every operation the same way — a skipped result naming
    why — so the behaviour lives once. Neither validates or loads a plan id:
    an unconfigured feature must not read the learner's plans at all, which is
    stronger (and easier to prove) than reading them and discarding the result.
    """

    provider: str = "none"
    _detail: str = NOT_CONFIGURED_DETAIL

    def describe(self) -> BrainDescription:
        return BrainDescription(
            provider=self.provider,
            configured=False,
            available=False,
            supports_publish=False,
            supports_pull_notes=False,
            vault_path=None,
            folder=None,
            use_cli=False,
            detail=self._detail,
        )

    def is_available(self) -> bool:
        return False

    def _skipped(self, operation: PublishOperation) -> PublishResult:
        logger.debug("second brain %s: %s skipped (%s)", self.provider, operation, self._detail)
        return PublishResult(
            provider=self.provider,
            operation=operation,
            skipped=(self._detail,),
        )

    def publish_plan(self, plan_id: str) -> PublishResult:
        return self._skipped("publish_plan")

    def publish_today(self) -> PublishResult:
        return self._skipped("publish_today")

    def publish_learning_record(self, plan_id: str, record_number: int) -> PublishResult:
        return self._skipped("publish_learning_record")

    def pull_notes(self, plan_id: str) -> PullNotesResult:
        logger.debug("second brain %s: pull_notes skipped (%s)", self.provider, self._detail)
        return PullNotesResult(
            provider=self.provider,
            plan_id=plan_id,
            found=False,
            warnings=(self._detail,),
        )


class NullBackend(_InertBackend):
    """What ``provider: none`` (or no ``second_brain`` section) returns.

    Returning an object rather than ``None`` means every caller — the CLI, the
    doctor, an agent — has one code path and no "is a second brain configured?"
    branch to forget.
    """

    provider = "none"
    _detail = NOT_CONFIGURED_DETAIL


class XtilesStageOneBackend(_InertBackend):
    """``provider: xtiles`` — configured, but not programmatically reachable.

    xTiles is served in stage 1 by documentation, three tested prompts and an
    opt-in assistant skill: the learner's assistant talks to xTiles' own MCP
    connector, StudyLoop does not. Reporting ``configured=True`` with
    ``supports_publish=False`` is what stops the wind-down protocol offering a
    publish command that cannot work, while still letting ``doctor`` confirm
    the learner's choice was understood.
    """

    provider = "xtiles"
    _detail = XTILES_STAGE_ONE_DETAIL

    def describe(self) -> BrainDescription:
        base = super().describe()
        return BrainDescription(
            provider=base.provider,
            configured=True,
            available=False,
            supports_publish=False,
            supports_pull_notes=False,
            vault_path=None,
            folder=None,
            use_cli=False,
            detail=self._detail,
        )


__all__ = [
    "NOT_CONFIGURED_DETAIL",
    "XTILES_STAGE_ONE_DETAIL",
    "BrainDescription",
    "NullBackend",
    "Operation",
    "Provider",
    "PublishResult",
    "PullNotesResult",
    "SecondBrain",
    "SecondBrainError",
    "XtilesStageOneBackend",
]
