# Stage38 council decision

Three rounds used Meta Llama4 Maverick, Qwen3 Coder and Mistral Large3 through the
configured LiteLLM gateway. All three providers returned in each round. Packets used
code, fictional tests and aggregates; no new real transcript excerpt was required.
Private request/response artifacts remain under the Stage38 review directory.

## Decision

Keep the configured SSH coordinator, durable recovery and strict operation allowlist.
Accept this as a bounded canonical transport checkpoint after the observed corrections
and regression tests. It does not complete the production goal: large scopes, full-store
lifecycle, managed restore, shared setup/doctor and remaining consumers remain required.

| Review input | Evidence and decision |
|---|---|
| Simplify protocol phases or relax the operation allowlist | Retain receiver-owned peer identity and fixed operations. Recovering accepted interest before routing retirement is necessary after a lost response; arbitrary path/SQL support would remove that boundary. |
| A control round might not converge | Accepted. Added finite eight-round refusal and tests for a new control during reconciliation and continuously changing controls. No eventual-convergence promise under continuous writes. |
| There is no durable log, schema check or control validation | Not supported by the supplied code: offers/receipts, `policy` negotiation and the control barrier already exist. The review did motivate direct late-change and recovery tests. |
| The unchanged shortcut might overlook a mutation | A directed receiver-insert test failed against the initial implementation. Access revision intentionally ignores new bodies. Added separate content revision, receiver confirmation and final control checks. |
| Verify new counter coverage, historical receipts and overflow | Added coverage across all 29 projected tables and three mutations, source/receiver append tests, unrelated-work invalidation and overflow rollback. Historical schema45 acceptance recovery is tested; new body release remains refused. v1 receipts never justify unchanged. |
| Global versus scoped invalidation | The counter is deliberately global. The work-only mutation test proves that it invalidates the shortcut but does not transfer excluded work. Scoped counters are a later efficiency choice. |
| More diagnostics and scale measurements | Remain open. Generic errors prevent body-bearing peer stderr from leaking; sanitized doctor diagnostics and large/incremental transfer acceptance are production work. |

The corrective round conditionally supported the counter separation. Its confidence
numbers are opinions, not probabilities or proof. The initial result round did not
unanimously approve the implementation. Coordinator decisions follow the concrete
code and failing/passing cases rather than model votes.

## Independent regression findings

The broad memory suite found six additional failures after the counter correction:
compaction collided with the destination's seeded counter, and hot/full archival proof
incorrectly compared per-instance counters. Excluding that bookkeeping from copy/proof
fixed the existing tests without weakening comparison of actual content rows.

The initial broad run also exposed a test that assumed `CLAUDE_CONFIG_DIR` was unset.
The test now clears it only while testing the constructor default. Other tests retain
the isolated directory, preventing owner Claude configuration changes.

## Review limits

The result packet included the complete endpoint/coordinator/wire/SSH/server/fence,
policy and ledger files, but described rather than fully included permissions, content,
snapshot, lifecycle and CLI/test files. The corrective packet added full snapshot and
response-access code plus the schema46 migration. The coordinator inspected those
boundaries locally and ran the production tests. Council coverage is not a complete
independent audit of the entire accumulated implementation.

Actual installed CLI/SSH checks establish one fictional two-node run. Process tests
cover lost replies, file changes, malformed frames, late controls and offline ordering.
Neither establishes all network interleavings, an engine advantage, semantic answer
quality, managed-restore safety or production release readiness.
