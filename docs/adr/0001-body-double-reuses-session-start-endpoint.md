# ADR-0001 — Body Double reuses `POST /api/session/start`

- **Status**: Proposed
- **Date**: 2026-07-25
- **Change**: `openspec/changes/body-double-own-agent-picker`
- **Deciders**: repo owner (pending sign-off)

## Context

The Body Double view needs to launch an agent CLI in a terminal. Study
Session already does exactly that through `POST /api/session/start`
(`web/routes/session/_start.py`), which spawns the agent on the chosen
transport, writes a `study_sessions` DB row, creates a session directory,
delivers the Socratic persona, and returns `ws_url` + `persona_text`.

`StartSessionRequest` (`web/routes/session/_models.py:9-24`) accepts exactly
four fields: `topic`, `energy`, `agent`, `transport`. There is no session-type
discriminator — the vestigial frontend `sessionType` value never reached the
backend.

Session start is guarded by an `asyncio.Lock` singleton
(`session/active.py:46`); a second start returns HTTP 409. So whatever we do,
Body Double and Study Session cannot both be live.

Body Double has no course/vendor/lesson cascade. Its input is one freeform
line: "what are you working on?"

## Decision

Body Double starts go through the **same** `POST /api/session/start`, with
the freeform activity text passed as `topic`. No new endpoint, no new request
field, no session-type discriminator anywhere in the stack.

Consequences accepted deliberately:

1. A Body Double session **occupies the single-active-session slot**. You
   cannot body-double and run a Socratic study session at the same time.
2. It gets a `study_sessions` row whose `topic` is the freeform activity
   text, so it appears in `studyloop resume`, the activity feed, exports, and
   session history alongside study sessions.
3. It receives the **same Socratic persona** the study path delivers.

## Alternatives considered

**A new `POST /api/session/body-double` endpoint.** Rejected: it would
duplicate agent resolution, transport dispatch, session-dir slugging,
persona delivery, and the active-session lock — five things this codebase has
a documented history of breaking precisely because they were hand-rolled per
call site (see `openspec/config.yaml` context note). The only thing that
differs is the label.

**Add `session_type` to `StartSessionRequest` and branch server-side.**
Rejected for now: nothing downstream would read it. Adding a field no
consumer branches on is how the current `sessionType` dead value came to
exist in the first place. If Body Double later needs a different persona or
to be excluded from mastery/struggle analytics, *that* is the change that
should introduce the discriminator — with a reader on day one.

**Keep Body Double sessionless (terminal only, no DB row).** Rejected: it
would need a second, parallel agent-spawn path outside the active-session
lock, so two agent processes could race for the same PTY infrastructure. It
also loses body-doubling from history, which is the data the AuDHD loop uses
to notice "you only get work done when someone's there".

## Consequences

- Zero backend change for this feature; the whole change is frontend plus
  removing one dead `session_types` entry.
- Body-doubling hours become visible in streaks and history for free.
- **Known wart**: the Socratic persona is delivered to a session where the
  agent is not being asked to teach. Acceptable for now — the mentor persona
  is benign in a body-doubling context and stays silent unless prompted. If
  it proves intrusive, the fix is a persona variant, and that will be the
  change that finally justifies a session-type discriminator.
- **Known wart**: body-double activity text lands in the same `topic` column
  as study topics, so struggle/mastery analytics will see e.g. "reply to
  Ahmed's email" as a topic. Flagged as follow-up, not blocking.

## Verification

- `POST /api/session/start` is unchanged; existing transport tests cover it.
- New: starting Body Double while a study session is active surfaces the 409
  as a picker error rather than a silent no-op.
