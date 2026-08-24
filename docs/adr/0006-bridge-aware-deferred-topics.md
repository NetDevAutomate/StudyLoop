# ADR-0006 — Bridge-aware deferred topics, behind a testable 0.1.0 boundary

- **Status**: Proposed
- **Date**: 2026-08-24
- **Change**: `reviews/0.1.0-SCOPE-DECISION.md` (§1, §5)
- **Deciders**: repo owner

## Context

Two linked decisions from the 0.1.0 scope record deserve to outlive it.

**First, the release needed a boundary.** There is no release pressure: the
stated goal is a strong, complete 0.1.0 for an open-source tool aimed at
neurodiverse learners, in preference to a fast one. That preference has a
failure mode — values-driven scope has no natural stopping point, because
there is always one more thing the values argue for, and the owner's stated
failure mode is opening many tasks and closing none. Without a *testable*
definition of "complete", 0.1.0 would never close.

**Second, the deferred-topics surface is the wrong shape.** Deferred and
struggled topics currently accumulate as a visible pile: `board_columns`
lives in `parking.py`, so the parking lot **is** a kanban board of
unfinished business. For this product's audience, a standing wall of
deferred topics is not neutral UI. The question is what replaces it —
and, just as important, what must *not* replace it.

## Decision

### 1. The 0.1.0 completeness boundary

**0.1.0 is complete when three testable clauses hold:**

1. **Every documented claim is true.** No doc promises behaviour the
   product lacks.
2. **No dead ends in the web flow.** No state a user can reach and not
   leave.
3. **The suite is green with zero warnings**, under a named-exclusions
   allowlist — every exclusion names the specific warning or test it
   covers; blanket filters do not count.

Anything that is neither a documented promise nor a dead end is **0.2.0**,
unless it is explicitly added as a named scope choice with its reasons
recorded.

### 2. Bridge-aware deferred topics (0.2.0)

Replace the visible pile of deferred topics with **contextual,
competence-first reintroduction**: the agent notices that a topic the
learner is currently handling well is structurally adjacent to one they
deferred, and brings the deferred topic in as an *application* of present
understanding — never as a return to a failure.

Four design constraints, each recorded because ignoring it is a way to get
this wrong:

1. **Not displayed, but knowable on demand.** A system that silently holds
   unfinished business and decides for itself when to raise it is
   *unpredictable*, and unpredictability is its own ASD stressor. Pull, not
   push — `studyloop struggles` is already the right shape. Removing agency
   to remove anxiety trades one discomfort for another.
2. **Bad adjacency is worse than silence.** A non-sequitur that also
   reminds the learner of a failure is the worst outcome. No structural
   edge, no mention.
3. **Asymmetric visibility — hide the debt, show the payoff.** Closure must
   stay visible, or the feature removes the anxiety and the dopamine
   together. The 90-day heatmap, `studyloop wins`, and streaks are
   asymmetric *by construction*: they can only show data when something
   went right.
4. **A kanban board is the wrong shape — and already exists.**
   `board_columns` lives in `parking.py`: the parking lot is a kanban
   board, and it is precisely the artefact being moved away from. A
   cheerful board with different columns is the same wall.

## Alternatives considered

**No explicit boundary — polish until it feels done.** Rejected: with no
release pressure and values that always argue for one more improvement,
"feels done" never arrives. The boundary exists *because* nothing external
forces one.

**Keep the deferred-topics board, restyled.** Rejected under constraint 4:
different columns and friendlier labels do not change what the surface is —
a permanently visible wall of unfinished business.

**Add a discard affordance now (`park-first-delete` / `park-first-undo`).**
Superseded by this design: a discard would destroy the very signal the
agent needs to reintroduce a topic gently. `parked_topics.status` already
permits `dismissed` and the SPA already calls `/api/backlog/dismiss`, so
the capability exists; only a modal control does not.

**System-initiated reminders (push).** Rejected under constraint 1: the
system deciding when to confront the learner with a deferred topic is
exactly the unpredictability the constraint forbids.

## Consequences

- Scope questions during 0.1.0 get a mechanical answer: is it a documented
  promise, or a dead end? If neither, it waits for 0.2.0 or gets a recorded
  scope choice.
- **Most of the 0.2.0 design already exists and must not be rebuilt:**

  | Need | Existing |
  |---|---|
  | Struggle signal | `study_progress` (concept, confidence, session_count) |
  | Deferred store | `parked_topics` — statuses `pending / scheduled / resolved / dismissed` |
  | Bridge store | `knowledge_bridges` table |
  | Structural-analogy discipline | `agents/shared/knowledge-bridging.md` |
  | Adjacency graph | `concept_dependencies` / `concept_relations` (`prerequisite`, `refines` edges) |
  | Deck generation from struggles | `topic_struggles` generation scope |

- **The one real gap:** `parked_topics.topic_tag` is free text, so there is
  no join from a parked topic to `concepts` — which is exactly the join
  adjacency lookup needs. That join is the schema work this design
  requires; the rest is agent behaviour.
- Constraint 2 makes the adjacency graph load-bearing: a topic with no
  structural edge to present competence is never mentioned, so the quality
  bar for `concept_dependencies` / `concept_relations` edges rises from
  "nice to have" to "gates a user-facing behaviour".
