# Stage21 council arbitration

Two bounded review rounds used the healthy configured LiteLLM gateway. The first
gave the full observation schema/store and consumer adapter; the second narrowed
the brief to input capture, transaction ordering and projection semantics. Each
round sent the same brief to every selected reviewer in that round.

| Round | Selected | Usable responses | Coverage limit |
|---|---|---|---|
| Full increment | Fable 5.1, Grok 4.6, Qwen3 Coder, Mistral Large 3 | Qwen, Mistral | Fable returned no JSON object; Grok timed out |
| Focused follow-up | Fable 5.1, Qwen3 Coder, Mistral Large 3 | Qwen, Mistral | Fable again returned no JSON object |

Both runs reported `insufficient_diversity`. This is two-provider advice, not
three-provider agreement or a release approval. Raw requests and responses are
kept in the private review directory, separate from distributable package content.

## Accepted

- **Test caller transaction ownership and batch rollback.** The pipeline now has
  a test proving it rejects an active borrowed transaction without changing that
  transaction. A late invalid report rolls back the entire batch and source capture.
- **Make input traceability explicit.** Returned relationships say `captured_input`.
  They are not supporting-passage citations. An ordered manifest preserves roles,
  null-content shape and the original sequence fingerprint.
- **Keep model authority conservative.** A projection with any unverified model
  report cannot inherit a stronger-looking status from another report merely
  because they have the same confidence value.
- **Test rather than assume lifecycle behavior.** Scope drift, source deletion,
  exact replay and superseded-history behavior have executable negative cases.
  Full managed forgetting/sync/restore remains an explicit release requirement.

## Rejected, with evidence

Mistral's first response said access was checked after evidence writes. The supplied
`persist_session_input` checks the session before `store.capture`; the pipeline
starts `BEGIN IMMEDIATE` before calling it. Concurrent policy/tombstone tests assert
that no observations or evidence survive either rejection. The alleged ordering
does not match the code.

The follow-up proposed holding one immediate transaction across the provider call.
That is unnecessary for the chosen contract, which records the input actually
supplied and revalidates permission before persistence. It would block all other
SQLite writers for the network wait. The test provider proves a second connection
can commit during invocation, then verifies that later persistence observes the
relevant scope/deletion change. SQLite documents both the single-writer behavior
and how a fresh transaction sees later committed state:
[transaction control](https://www.sqlite.org/lang_transaction.html),
[isolation](https://www.sqlite.org/isolation.html).

Both follow-up responses raised a concern that a captured-input link might imply
semantic validation. That distinction is valuable and is now explicit in the
output/guide. Their claim that `conflicting_reports` itself promotes an assessment
to validated status does not follow: the code retains all values and no validation
status is awarded. Conflicting reports are also not automatically integrity
violations; the contract deliberately preserves disagreement and concurrent branches.

## Decision and remaining uncertainty

Keep immutable, source-linked observations and fresh-transaction revalidation.
Keep the conservative scheduling projection with exposed disagreement. Preserve
the runnable checkpoint and continue production work; do not claim semantic
correctness or readiness from this increment.

The gateway review did not produce strong provider diversity. It also did not
independently execute the tests, inspect installed artifacts, or review all the
remaining learner/capture/sync paths. Those limits remain part of release acceptance.
