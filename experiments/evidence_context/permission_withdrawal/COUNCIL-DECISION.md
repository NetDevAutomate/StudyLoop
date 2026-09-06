# Stage36 council arbitration

The design and result rounds each returned Meta Llama4 Maverick, Qwen3 Coder and
Mistral Large 3 through the authorized local gateway. Raw responses and briefs are
retained in the private `2026-09-06-stage36-withdrawal-protocol` review directory.
The council did not unanimously approve this implementation.

## Design round

Meta emphasized keeping the protocol small and testing generation order. Qwen supported
the direction conditionally on transaction, bounds and quarantine recovery evidence.
Mistral recommended replacing rollback tracing with a marked dependency set and warned
that ambiguous quarantine could become a permanent availability problem.

Accepted: monotonic generations, explicit unresolved retention, fresh regrant, bounded
tracing and concrete concurrency/crash tests. The missing reconciliation path is a real
production gap. It remains visible in the goal rather than being hidden by a success
receipt.

Not adopted: a second manually enumerated purge graph. The existing lifecycle already
handles source and learner dependencies, including SET NULL ordering. Reusing the real
purge under a rollback-only preview reduces disagreement between a predicted footprint
and the actual deletion. That choice still requires fixed-schema and error-path tests.

## Result round

Meta requested more edge-case evidence. Qwen and Mistral rejected the implementation,
alleging transaction and concurrency defects. Their conclusions were considered as
hypotheses, not discarded because tests were green and not accepted because two models
agreed in tone.

| Finding | Arbitration against evidence |
|---|---|
| A second connection could observe the simulated partial purge | The actual second-connection test sees the earlier committed session while the writer sees no session; a competing write is locked. SQLite transaction documentation supports this behavior. |
| TEMP triggers could affect other connections | SQLite explicitly restricts a TEMP trigger on a main table to its creating connection. The trace performs no external file/network effects. Creating a TEMP database object is not evidence of cross-connection trigger execution. |
| Another writer could change permission generations during the trace | The coordinator holds BEGIN IMMEDIATE. Directed tests cover a competing writer, concurrent duplicate outgoing preparation, and regrant between compaction and final receipt. |
| SAVEPOINT cleanup could obscure an original transaction failure | This was a real defect in the earlier implementation, reproduced and fixed before the result round. The whole-transaction-abort and process-exit tests pass. The reviews did not provide a new failing ordering after that fix. |
| Regrant might expose an unoffered retained row | A receiver-only message is deliberately retained. Fresh content lacking that message fails exact-offer coverage and rolls back releases and writes. The installed lesson demonstrates it. |
| Released IDs might name absent rows | Missing rows expose no body; incoming content still goes through the existing exact manifest, closure, ownership and retirement validation. Historical receipts are not current existence claims. |
| Foreign-key and cascade failure handling needed testing | Added a restrictive-FK failure case; it aborts the whole control without a success receipt. Native learner cascades are tested with recursive triggers both enabled and disabled. |
| Bounds must fit every production workload | Rejected as an unprovable universal requirement. Bounds are a refusal boundary: row/byte overflow returns unresolved instead of a partial proof. Realistic scale and operational recovery remain required. |
| Future schema evolution or unknown retention could be unsafe | Accepted as a maintenance/release obligation. The current canonical table contract is fixed, and operator reconciliation remains open. No arbitrary-schema or full-production claim is made. |

Primary references: [SQLite savepoints](https://www.sqlite.org/lang_savepoint.html),
[transactions](https://www.sqlite.org/lang_transaction.html),
[TEMP trigger scoping](https://www.sqlite.org/lang_createtrigger.html#temp_triggers_on_non_temp_tables)
and [foreign keys](https://www.sqlite.org/foreignkeys.html). The tests establish the
observed implementation behavior; the documentation explains the underlying guarantees.

## Decision

Preserve the bounded protocol as an independently runnable checkpoint and keep the full
production goal active. Do not replace the implementation solely because a reviewer
asserted a concurrency failure inconsistent with SQLite's documented behavior and the
directed experiment. Do not describe these tests as a proof of every future workload.

Prioritize explicit resolution of quarantine before claiming a usable sync lifecycle.
Retained local additions need an inspectable decision path; a sender cannot silently
authorize them by regranting its own earlier copy. Then complete authenticated transport,
full-store/restore and the remaining installed StudyLoop acceptance gates.
