"""The core-owned drill runner (proposal §5.5) -- the runtime half of MC013 and MC015.

**R1 interface stub.** The one function body raises :class:`NotImplementedError`; R2 (argv,
regular file, clean environment) and R4 (exit classes, timeouts, streamed caps, redaction)
implement it. Only what ``tests/test_module_runner.py`` needs is declared here.

What :func:`run_phase` must guarantee, each row a contract item (§5.5):

- *Invocation*: ``argv[0]`` is one executable under ``scripts/`` in the snapshot plus
  literal arguments, spawned as a **list** with ``shell=False``. A shell operator or
  substitution in any argument is a :class:`ShellTokenError` **before** spawn (MC015).
- *MC013 at runtime*: the resolved script must be a regular file inside the snapshot's
  ``scripts/`` -- no symlink, no hardlink (``st_nlink > 1``), no device/FIFO/directory, no
  ``..`` escape and no absolute path -- else :class:`ScriptPathError`.
- *Environment*: built from scratch, never inherited: a scratch ``HOME``/XDG under
  ``Attempt.attempt_dir``, a minimal ``PATH``, and only ``STUDYLOOP_MODULE_ID``,
  ``STUDYLOOP_DRILL_ID``, ``STUDYLOOP_ATTEMPT_ID`` and ``KUBECONFIG`` (when the target is a
  kubeconfig context). Which XDG variables, and what ``PATH`` contains, is a contract gap
  R1 reports; the test enforces the proposal's words, not a list of this module's.
- *Consent*: the script digest is recomputed and ``ConsentLedger.redeem`` is called
  **immediately before** ``subprocess.Popen`` -- never earlier.
- *Timeouts*: ``timeout_seconds`` applies to this phase alone; on expiry the child is
  terminated and the result is ``ExitClass.ERROR`` with ``timed_out=True``.
- *Output*: stdout+stderr streamed with a byte cap; beyond it the stream is truncated,
  ``truncated=True`` is recorded, and the child is never left running. The proposal
  requires a cap but names no value, so ``output_byte_cap`` is a required argument here.

Spawning goes through ``subprocess.Popen`` looked up on the module at call time (not a
``from subprocess import Popen``) so that tests can observe the exact spawn arguments by
patching ``subprocess.Popen``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from studyloop.modules.attempt import RefusalError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from studyloop.modules.attempt import Attempt, Phase, PhaseResult
    from studyloop.modules.consent import Consent, ConsentLedger


class ShellTokenError(RefusalError):
    """A literal argument contained a shell operator/substitution (MC015 at runtime)."""


class ScriptPathError(RefusalError):
    """``argv[0]`` did not resolve to a regular file inside the snapshot's ``scripts/`` (MC013)."""


def run_phase(
    attempt: Attempt,
    phase: Phase,
    argv: Sequence[str],
    *,
    consent: Consent,
    ledger: ConsentLedger,
    timeout_seconds: int,
    output_byte_cap: int,
) -> PhaseResult:
    """Run one phase of ``attempt`` under the §5.5 execution model and classify the result.

    Order of operations is part of the contract: validate argv (MC015) -> resolve and
    validate the script path (MC013) -> recompute the digest -> ``ledger.redeem`` ->
    build the environment from scratch -> ``subprocess.Popen(list, shell=False, cwd=
    attempt.attempt_dir, env=...)`` -> stream with caps/timeout -> classify. Any
    :class:`~studyloop.modules.attempt.RefusalError` is raised before the spawn step.
    """
    raise NotImplementedError
