"""What the plan integration deliberately does not automate.

Issue #7 drew this line on purpose ("Out of Scope"; the plan-application-seam
proposal's "Non-goals"): an active plan biases the ``now`` recommendation and
gives agents lifecycle tools, but it never runs the session. Each entry below
is the lead phrase of one bullet in ``docs/study-plans.md``'s "Deliberately
not automatic" list and one clause of the installer's boundary sentence;
``tests/test_docs_plan_integration_contract.py`` pins both to this tuple so
the public statement cannot claim more — or less — automation than the
product has without this constant moving with it.

The phrases are deliberately verbs: each names something StudyLoop does
**not** do, in the words the learner-facing doc uses.
"""

from __future__ import annotations

from typing import Final

#: Ordered as the doc lists them: the live-session boundary first (the one
#: issue #7 calls out as a separate future feature), then the three
#: session-driven automations, then the two things a plan must never become.
NOT_AUTOMATIC: Final[tuple[str, ...]] = (
    "bind a live study session to a plan",
    "run checkpoints from session events",
    "complete milestones from study evidence",
    "enforce one active plan",
    "turn a plan into a filter",
    "structure the manual form's brain dump",
)

__all__ = ["NOT_AUTOMATIC"]
