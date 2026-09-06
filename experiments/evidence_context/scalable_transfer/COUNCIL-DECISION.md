# Stage39 council and coordinator decision

Two rounds returned valid responses from Meta (`llama4-maverick`), Qwen
(`qwen3-coder`) and Mistral (`mistral-large-3`) through the configured gateway.
These are provider-diverse reviews, not votes that establish correctness. The
production goal remains open. No unanimous release approval is claimed.

## Decision and alternatives

The design brief asked how to move scopes larger than the existing 32 MiB packet
while preserving source bindings, dependency closure, current permissions, complete
regrant coverage and atomic content receipts. It offered larger packets, independent
session batches, private complete-scope staging and row-level deltas.

Meta wanted a broader review of the goal without identifying a concrete replacement.
Qwen favored bounded staging first. Mistral favored a row-delta protocol, beginning
with full-scope retransmission until portable keys and receiver-union validation were
proven. The coordinator chose private complete-scope staging as this checkpoint and
kept incremental transfer as required subsequent work.

The reason is the existing cross-session evidence contract. Splitting commits by
session would require new rules for reviews spanning sessions and for receiver-only
quarantined dependencies. Private staging changes the representation without granting
partial content authority. This is a sequencing decision, not evidence that full
retransmission will be sufficient for every production history.

## Result review and arbitration

The result packet included the full staging, stream, projection, content, ledger,
endpoint, coordinator, framing, policy, withdrawal-preview, retention and server
implementation. It summarized directed tests and initial measurements. It did not
include the complete tests, permission implementation or every consumer. Corrected
installed acceptance was still pending when that packet was sent.

| Council concern | Evidence and decision |
|---|---|
| Incomplete staging might become canonical | Stage completeness, strict table/sequence/column checks, final exact hash and one canonical content/receipt transaction are enforced. Directed incomplete/corrupt stream tests assert no body and no receipt, rather than relying on exit status alone. |
| Late permission/source checks need scrutiny | Accepted. A further test reproduced a final commit-request gap after the last chunk. The command failed later, but a receiver copy existed. Extending the pre-write source check to the commit request closes that observed window; both chunk and commit injections now require body absence. |
| Process death needs concrete tests | Actual child-process death during canonical promotion rolls back body and receipt. Another child allocates over 64 MiB of temporary staging and exits; no reusable path remains in its isolated directory on this Mac. Cross-platform cleanup and forensic erasure are not established. |
| Streaming hashing could change the binding | A directed Unicode/escaping test compares exact serialized bytes and digest with the existing canonical encoder. Final received hashes are recomputed against the accepted offer. This does not certify arbitrary future serializers. |
| Large metadata can still consume memory | Accepted limitation. Indexed staged body lookup removes full-body dictionaries; identifier sets, manifests and withdrawal facts still scale with cardinality. Single-sample RSS observations are not a universal memory guarantee. |
| Historical protocol recovery is missing | Live v1 peers are refused before binding/content. A historical v1/schema45 acceptance test exercises metadata recovery while refusing old body release. Historical proof and current permission remain distinct. |
| Withdrawal correctness needs large-scale acceptance | The first installed large transfer exposed the old preview budget and returned incomplete cleanup. Hashing first-before-images instead of retaining bodies corrected that bottleneck; the subsequent installed lifecycle checks pass. Unknown retention remains quarantined. |
| Other production work must precede release | Agreed. Full-store/restore, shared setup, remaining consumers and release acceptance remain in the delivery contract. This checkpoint is not a release. |

Several responses described tests as absent even though the brief named them; the
complete test files were not supplied. Those assertions were checked against the
repository rather than treated as proof of missing behavior. Assertions that the
brief promised universal temporary-file cleanup, constant memory or changed owner
configuration were also rejected: those claims were explicitly excluded, and all
observed runs used disposable fixtures. The underlying portability and deployment
limitations remain valid.

## Reproduce the important checks

The stage guide provides the combined command. The most informative individual tests
are in `packages/agent-session-tools/tests/`:

- `test_replica_staging.py`: canonical byte equivalence, poisoned/incomplete stages,
  immutable sealing, bounded rows and actual temporary-stage process death.
- `test_replica_content.py`: over-limit staged scope, cross-session review closure,
  changed receiver, withdrawal before promotion and canonical crash rollback.
- `test_replica_coordinator.py`: actual two-process streaming, lost commit response,
  midstream withdrawal/forget/config change, both pre-write boundaries, incomplete and
  corrupted streams, old live protocol refusal and historical metadata recovery.

The guide and observed results record the failed probes as well as passing runs.
No further prompt tuning or council approval loop substitutes for those checks.
