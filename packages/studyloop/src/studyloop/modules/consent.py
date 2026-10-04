"""Per-phase, per-execution consent for module drills (proposal §5.5 *Consent*).

**R1 interface stub.** Both method bodies raise :class:`NotImplementedError`; R3 implements
them. Only what ``tests/test_module_runner.py`` needs is declared here.

The contract row: consent is *per phase, per execution*. The exact argv **and the content
digest of the referenced script** are shown and confirmed, and both are re-checked
immediately before spawn. ``setup`` and ``cleanup`` each need a fresh consent every time
they run. No standing grants in v1. A consent is therefore:

- **bound** to ``(attempt, phase, argv, script digest, target)`` -- any difference at
  redemption is a :class:`ConsentMismatchError` (:class:`DigestMismatchError` when the
  difference is the script's content);
- **one-use** -- redeeming the same consent twice is a :class:`ConsentReplayedError`.

The proposal names an *expiry* only for the v1.1 web challenge (§5.5, §7); whether a CLI
consent expires is not specified, so this stub carries no clock. R3 reports it if needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from studyloop.modules.attempt import Attempt, Phase, RefusalError

if TYPE_CHECKING:
    from collections.abc import Sequence


class ConsentRefusedError(RefusalError):
    """Base of every consent refusal; raised before spawn, so nothing ran."""


class ConsentReplayedError(ConsentRefusedError):
    """The consent was already redeemed once; a second redemption is refused."""


class ConsentMismatchError(ConsentRefusedError):
    """What is about to run differs from what was consented to (attempt, phase, argv, target)."""


class DigestMismatchError(ConsentMismatchError):
    """The referenced script's content digest differs from the one shown at consent time."""


@dataclass(frozen=True)
class Consent:
    """A confirmed, one-use permission to run exactly one phase of one attempt.

    ``argv`` is the exact argument vector that was displayed (``argv[0]`` is the
    snapshot-relative ``scripts/...`` path). ``script_digest`` is the hex SHA-256 of the
    referenced script's bytes at display time. ``target`` is the attempt's target
    identity (the attempt directory for ``workdir``; the disposable cluster's context name
    for ``kubeconfig-context``).
    """

    consent_id: str
    attempt_id: str
    phase: Phase
    argv: tuple[str, ...]
    script_digest: str
    target: str


@dataclass
class ConsentLedger:
    """Issues consents after display and redeems each exactly once immediately before spawn.

    The ledger is the one place that knows which consents have been redeemed, so replay
    detection does not depend on the (immutable) :class:`Consent` object itself.
    """

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
        raise NotImplementedError

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

        Raises :class:`ConsentReplayedError` if already redeemed, :class:`DigestMismatchError`
        if the freshly computed ``script_digest`` differs, and :class:`ConsentMismatchError`
        if attempt, phase, argv or target differ. On success the consent is marked redeemed
        before returning.
        """
        raise NotImplementedError
