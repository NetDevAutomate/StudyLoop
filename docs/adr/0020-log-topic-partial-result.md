# ADR-0020: `log_topic` reports a failed spaced-repetition write as a typed partial result, not an error

**Status:** Proposed · **Date:** 2026-10-22 · **Deciders:** council pass 3 of the 2026-10-21
full-repository review (five no-tool seats: kimi-k3, gpt-6-astra, grok-4.6, deepseek-r1,
mistral-large-3), arbitrated by argument by the review coordinator under the owner's standing
delegation; Andy Taylor (owner) has not yet reviewed. Accepted when the owner has read this record
and the arbitration; the release-consistency check refuses a tagged release that still says
Proposed. · **Change:** 2026-10-22 council pass 3, ruling D9.3 (4–1); implemented in `12f53ab2`,
merge `b5a222ac` (lane I, `mcp-log-topic-partial`).

The council record (`reviews/2026-10-21-full-repo-review/`, gitignored, owner's machine only)
holds the seat transcripts; everything this record relies on is restated here. Symbols were read
at `309074c7` in `packages/studyloop/src/studyloop/mcp/tools.py`.

## Context

The MCP tool `log_topic(topic, status, note)` is how a mentor records that the learner is
learning, struggling with, or has had an insight about a concept. It makes **two independent
writes**: `append_topic` adds the entry to the session's `session-topics.md` (counted at session
end), then, for learning-signal statuses, `record_progress` writes a `study_progress` row (the
spaced-repetition store). They are not one transaction: the file write has landed before the
database write starts, and nothing rolls it back.

Before the 2026-10-21 review a failed second write was swallowed. The review's lane 8 made it
visible as `progress: "not saved: <reason>"` beside `logged: "true"`, because
`test_mcp_log_topic.py` pinned the exact success dict and the lane did not own that test. That
left a **success-shaped failure**: a mentor reading `logged: "true"` would tell the learner the
topic was saved for review when it was not, and nothing in the shape said otherwise.

Raising `ToolError` instead would have misreported state in the other direction: the topic
**was** logged for the session, and an agent that sees an error retries, which duplicates the
`session-topics.md` entry.

## Decision

A **typed partial result**. On a failed `study_progress` write the tool returns

```json
{"logged": "partial", "topic": "...", "status": "...",
 "failed": "study_progress", "reason": "<why, with the fix>"}
```

The success shape is unchanged: `{"logged": "true", "topic": ..., "status": ...}`. The tool's
docstring, which the mentor reads, states the contract: on `"partial"`, tell the learner the topic
was logged for this session but not saved for spaced repetition, and **do not call `log_topic`
again**, because that duplicates the session-topics entry.

Grounding adopted: the MCP convention that **domain outcomes are structured results** and
protocol or tool failures are errors; typed status over sentinel strings. It matches the pattern
`evaluate_study_plan` already uses (`db_write` / `document_write` each `saved` or `failed`,
`recording_complete` only when every requested write landed).

## Alternatives considered

- **(a) Keep `logged: "true"` with a `progress` field the agent must notice.** Rejected: the
  top-level field says success; the failure is in a field no mentor prompt mentions. The lane that
  produced it had already said it was the wrong shape and was only honouring a test it did not own.
- **(b) Raise `ToolError` on the failed write.** Rejected 4–1: the two writes are independent, so
  an error after the file write misreports state (topic logged, error returned) and invites a
  duplicate retry. The one seat for (b) argued it is safe only if the two writes are one
  transaction, which they are not.

## Consequences

- A mentor must branch on `logged` having three values, not two: `"true"`, `"partial"`, and the
  exception path for a genuine tool failure (bad arguments, no active session). The docstring
  carries the branch.
- The old pin of the partial shape (`logged: "true"` plus `progress`) was asserting the wrong
  contract; it was updated along with the tests in `test_mcp_tools.py` that assumed it. The plan's
  citation of the success-dict line as "the assertion to update" was wrong, and the lane said so
  in its commit body rather than editing around it; the success dict is byte-for-byte unchanged.
- Any future tool that makes more than one write should return per-write outcomes in the same
  style rather than a boolean, so a mentor can tell the learner exactly what did and did not land.

## Verification

`packages/studyloop/tests/test_mcp_log_topic.py`: a failed progress write (raising, and returning
`False`) yields `logged == "partial"` and `failed == "study_progress"`; success yields the exact
previous dict; the session-topics entry lands **exactly once** in every case, proven by driving the
real `append_topic` against a temporary `session-topics.md` rather than a mock.
`test_mcp_tools.py`: the `log_topic` assertions updated to the new contract. 52 tests across the
affected files pass under the coordinator's run.
