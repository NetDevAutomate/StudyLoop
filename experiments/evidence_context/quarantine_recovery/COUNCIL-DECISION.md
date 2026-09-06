# Stage37 council arbitration

Meta Llama4 Maverick, Qwen3 Coder and Mistral Large 3 responded in both the design
and result rounds through the authorized LiteLLM gateway. The briefs and raw responses
remain in the private `2026-09-06-stage37-quarantine-recovery` directory. Their
recommendations are review hypotheses; there was no unanimous approval.

The design round favored an inspectable discard path, preservation of denials and
explicit acknowledgement of local additions. These were adopted. Retaining quarantine
remains the default. A suggestion to treat retry as out of scope was rejected: an
operator must be able to recover after a lost response without deleting a fresh copy.

The result brief included the quarantine implementation, audit schema and preview
implementation. It described the selector changes but did not include their full diff,
despite an imprecise closing sentence saying they followed. The council therefore did
not independently inspect every changed body-reader path. The coordinator reviewed
those changes and added a directed ordinary-reader/snapshot test; this limitation is
not presented as independent verification.

| Review concern | Decision and evidence |
|---|---|
| Historical receipts could delete fresh content | The existing fresh-transfer test and installed CLI lesson verify that replay returns the old receipt without rerunning purge. The receipt explicitly does not assert current body absence. |
| Concurrent work could invalidate cleanup completion | Accepted as a concrete test obligation. A second connection inserts pending work after successful compaction; the final receipt remains incomplete and retry completes with one audit decision. Pinned-reader retry and crash-before-audit tests also pass. |
| Logical discard and physical cleanup should be separate | They already are separate fields and commit boundaries. Mistral's specific assertion that `complete: false` claims completion is unsupported. Documentation now explains historical meaning, pending cleanup and canonical-only coverage explicitly. |
| Cleanup must eventually succeed for all affected files | Rejected as a universal liveness claim. Readers, storage failure or configuration changes can prevent success. The operation reports that limitation; it does not claim archives, backups, full-store or arbitrary file cleanup. |
| Equal policy digests across scopes could allow cross-scope discard | The digest describes project classification, not request scope. Scope is checked separately in selection, plans, cursors and historical receipts. A new test deliberately retains the same digest, switches personal to work, and verifies receipt access refusal. No claim to experimentally prove cryptographic collision resistance is made. |
| There is no cross-process write exclusion | The operation uses the existing BEGIN IMMEDIATE transaction. Stage36 exercises actual competing connections. The new process-exit test verifies atomic purge/audit rollback. Review supplied no concrete counterexample to those transaction boundaries. |
| Metadata selection might enable body access | Accepted as an entry-point regression concern. A new test inspects all six kinds, then checks ordinary session, source, observation, learner-record and snapshot routes remain empty. The private exception is not a public API argument. Future entry points still require audit. |
| A removed and re-added peer needs a recovery test | Added. Local discard succeeds with the peer absent; re-adding configuration alone restores nothing. Explicit regrant and a fresh transfer restore the sender-covered copy. |
| Audit should preserve request context | Schema45 already stores the full sealed plan, scope, kind/ID, instance, actor and commit time. Only the cleanup receipt can be updated. Directed tests refuse deletion and identity/plan rewrites. Actor is local audit attribution, not cryptographic identity. |
| Body-access logging should be added | Not adopted as a substitute for denying body reads. Logging would neither prove absence of exposure nor strengthen the current authorization predicate. Whole-product observability remains part of capture/doctor acceptance. |

The coordinator decision is to preserve this bounded implementation and move to the
actual sync coordinator. Repeated prompt revision until every reviewer approves would
not establish correctness. The tests, observed failure behavior and explicit coverage
limits support this checkpoint; full production readiness remains unclaimed.
