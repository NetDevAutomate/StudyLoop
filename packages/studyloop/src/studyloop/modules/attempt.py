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

    @property
    def drill_id(self) -> str:
        """``STUDYLOOP_DRILL_ID``: ``<deck id>/<task id>`` (§5.5)."""
        return f"{self.deck_id}/{self.task_id}"


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
class OutputCaps:
    """Streamed-output caps the runner enforces while the child runs (spec, ruling 2).

    ``stdout_bytes`` and ``stderr_bytes`` bound each stream separately; ``lines`` bounds the
    two streams together. Hitting any cap terminates the child, records ``truncated`` and
    classes the phase ``ERROR`` naming the cap (ruling 3) -- a flooding check is not a
    trustworthy pass.
    """

    stdout_bytes: int = 64 * 1024
    stderr_bytes: int = 16 * 1024
    lines: int = 2_000


#: The spec's values: 64 KiB stdout, 16 KiB stderr, 2,000 lines in total.
DEFAULT_CAPS = OutputCaps()


@dataclass(frozen=True)
class PhaseResult:
    """What one phase execution produced, after redaction and truncation.

    ``stdout`` and ``stderr`` are the captured streams, cut at their caps (``truncated``
    records that one was hit and ``cap_hit`` names which: ``"stdout"``, ``"stderr"`` or
    ``"lines"``) and redacted by the secret detector before anything is persisted, shown or
    delivered. ``exit_code`` is ``None`` when the runner stopped the child (timeout or cap)
    before it exited on its own. ``message`` is the one-line human reading of the outcome
    the CLI prints and the mentor hop forwards verbatim.
    """

    phase: Phase
    exit_class: ExitClass
    exit_code: int | None
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool
    duration_seconds: float
    cap_hit: str | None = None
    message: str = ""

    @property
    def output(self) -> str:
        """stdout followed by stderr -- the combined transient evidence."""
        return self.stdout + self.stderr
