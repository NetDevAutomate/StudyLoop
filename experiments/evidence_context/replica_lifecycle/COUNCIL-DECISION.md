# Stage34 council arbitration

Two healthy-gateway rounds each produced successful Meta (`llama4-maverick`), Qwen
(`qwen3-coder`) and Mistral (`mistral-large-3`) responses. Each round used a common neutral
brief. Both comparison files and all raw result responses were read. Private artifacts
remain in the Stage34 replica-lifecycle review directory. No owner transcripts or
credentials were supplied; they are not needed for this protocol code review.

## Design

Meta and Qwen requested clearer state transitions, identity changes and retirement
feedback. Accepted: persist both endpoint bindings, enumerate states and test the gaps
between acceptance, body commit, receipt and controls. Unexpected replacement identities
are refused for managed reconciliation rather than automatically trusted.

Mistral proposed eliminating acceptance and relying on a single transfer plus sender
logging. Rejected for this checkpoint: it does not supply the receiver-side prospective
boundary required for controls arriving before body delivery. The lost-acceptance and
retire-before-body tests exercise that distinguishing case. The brief explicitly made
acceptance durable, contrary to the response's assumption that it was ephemeral.

Also rejected: treating retirement as secondary to delivery, introducing hypothetical
forensic-retention requirements, inferring missing legacy scope from unspecified side
channels, or assuming synchronized clocks are necessary for monotonic permanent IDs.
None follows from the user objective or this implementation. Real additional historical
evidence could support a later explicit legacy repair; none is invented here.

## Implementation review

| Advice or claim | Engineering decision |
|---|---|
| Qwen/Mistral: cleanup and receipt concurrency needs proof | Accepted. Reproduced a new pending deletion between compaction and receipt. The old function falsely reported complete; the final receipt transaction checks pending work and the sender declines completion until retry succeeds. |
| Qwen: strengthen immutable metadata/state transitions | Added database guards against backward offer states, receipt/acceptance replacement and identity/scope mutation; tested direct attempts. |
| Mistral: batches lack endpoint identity binding | Rejected as stated. They contain both node identities and database instances, and APIs match the independently supplied peer against pinned local records. Real SSH authentication remains unimplemented and cannot be inferred from those fields. |
| Mistral: compaction can fail after the receipt is already written | That order does not match the code; compaction precedes receipt writing. The real later-request interval above was tested instead. |
| Qwen: SHA-256 identity needs signatures to prevent collisions | Not adopted. Hash integrity and authenticated peer transport are different obligations; signatures do not change hash collision properties or establish source truth. The coordinator's authentication work remains open. |
| Meta: there are no payload limits | Rejected as a per-envelope claim: row and byte caps are present. Accepted as a longer-term history growth concern; aggregate retained ledger size is not bounded by those caps. |
| All: real coordinator/config freshness is absent | Agreed. It is explicitly required before production sync is exposed; helper success does not satisfy it. |
| Meta: owner credentials are necessary for review | Rejected. Fictional fixtures and implementation source are sufficient here; credentials are not a review artifact. |

The council did not unanimously approve the design or final implementation. The
coordinator retained a mechanism supported by discriminating tests, fixed a demonstrated
receipt race, and documented the unresolved production boundaries. Final refinements
followed review; no second result approval is claimed. The full production goal remains
active.
