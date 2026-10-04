"""Per-phase, per-execution consent for module drills (proposal §5.5 *Consent*).

The contract row: consent is *per phase, per execution*. The exact argv **and the content
digest of the referenced script** are shown and confirmed, and both are re-checked
immediately before spawn. ``setup`` and ``cleanup`` each need a fresh consent every time
they run. No standing grants in v1. A consent is therefore:

- **bound** to ``(attempt, phase, argv, script digest, target)`` -- any difference at
  redemption is a :class:`ConsentMismatchError` (:class:`DigestMismatchError` when the
  difference is the script's content);
- **one-use** -- redeeming the same consent twice is a :class:`ConsentReplayedError`;
- **short-lived** -- a CLI confirmation expires :data:`CONSENT_TTL_SECONDS` (10 minutes,
  drill-runner spec / wave-1 ruling 7) after it is given: :class:`ConsentExpiredError`;
- **issued, not constructed** -- a :class:`Consent` the ledger did not issue is a
  :class:`ConsentUnknownError`. The ledger, not the immutable consent object, holds the
  redeemed/issued state, so a forged object cannot carry its own "unused" flag.

The ledger lives in the process that runs the phase (``studyloop drill``): one invocation
shows the prompt, issues the consent, and redeems it at spawn. There is no persistence and
no cross-process consent -- the web surface exposes no ``--yes`` equivalent in v1 (§7).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from studyloop.modules.attempt import Attempt, Phase, RefusalError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class ConsentRefusedError(RefusalError):
    """Base of every consent refusal; raised before spawn, so nothing ran."""


class ConsentReplayedError(ConsentRefusedError):
    """The consent was already redeemed once; a second redemption is refused."""


class ConsentMismatchError(ConsentRefusedError):
    """What is about to run differs from what was consented to (attempt, phase, argv, target)."""


class DigestMismatchError(ConsentMismatchError):
    """The referenced script's content digest differs from the one shown at consent time."""


class ConsentExpiredError(ConsentRefusedError):
    """The consent is older than :data:`CONSENT_TTL_SECONDS` (spec: 10 minutes, single use)."""


class ConsentUnknownError(ConsentRefusedError):
    """The consent object was never issued by this ledger (forged or from another process)."""


#: A CLI confirmation expires this long after it is given (drill-runner spec, ruling 7).
CONSENT_TTL_SECONDS = 10 * 60


def consent_target(attempt: Attempt) -> str:
    """The target identity a consent is bound to.

    The attempt directory for ``workdir``; the core-written kubeconfig path for a
    ``kubeconfig-context`` target (it holds exactly the disposable cluster's one context,
    §5.5 *Kubernetes identity*).
    """
    if attempt.kubeconfig is not None:
        return str(attempt.kubeconfig)
    return str(attempt.attempt_dir)


def describe_consent(
    attempt: Attempt, phase: Phase, argv: Sequence[str], *, script_digest: str
) -> str:
    """The text shown to the learner before confirming: phase, target, exact argv, digest,
    and what consenting means (M1 Q2/Q7: hygiene, not a sandbox).

    Every argv item is printed verbatim on its own line so a learner can see an argument
    that *looks* like a flag but is not, and the digest is the one the runner re-checks at
    spawn -- what is shown is exactly what will run or nothing runs.
    """
    lines = [
        f"Drill phase: {phase.value}",
        f"Drill:       {attempt.drill.module_id} {attempt.drill.drill_id}",
        f"Target:      {attempt.target.value} {consent_target(attempt)}",
        "Command (argv, no shell):",
    ]
    lines.extend(f"  [{index}] {item}" for index, item in enumerate(argv))
    lines.append(f"Script sha256: {script_digest}")
    lines.append(
        "This script runs with YOUR privileges on this machine -- it can read and write "
        "anything you can. StudyLoop runs it without a shell, with a clean environment, in a "
        "scratch directory, with capped and redacted output, and stops it on timeout; that is "
        "hygiene, not a sandbox (a process that detaches itself survives the stop)."
    )
    if phase is Phase.CLEANUP:
        lines.append("This phase is destructive: it deletes what the attempt created.")
    return "\n".join(lines)


