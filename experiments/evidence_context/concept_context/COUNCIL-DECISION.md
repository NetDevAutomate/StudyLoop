# Stage29 council arbitration

Both rounds used the same brief per reviewer through the healthy local LiteLLM
gateway. Meta (llama4-maverick), Qwen (qwen3-coder) and Mistral (mistral-large-3)
all returned valid independent responses. Private briefs and raw outputs remain
in the dated Stage29 review directory; no real conversation excerpts were needed.

## Design

All three preferred the existing owned observations plus live bridge projection.
This matches the actual code's reusable ownership/retirement primitives and avoids
a second graph copy before its value is measured. We did not rebuild the owner
registry or globally remap legacy concept identities.

Mistral also proposed treating unknown paths as personal. That contradicts the
explicit scope requirement and was rejected. A later Meta suggestion to reconsider
that restriction does not override the requirement either. Unknown files do not
acquire personal ownership from an active harness or default scope.

## Results: a split review

Meta and Qwen gave conditional acceptance; Mistral recommended rejection pending
semantic validation and more edge-case tests. These are review opinions, not votes
that authorize a release. The production goal is still active.

| Review point | Coordinator decision and evidence |
|---|---|
| Semantic validation is missing | Correct limitation. Preserve `not_established`; provenance cannot create semantic proof. This increment claims safer representation/use, not generally correct advice. |
| Partial coverage may omit decisive context | Accepted. Return complete contributions, `coverage=partial` and `semantic_arbitration=not_performed`. Unicode-budget test proves omission is explicit. Useful semantic selection remains open. |
| All-visible projection cost is unknown | Accepted. Added independent installed scale script: medians17.647/34.158/110.561 ms for 100/1,000/5,000 visible plus equally many excluded short bridges. This is query/packing work, not engine comparison. |
| Forgotten/changed owner and conflicting legacy cases need tests | Existing ownership, independent-parent, correction and legacy-shadow tests cover these; added forget-after-reclassification-then-return test and explicit unclassified retirement cases. |
| Any reported prerequisite label may imply a direction | Tightened the contract to `prerequisite`: source is the reported prerequisite of target. Ambiguous `requires`/`depends_on`, headings, backlinks and analogies remain context, not prerequisite recommendations. Five extra parameterized cases verify this. |
| Rejecting old source_type imports could break a valid projection | Intentional change. Live owned bridges remain useful without copying. Modern file/global-edge imports require their own source ownership integration; the limitation is explicit and tested before source reads. |
| Quality and mapping fields might be misleading | Preserve them as reported content with source IDs/hashes and `not_established`. The literal quality `validated` cannot promote authority. They are not executed or taken as prerequisite facts. |
| Legacy aliases/message links might have unknown consumers | Accepted audit limit. Static search is evidence about this repository, not all external users. Sync/tiering/managed lifecycle remain release requirements. |

Full StudyLoop rerun passed3,816 tests (4 skips,704 deselections) before the final narrow
prerequisite direction and reported-legend changes. Final168 focused tests include direction, scope,
retirement, HTTP/MCP, history regressions and the runnable lesson. Workspace type
checking passed. Both initial and rebuilt-final fresh wheels passed10 actual HTTP/MCP
checks. Combined memory/experiment regression passed1,584 tests with1 optional skip.

The initial broad run found old web fixtures missing Stage28's required generation
schema. Those fixtures now use canonical migrated storage and verify the actual
observation payload written by the production route. We did not weaken the response
boundary to satisfy an obsolete fixture.

No claim is made that numeric bridge weights, a council majority, or passing mechanical
tests establish the correct learning recommendation. The next performance question
is selective retrieval under a work budget; complete file ownership/lifecycle and
installation remain required before shipping the whole feature.

The coordinator also found an older legend claiming a full review from a mastery
category. The legend now describes reported assessments, and a regression checks
that the label is not presented as validation. This was an additional code-review
finding, not a council-verified claim.
