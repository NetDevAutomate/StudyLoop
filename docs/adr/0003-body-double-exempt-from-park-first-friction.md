# ADR-0003 — Body Double is exempt from park-first friction

- **Status**: Accepted (2026-09-05 — implemented and shipped; accepted retrospectively during the body-double-own-agent-picker reconciliation)
- **Date**: 2026-07-25
- **Change**: `openspec/changes/body-double-own-agent-picker`
- **Deciders**: repo owner

## Context

The web-ui spec requires deliberate friction on starting a study session:

> **Requirement: Starting a 4th topic requires parking one first** — when
> `GET /api/backlog` reports `active_count >= max_active` and the learner
> starts a session on a topic not already active, the start is intercepted by
> an in-page `.park-first-overlay` listing active topics; choosing one calls
> `POST /api/backlog/demote`, then the start proceeds.

Implemented in `sessionTimer().startSession()` — the backlog check runs
*before* the POST and returns early to show the overlay.

The rule exists to protect against ADHD topic-sprawl: three concurrent
learning threads is the cap, and a fourth costs you an explicit trade.

Body Double is not a learning thread. Its "topic" is whatever you are
actually doing — "reply to Ahmed's email", "unblock the Glue job", "tidy the
kitchen". Routing that through the 3-topic gate would (a) demand you park a
real study topic to answer an email, and (b) if Body Double reuses
`/api/session/start` with the activity as `topic` (ADR-0001), teach the
backlog that "reply to Ahmed's email" is a study topic competing for one of
three slots.

## Decision

Body Double starts **skip** the park-first check entirely. `bodyDoubleSession()`
POSTs `/api/session/start` directly; it never calls `GET /api/backlog` and never
renders `.park-first-overlay`.

The friction stays exactly as-is for Study Session starts. The web-ui spec
requirement is narrowed to say so explicitly — "the learner starts a *study*
session … from the study-session picker" — rather than left ambiguous.

## Alternatives considered

**Apply the friction to Body Double too.** Rejected: it inverts the rule's
purpose. Friction is meant to stop you *accumulating study threads*. Applying
it to "I want someone to sit with me while I do this chore" punishes the
support mechanism, and PDA sensitivity means an unnecessary gate at the moment
of starting is a real risk of not starting at all.

**A separate, looser cap for body-double sessions.** Rejected as premature:
there is no evidence body-double sprawl is a problem, and it would add a
second counter and a second overlay for a hypothetical.

**Track body-double activity in the backlog but never gate on it.** Rejected:
`/api/backlog` `active_count` is the input to the gate. Writing rows that are
invisible to the count means two notions of "active", which is the kind of
divergence that later reads as a bug.

## Consequences

- Body Double always starts immediately (subject only to the HTTP 409
  single-active-session guard).
- Because Body Double still writes a `study_sessions` row (ADR-0001), the
  activity text will appear in session history and *may* surface in
  struggle/mastery analytics. That is the wart recorded in ADR-0001, not a new
  one — but it is the reason a future session-type discriminator would be
  worth introducing.
- The park-first requirement becomes narrower and therefore more precisely
  testable: an assertion that a Body Double start issues **no**
  `GET /api/backlog` request is now a valid regression test.

## Verification

- Route-intercept test: three topics active, start a Body Double session,
  assert no `/api/backlog` request and no `.park-first-overlay` in the DOM.
- Existing park-first study-session test must still pass unchanged.
