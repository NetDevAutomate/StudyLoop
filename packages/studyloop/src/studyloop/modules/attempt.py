"""Attempt identity, phases and exit classes for module drills (proposal §5.5, §5.7).

**R1 interface stub.** This module holds only the types ``tests/test_module_runner.py``
needs; it has no functions. R2-R5 add behaviour. It is the leaf of the
``attempt <- consent <- runner`` import chain and must stay free of ``subprocess`` and of
the sessions store.

Contract rows these types carry (proposal §5.5):

- *Snapshot and identity*: drill identity is ``(module id, module digest, deck id, task
  id)``; ``STUDYLOOP_DRILL_ID`` is ``<deck id>/<task id>``.
- *Working directory*: a core-created per-attempt directory (``Attempt.attempt_dir``).
- *Exit codes*: ``check`` ``0`` = passed, ``1`` = failed (task not complete), ``>= 2`` =
  error; ``setup`` any non-zero = error; a timeout is always an error.
- §5.7: a completed check records a **transient** ``practice_check`` event on the attempt
  and never an observation (R5 adds that path; R1's test for it drives today's
  ``learning/practice.py`` and is red there).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class Phase(StrEnum):
    """The three phases of a drill; each is one consented execution (§5.5)."""

    SETUP = "setup"
    CHECK = "check"
    CLEANUP = "cleanup"


class TargetKind(StrEnum):
    """``target.kind`` of a drill (§5.3 / §5.5 *Working directory* and *Kubernetes identity*)."""

    WORKDIR = "workdir"
    KUBECONFIG_CONTEXT = "kubeconfig-context"


class ExitClass(StrEnum):
    """How a finished phase is classified (§5.5 *Exit codes*).

    ``FAILED`` means *task not complete* -- the learner's work did not satisfy the check.
    ``ERROR`` means the check could not run (script error, unreachable target, timeout).
    """

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class RefusalError(Exception):
    """Base of every refusal raised **before** a child process is spawned.

    When a ``RefusalError`` propagates nothing ran, nothing was written to the attempt
    directory by a module script, and nothing was recorded.
    """


@dataclass(frozen=True)
class DrillIdentity:
    """``(module id, module digest, deck id, task id)`` -- proposal §5.5 *Snapshot and identity*."""

    module_id: str
    module_digest: str
    deck_id: str
    task_id: str


@dataclass(frozen=True)
class Attempt:
    """One attempt at one drill, bound to one immutable module snapshot.

    ``snapshot_dir`` is the module snapshot taken at ``module add``; every script a phase
    runs must be a regular file inside it (MC013). ``attempt_dir`` is the core-created
    per-attempt working directory, which also hosts the child's scratch ``HOME``/XDG dirs.
    ``kubeconfig`` is set only for ``TargetKind.KUBECONFIG_CONTEXT`` and is the
    core-written file containing exactly the disposable cluster's one context.
    """

    attempt_id: str
    drill: DrillIdentity
    snapshot_dir: Path
    attempt_dir: Path
    target: TargetKind = TargetKind.WORKDIR
    kubeconfig: Path | None = None


@dataclass(frozen=True)
class PhaseResult:
    """What one phase execution produced, after redaction and truncation.

    ``output`` is the combined stdout+stderr stream, truncated at the byte cap
    (``truncated`` records that it was) and redacted before it is persisted or delivered.
    ``exit_code`` is ``None`` when the child was terminated by the runner (timeout).
    """

    phase: Phase
    exit_class: ExitClass
    exit_code: int | None
    output: str
    truncated: bool
    timed_out: bool
    duration_seconds: float
