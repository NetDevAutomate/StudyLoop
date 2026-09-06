# Stage 14 results: evidence selection improved; interpretation still blocks acceptance

24 fresh answer calls, same four development questions, unchanged Stage 12 prompt/model.
All 24 parsed as original JSON and passed schema. These are diagnostic observations,
not a held-out efficacy or product acceptance score.

## The decisive case: browser Parking checks

| Condition | Required source facts supplied | Relevant results recovered in both answers? | Remaining interpretation failure |
|---|---:|---|---|
| Original retrieval | 0/4 | No | Plans/earlier workflow became completed Parking checks |
| Reviewed passages only | 4/4 | Yes | Agent reports became claims that CRUD/cleanup were actually validated |
| Reviewed plus nearby material | 4/4 | Yes | In-progress port correction became completed correction |

The reviewed packs recovered the unsafe-default finding, correct card operations,
persisted reload result and cleanup report. This supplies a concrete target for a
better retriever. We did not implement an automatic way to select these passages.
Their selection used known labels, and all cases were reused from development.

The two clean-reference answers also correctly left the port correction unresolved.
Both filled-reference answers said it was corrected, although the source says the
agent is making the correction. Their limitations acknowledged report-only evidence,
but that did not repair the unsupported completion claim.

The coordinator judges all six Q3 drafts unsuitable for release under the frozen
contract, for different reasons. This is a case-specific analyst judgment, not a
human-adjudicated accuracy estimate. The council's results and erroneous findings are
separately recorded in COUNCIL-DECISION.md.

## This does not establish a pure distraction effect

Q3 original used 1,001 evidence tokens, reviewed-only 540 and reviewed-plus-original 852.
The common budget is1,400 tokens/six passages, not matched actual length. Adding nearby
material changes density and position as well as content. The two added passages are
only a subset of the original pack. A new counterbalanced experiment is needed to
attribute the observed regression specifically to distraction.

Q2 has the same six passages in original and filled-reference, reordered; its main
explanation and unknown-completion status remained intact in all six answers. One
citation in a filled answer supported only part of its attached claim, while another
passage in the pack supported the full statement. Provenance still needs careful binding.

Q1's browser choice remained stable. Supplying repository checks did not reliably
make the answer distinguish them from applicable voice validation. Some clean answers
used ambiguous blanket wording about no test records; filled answers invented a more
specific entity, an iPad version of OpenVox, from an underspecified user reference.
These are analyst-identified ambiguities, not a robust ranking of the three conditions.
Exact test counts were optional in the frozen rubric, so omission alone is not failure.

Q4 always selected insufficient evidence and invented no benchmark. With an empty
pack, however, both answers made broad historical absence statements before acknowledging
missing evidence. Category-level abstention therefore does not settle prose scope.
The nonempty control answers explicitly scoped absence to the provided evidence.

## Mechanical measurements

| Condition | Calls parsed/schema-valid | Exact quotes / citations | Validated-status flags | Gateway answer cost USD |
|---|---:|---:|---:|---:|
| original | 8/8 | 20/23 | 0 | 0.007828 |
| reviewed_only | 8/8 | 20/22 | 0 | 0.006574 |
| reviewed_plus_original | 8/8 | 18/24 | 0 | 0.008631 |

11 quote mismatches across7 answers; some were punctuation changes and some used the
wrong passage ID. Exact matches still do not prove claim support. Total gateway-reported
answer cost was **$0.0230328**. Council costs are not retained by the council wrapper,
so this is not the total bill. All evidence statuses were reported_only or insufficient,
even where prose overclaimed. No draft was automatically accepted.

## The next implementation target

Represent **what a source claims happened** separately from **how it is evidenced**:

- Reported event state: planned, in progress, reported complete, unknown.
- Evidence basis: conversation report, attributable tool result, authenticated artifact.
- Target: the specific workflow/component/revision the claim concerns.

The next bounded test should ensure that a cleanup result can be reported while a
separate code fix remains unconfirmed. A verifier must also avoid false blocks on
honest reported decisions. This calls for source-linked assertions and a calibrated
acceptance check, not more instructions appended to the current prompt.

Those fields and verification rules remain hypotheses to test on independently labelled
cases. We have not built reliable extraction by writing down the schema. Keep SQLite
canonical and defer engine changes: this iteration concerns information and meaning.
