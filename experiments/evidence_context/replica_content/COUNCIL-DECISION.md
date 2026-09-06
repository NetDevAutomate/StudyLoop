# Stage32 council arbitration

Decision: preserve this tested **content-phase increment**, then implement lifecycle
reconciliation and the actual configured-peer coordinator. It is not a completed sync
implementation or approval to ship. The full delivery goal remains active.

## Review coverage

Both council rounds used the healthy configured LiteLLM gateway. Meta
(`llama4-maverick`), Qwen (`qwen3-coder`) and Mistral (`mistral-large-3`) returned
valid responses in each round: six successful calls across three provider lineages.
The same brief/schema went to each reviewer within a round. Comparison Markdown/JSON
and raw responses were inspected. Private briefs and responses are retained under
`studyloop-private/reviews/2026-09-06-stage32-scoped-transport`.

The design round selected a structured protocol over SSH. Its alternatives and
arbitration are preserved in [the transport design](../delivery/SCOPED-TRANSPORT-DESIGN.md).
The result round reviewed the implementation and observed content-phase results.
Meta accepted conditionally; Qwen rejected integration pending trust, conflict and
lifecycle work; Mistral accepted conditionally with concerns about typed references
and remote provenance. These are different assessments, not unanimous approval.

## What changed because of review

| Concern | Coordinator decision and evidence |
|---|---|
| A review payload could cite an undeclared source | Accepted as a concrete contract gap. The receiver requires every structured review citation and every target source in the declared input set. A self-consistent, rehashed packet with an omitted input now fails before writes. |
| Scope checks must precede payload exposure | Added source-side SQL metadata preflight. A deliberately corrupted review citing excluded work input fails before any `Projection.read`. Learner native/study foreign keys are checked as additional selection dependencies. |
| Review target binding may be insufficient | The original code already reconstructs exact assertion/relation targets and checks their hash, authority, verdict and citation slices. The missing dependency test strengthens this; it does not establish semantic correctness. |
| UUIDs might be treated as conflict resolution | Rejected that implication. IDs locate records; divergent values still refuse the whole content phase. A conflict preserves both originals but has not converged. |
| No complete lifecycle/coordinator | Accepted. Return values explicitly keep `sync_complete` and `lifecycle_reconciled` false. No real SSH, withdrawal, stale-delete replay or managed restore acceptance follows from these tests. |
| Configuration assumed fixed during operations | That assumption does not match the implementation: tests change the supplied configuration during both export and import. External configuration-file refresh and final transport boundaries remain coordinator obligations. |
| Clock drift could invalidate the grant | The binding uses DB identity, access generation, file identity and policy digest, not time-based expiry. Network disconnection/retry still needs actual coordinator tests. |
| Marker flags do not establish absence | Correct generally. Here the flag is calculated by inspecting the actual staged JSON and destination DB/WAL bytes. That proves absence of the fixture marker, not universal information-flow correctness. |
| Require cryptographic attestation for semantic trust | Not accepted as a substitute for provenance. Hashes prove consistency; a signature authenticates a statement, not its truth. Authenticate the configured SSH peer and retain the documented local-parser trust boundary. |

## Additional implementation findings

Testing all six owned learner tables exposed a generated SQLite column: teach-back
`total_score` must be recomputed at the destination, not inserted as an ordinary field.
Explicit writable-column projection fixes that round trip. The test compares every
stored/calculated field and checks study-parent links and repeat import.

A separate negative test prevents an incoming owner from adopting an identical but
previously unowned text-keyed learner row. Matching content is not authorization to
change local classification. A final byte-limit test includes the packet hash field
in the encoded size budget.

These changes followed the result brief. They received deterministic tests and local
code inspection; do not describe them as a second council approval. The lesson was
rebuilt from a fresh standalone wheel afterward. Exact coverage is recorded in
[OBSERVED-RESULTS.json](OBSERVED-RESULTS.json).

## Next evidence gate

Implement durable retirement/withdrawal semantics, unsafe legacy fallback refusal,
fresh-file peer policy checks and real `session-sync` process boundaries. Test deleted
sources against stale snapshots, native reimport, indexes and managed restore. Provide
an actionable conflict outcome before claiming successful complete synchronization.
None of these obligations is waived because the smaller content test passes.
