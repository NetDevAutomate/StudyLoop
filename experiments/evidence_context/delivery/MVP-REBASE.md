# Delivery rebaseline, 2026-09-06

The user raised the cost and duration of the overnight run and asked to ship what
already exists or an improved MVP. The immediate work is a bounded reliability
release audit, not continuation through every open P01-P15 requirement.

The candidate is on `codex/session-memory-mvp`, based on current main `f945d057`
with the three pre-research capture/repair/sync commits. Its `MVP-RELEASE.md`
records the exact scope, verified behaviour, exclusions and finite release gates.
No database redesign or new runtime feature was added during the audit.

Preserve this research branch, all runnable stages and saved learning exercises.
The unfinished schema-47 reconciliation changes are retained uncommitted; they
are not part of the release candidate. Do not interpret earlier STATUS/GOAL
continuation instructions as a request to resume the unbounded implementation.
The original broader objective and evidence remain historical context, not a
claim that the reliability candidate satisfies all of those requirements.

The candidate intentionally does not claim enforced cross-machine scope,
propagated forgetting or validated decision arbitration. Those features must be
chosen explicitly for a later product increment with a new delivery boundary.
