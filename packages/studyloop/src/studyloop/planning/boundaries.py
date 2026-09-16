"""What the plan integration deliberately does not automate.

Issue #7 drew this line on purpose ("Out of Scope"; the plan-application-seam
proposal's "Non-goals"): an active plan biases the ``now`` recommendation and
gives agents lifecycle tools, but it never runs the session. Each entry below
is the lead phrase of one bullet in ``docs/study-plans.md``'s "Deliberately
not automatic" list and one clause of the installer's boundary sentence;
``tests/test_docs_plan_integration_contract.py`` pins both to this tuple, so
the two public statements cannot drift from each other or from this list
without the constant moving with them. The tuple is a shared *statement* of
the boundary, not proof of it: the behavioural evidence is the named tests
(``test_planning_launch_creates_no_plan_and_no_plan_id``,
``test_multiple_ready_active_plans_are_valid``, the no-active golden, …).

Every entry is an *automation* the product refuses — the learner-facing
reading of issue #7's out-of-scope list. Input-path facts (the manual form's
brain dump is saved, not decomposed; the Web door carries a subject) are not
automations and live beside the list in the doc, not in it (council review 5).

The phrases are deliberately verbs: each names something StudyLoop does
**not** do, in the words the learner-facing doc uses.
"""

from __future__ import annotations

from typing import Final

#: Ordered as the doc lists them: the live-session boundary first (the one
#: issue #7 calls out as a separate future feature), then the three
#: session-driven automations, then the two things a plan must never become,
#: then the one thing StudyLoop never schedules on the learner's behalf.
NOT_AUTOMATIC: Final[tuple[str, ...]] = (
    "bind a live study session to a plan",
    "run checkpoints from session events",
    "complete milestones from study evidence",
    "enforce one active plan",
    "turn a plan into a filter",
    "schedule recurring planning sessions",
)

__all__ = ["NOT_AUTOMATIC"]