@dataclass(frozen=True)
class Consent:
    """A confirmed, one-use permission to run exactly one phase of one attempt.

    ``argv`` is the exact argument vector that was displayed (``argv[0]`` is the
    snapshot-relative ``scripts/...`` path). ``script_digest`` is the hex SHA-256 of the
    referenced script's bytes at display time. ``target`` is the attempt's target
    identity (the attempt directory for ``workdir``; the disposable cluster's kubeconfig
    for ``kubeconfig-context``).
    """

    consent_id: str
    attempt_id: str
    phase: Phase
    argv: tuple[str, ...]
    script_digest: str
    target: str


@dataclass
class _Issued:
    consent: Consent
    issued_at: float
    redeemed: bool = False


@dataclass
class ConsentLedger:
    """Issues consents after display and redeems each exactly once immediately before spawn.

    The ledger is the one place that knows which consents have been issued and redeemed, so
    replay and forgery detection do not depend on the (immutable) :class:`Consent` object
    itself. ``clock`` is injectable so expiry is testable without sleeping.
    """

    clock: Callable[[], float] = time.monotonic
    ttl_seconds: float = CONSENT_TTL_SECONDS
    _issued: dict[str, _Issued] = field(default_factory=dict, repr=False)

    def issue(
        self,
        attempt: Attempt,
        phase: Phase,
        argv: Sequence[str],
        *,
        script_digest: str,
    ) -> Consent:
        """Record a consent the learner has just confirmed and return it.

        Called only *after* the exact ``argv`` and ``script_digest`` were displayed.
        """
        consent = Consent(
            consent_id=str(uuid.uuid4()),
            attempt_id=attempt.attempt_id,
            phase=phase,
            argv=tuple(argv),
            script_digest=script_digest,
            target=consent_target(attempt),
        )
        self._issued[consent.consent_id] = _Issued(consent=consent, issued_at=self.clock())
        return consent

    def redeem(
        self,
        consent: Consent,
        *,
        attempt: Attempt,
        phase: Phase,
        argv: Sequence[str],
        script_digest: str,
    ) -> None:
        """Consume ``consent`` for exactly this execution, or raise a :class:`ConsentRefusedError`.

        Order: unknown -> replayed -> expired -> binding (attempt, phase, argv, target) ->
        digest. The consent is marked redeemed **before** the binding checks so that a
        mismatching redemption also burns it: a consent is one chance, not one success.
        """
        record = self._issued.get(consent.consent_id)
        if record is None or record.consent != consent:
            raise ConsentUnknownError(
                f"consent {consent.consent_id} was not issued by this ledger; refusing to run"
            )
        if record.redeemed:
            raise ConsentReplayedError(
                f"consent {consent.consent_id} for {consent.phase.value} was already used; "
                "each phase execution needs a fresh confirmation"
            )
        record.redeemed = True
        age = self.clock() - record.issued_at
        if age > self.ttl_seconds:
            raise ConsentExpiredError(
                f"consent {consent.consent_id} is {age:.0f}s old; a confirmation expires after "
                f"{self.ttl_seconds:.0f}s -- confirm again"
            )
        if consent.attempt_id != attempt.attempt_id:
            raise ConsentMismatchError(
                f"consent is for attempt {consent.attempt_id}, not {attempt.attempt_id}"
            )
        if consent.phase is not phase:
            raise ConsentMismatchError(
                f"consent is for the {consent.phase.value} phase, not {phase.value}; "
                "setup, check and cleanup are each consented to separately"
            )
        if consent.argv != tuple(argv):
            raise ConsentMismatchError(
                f"consent was given for argv {list(consent.argv)!r}, not {list(argv)!r}"
            )
        target = consent_target(attempt)
        if consent.target != target:
            raise ConsentMismatchError(
                f"consent was given for target {consent.target!r}, not {target!r}"
            )
        if consent.script_digest != script_digest:
            raise DigestMismatchError(
                f"script content changed since consent: shown sha256 {consent.script_digest}, "
                f"now {script_digest}; aborting before spawn"
            )
