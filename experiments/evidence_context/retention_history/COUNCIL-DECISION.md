# Stage35 council arbitration

Both the corrected design review and implementation review received successful responses
from Meta (`llama4-maverick`), Qwen (`qwen3-coder`) and Mistral (`mistral-large-3`) through
the configured local LiteLLM gateway. Preflight was healthy. Each round supplied the
same brief to all three providers. Raw briefs/responses remain in the private review
directory; the public learning material contains no transcript bodies or credentials.

The initial design round contained an incorrect premise about learner/observation edge
direction. That brief was corrected and rerun. Its original failing test is not a
production defect or a successful remediation. The corrected edge is described in the
guide and protected by a passing test.

## Design advice

| Advice | Decision and evidence |
|---|---|
| Track explicit local capture and committed peer origins | Accepted as historical, exact-version facts recorded by code in the content transaction |
| Preserve independently permitted copies when one peer withdraws | Kept as a requirement; not implemented by counting delivering peers |
| Treat ambiguous legacy origins explicitly | Accepted: no migration backfill; an existing untracked row receives an unattributed marker before its first new peer contribution |
| Quarantine or refuse ambiguous withdrawal | Deferred to withdrawal implementation; this stage does not add a misleading partial quarantine with uncovered readers |
| Infer authority from model statements to improve proof | Rejected: a model's claim cannot supply a capture receipt or grant permission |

All three designs were conditional on provenance that the previous schema could not
prove. The coordinator narrowed the implemented checkpoint accordingly. A three-replica
test demonstrates the shared-upstream counterexample. `committed_peers` is descriptive;
`independent_upstream_origins` remains `not_established` and `retention_authorized`
remains `not_evaluated`.

## Implementation review

Meta asked for legacy/recapture coverage. Both existed in actual native-import and
content-delivery tests. Repeated capture records a fact without treating it as permission.
Qwen requested a legacy-row test when origin tracking is introduced. The migration test
preserves old rows without assigning origins, and a separate existing-body transfer test
verifies the unattributed marker survives a new peer receipt. Writer serialization and
the content/receipt transaction prevent another writer from interleaving that check.

Mistral identified missing peer-binding validation in the new helper. Its claimed
sender injection path was not demonstrated: the actual `receive_content` entry point
already validates the peer; an accepted offer references a durable peer row; and fact
description filters bindings against the local instance. Nevertheless, the helper's
own invariant could be stronger. It now requires foreign keys, an accepted inbound
offer, a matching peer, and a binding to the current database instance. A directed test
rejects an unregistered peer and a replaced local instance before recording any fact.

The reviewers' confidence scores are not test results or release approvals. The
coordinator accepted the useful guard/test suggestion, rejected the unsupported claim
of an existing remote exploit, and retained the full withdrawal/integration work as
open. There is no unanimous production-ready verdict.
