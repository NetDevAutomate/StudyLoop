# Stage22 council arbitration

## Decision

Keep the native capture implementation as a tested increment on the experimental
branch. Continue the full production goal. No merge, release or owner installation
was performed. The complete P01–P15 contract remains in
[delivery/GOAL.md](../delivery/GOAL.md).

Two bounded rounds used the local LiteLLM gateway. The first selected Grok4.6,
Llama4 Maverick, Qwen3 Coder and Mistral Large3. Meta, Qwen and Mistral returned
valid responses; Grok timed out. The result round used those three responding
provider lineages and all responded. Fable had returned invalid responses in
Stage21; this stage obtained a third lineage through Meta instead. These are three
provider perspectives, not three independent proofs or a release approval.

Both rounds sent the same brief to all reviewers in that round. The first included
the actual native collector, transaction adapter and batch writer. The second
included observed results, precise authority rules and the explicit remaining
release requirements. No actual transcript bodies were sent in these reviews.
Private briefs, selected model manifests, raw replies and comparisons remain in
`studyloop-private/reviews/2026-09-06-stage22-native-capture/`.

## Accepted concerns and their effects

| Concern | Evidence or action |
|---|---|
| Backfill after a parser upgrade needs proof | Added old-fingerprint simulation to the actual exporter test for each harness; unchanged archives repopulate native evidence |
| Failure and malformed-source handling need more than a happy path | Existing malformed-tail and all-layer rollback tests preserved last good data; a new interruption-after-INSERT test exposed an uncommitted transaction, now explicitly rolled back |
| Similar records need identity tests | Identical native records lacking IDs receive occurrence keys; a regression test proves both remain distinct |
| Media handling needs concrete boundary examples | A structured image block inside an invocation is omitted, while quoted image-shaped JSON in prose remains text |
| Scope configuration cannot silently change during capture | Tests prove root assignment changes, explicit owner preservation and unapplied policy-drift refusal |
| Capture health does not establish archive completeness or hook liveness | Both are explicitly `not_established`; tests cover no attempt, partial, failed, unavailable, interrupted and older-schema states |
| Small samples cannot justify release or scalability claims | The guide reports sample selection and raw units; format coverage, large backfill, installed hooks and lifecycle acceptance remain required |

The new interruption test mattered more than the reviewers' confidence scores.
An interrupted Python process could leave a pending transaction on a connection
that a caller later reused. The wrapper now rolls back for `BaseException`, while
keeping an interrupted attempt's durable receipt incomplete. Ordinary exceptions
still record a body-free failure class when the database remains writable.

The first full session-tools run passed 1,232 tests. After these additions the
full suite passed 1,237. The four-harness backfill test initially failed because
the test assumed all fingerprints used the same column: Kiro's existing importer
uses `metadata.kiro_import_fingerprint`. Correcting that fixture tested the real
compatibility path rather than changing a working importer to suit the test.

## Recommendations not accepted as stated

Mistral's first response claimed exit-code types were not validated. The supplied
code already used `type(code) is int`, and tests reject strings and Booleans.
Its assumption that session-start Git revision was copied into later executions
was also contradicted by the code and all 1,898 sampled records having null
revision. Neither claim is treated as a proven defect.

Qwen called the different harness exit semantics inconsistent. The difference
comes from the native evidence: a generic tool result, Kiro `Success`, and an
integer Codex process-exit envelope establish different things. Normalising all
of them to a successful process would lose information and manufacture authority.
The common schema supports unknown values precisely so adapters need not pretend
they have equivalent evidence.

Meta questioned leaving the source machine unknown. The current host establishes
where capture happened, not necessarily where a copied archive originated. The
capture receipt stores the former separately. Original-machine attribution needs
an actual native or registered source identity; a plausible hostname is not a fix.

The second round included assumptions that hook liveness could be addressed
after release and that eight sessions were being presented as sufficient evidence.
Neither was our claim. P09 and P15 remain release requirements, and the probe is
explicitly non-representative. We accept the missing-evidence concern without
accepting its mistaken attribution.

Mistral proposed a default-off feature flag. At this checkpoint the entire change
is isolated on the experimental worktree and has not been installed into owner
hooks. An additional flag would not establish correctness. Release gating remains
the full acceptance contract; the installer still needs clear capture choices
and health checks before shipment.

## How the result changes the next step

The real sample gives a useful data signal: 872 tool results and 162 typed
process-exit records are now available to retrieval, alongside conversation and
invocations. It does not supply applicable revision metadata, establish semantic
accuracy, or justify a different storage engine. SQLite can keep the new links
and atomic writes within the existing canonical database.

Next, complete the product paths that consume and control these sources: bounded
scoped retrieval and decision sufficiency, complete learner-state ownership,
versioned scoped sync and forgetting through restore/reimport, and installed
capture/doctor acceptance. Large and varied source-format probes belong in that
acceptance work. The production goal is not reduced to this successful increment.
