# Stage28 council arbitration

Decision: preserve the tested finite-response guard and continue the full production
goal. This is an implementation checkpoint, not deployment or release approval.

Both rounds returned valid responses from Meta `llama4-maverick`, Qwen `qwen3-coder`
and Mistral `mistral-large-3`. Preflight was healthy. Each round used one neutral
brief for all reviewers. Only synthetic cases, code and aggregate results were sent.
The comparison Markdown/JSON and relevant raw responses were read. Private artifacts:
`studyloop-private/reviews/2026-09-06-stage28-response-boundary/`.

## Design advice

All three favored a request-local frame plus a durable access generation. Accepted
because it addresses the reproduced between-helper scope switch while retaining
existing scoped query paths. Agreement alone was not the acceptance test.

Qwen assumed every query stays on the originating request thread. Rejected: FastAPI
runs synchronous endpoints on workers. The implementation shares a request-local
frame through copied context and protects monitor use with a per-frame RLock.
Actual HTTP and asyncio-to-thread tests exercise this. Custom executors require
explicit propagation or another boundary; no universal thread-safety claim follows.

A global process lock would not cover external configuration edits or other processes.
A single historical data snapshot remains a different, stronger fact-consistency
contract than the permission-consistency contract tested here.

An initial old-schema PRAGMA data_version fallback was removed during implementation
review. It could miss a revocation committed between the helper snapshot and opening
its monitor. The final implementation requires the generation migration, with an
explicit policy-apply instruction. A compatibility path cannot silently promise a
guarantee it cannot establish.

## Result review and decisions

| Advice or claim | Decision and evidence |
|---|---|
| Meta/Mistral: test cancellation and monitor cleanup | Accepted. Added assembly/release cancellation, closed-monitor verification, context restoration and delayed-reuse refusal. Tests exercise real async suspension points; synchronous validation is not artificially made asynchronous. |
| Qwen: test simultaneous requests and explain custom-thread limits | Accepted. Sixteen requests contribute queries through worker threads, then an assignment changes away and back. All sixteen are withheld; a subsequent unchanged batch all succeeds. The separate independent-task test confines a scope mismatch to its own request. |
| Meta: benchmark added checks | Installed paired-order fixture measures 14.932 ms versus 16.892 ms median over 20 iterations each. This does not cover production volume, high throughput or all storage variants. |
| Mistral: all access-relevant changes are caught | Too broad. The trigger allowlist covers the current DB paths under test. Remaining learner files, streaming, sync and managed restore still need integration; every new access-affecting writer must extend the contract. |
| Mistral: cancellation can leave the ContextVar token unset | Not demonstrated. `finally` restores the token and closes monitors; cancellation tests verify cleanup. No special cancellation handler is needed merely to replace correct finally behavior. |
| Meta: releasing the buffer before sending might fail during capture | Capture completes before validation or sending. Oversize and cancellation tests verify no captured prefix escapes. Errors during actual transport can still interrupt a valid response; that is not a database rollback. |
| Mistral: document no recall after valid delivery | Accepted as a boundary of the claim. An application cannot retract bytes already received by an external client. This does not waive required managed deletion/restore work. |
| Qwen: approve with follow-up | Retain the increment; do not interpret this as release approval. Whole P01–P15 acceptance remains incomplete. |

The result brief preceded the final installed figures and added cancellation/load
checks. Tests were added to distinguish concrete risks; there was no repeat council
run to obtain a more favorable vote. Numerical model confidence is not used as a
correctness probability.

## Next work

Complete ownership of remaining annotations, learner graphs/dependencies, planning
and session-state files; add the appropriate live-stream/session boundary. Then
exercise the actual protected peer protocol, forgetting/reimport/restore and indexes,
shared selectable setup/doctor/skills and installed agent startup. Keep semantic
usefulness separate from a result being consistently permitted and attributable.
