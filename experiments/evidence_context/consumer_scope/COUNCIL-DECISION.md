# Stage20 council arbitration

The gateway was healthy before the run. Four provider buckets received the same
brief and source excerpts. Fable, Qwen and Mistral returned usable reviews; Grok
timed out. Original responses remain locally in the ignored
`.private/stage-20/consumer-council/` directory. The brief included no conversations.

The review covered the legacy helper, extractor caller and resume implementation,
plus an explicit description of the incomplete global learning ownership. It did
not cover every StudyLoop consumer, the installed package or the entire write path.

| Finding | Arbitration |
|---|---|
| Fable: scoped extraction can still contaminate the global progress aggregate | Accepted. The actual pipeline confirmed the unscoped upsert. Classified writes are now refused before calling the provider, with a negative persistence test. Durable scoped writes remain a release prerequisite. |
| Fable: an excluded direct ID looks like an ordinary pre-filter skip | Accepted. Missing and excluded IDs both report unavailable, without disclosing whether an excluded ID exists. Tests and the demo check this before provider invocation. |
| Fable: dry run still sends messages to a live model | Confirmed existing semantics. CLI help and this guide now make that explicit. Dry run is not described as offline. |
| Fable: root configuration is not consulted by the helper | Incomplete inference from the supplied excerpt. The helper calls active policy/request scope and the shared guard checks the applied project fingerprint. CWD roots participate in scope resolution. Explicit unclassified inspection is still deliberately allowed for an unassigned database. |
| All three responders: prefer source-linked observations with rebuildable scoped aggregates | Accepted as the next design direction. Adding a scope column to a previously merged record cannot recover lost contributions. No general model-quality or graph-engine superiority claim follows. |
| Fable: resolve current ownership through source assignments instead of freezing scope forever on events | Accepted principle. Preserve original event provenance separately from the current access decision, and invalidate cached projections after reclassification. Manual observations without a session need explicit ownership. |

The next decisive tests are: two scopes discussing the same concept without mixed
outputs; reclassifying one source while keeping its historical observation intact;
forgetting one contributing source and proving it cannot return through summaries,
sync, caches or restored snapshots. These tests require the next ownership schema;
passing read-withholding tests does not stand in for them.

The final decision is to keep this increment conservative and continue. Council
agreement is advisory, not semantic certification or approval to release incomplete
ownership paths. Unimplemented requirements remain visible in delivery/GOAL.md.
