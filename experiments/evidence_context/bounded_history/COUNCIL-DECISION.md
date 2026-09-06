# Stage31 council arbitration

Both design and result rounds used the configured LiteLLM gateway and three distinct
provider buckets: Meta (`llama4-maverick`), Qwen (`qwen3-coder`) and Mistral
(`mistral-large-3`). All six calls succeeded after healthy preflights. Briefs contained
code and fictional fixture results. Comparison artifacts and all raw result responses
were inspected. Private evidence is retained under
`studyloop-private/reviews/2026-09-06-stage31-bounded-history`.

## Design decision

Meta and Qwen preferred scoped header selection plus current/history paging. Qwen
asked that an additional index wait for query-plan evidence. The recorded diagnostic
provided that evidence; schema 40 adds the ordered index without new durable caches.

Mistral's recommendation field rejected optionB while its explanation called it the
least harmful option. We did not resolve that inconsistency by counting votes. Its
concrete requirements were useful: preserve the entire current group atomically,
validate cursor state and visible anchors, avoid treating cursors as authorization,
and error rather than return partial context on work exhaustion. Those became tests.

## Result review and follow-up

All reviewers favoured keeping the increment subject to concerns. They saw the
initial installed benchmark (10,000 versions: 393.386 ms full cached control versus
13.251 ms first page),18 new cases and63 prior cases, the 8-check installed walkthrough,
and the schema 39→40 copy upgrade. Final verification followed the refinements below;
it is recorded separately, not attributed to the council's earlier view.

| Reviewer observation | Evidence and decision |
|---|---|
| VM steps do not bound actual wall time or Python work | Accepted limitation. The API and guide say exactly what is counted. Additional review found metadata/legacy bodies and learner-record fanout could be materialized before size/count checks; preflight checks now cover them, with six additional cases. No wall-clock guarantee is claimed. |
| Mistral: policy and scope are absent from cursor invalidation | Rejected as stated: both are in the cursor state, and the public response guard checks them again. Existing tests cover correction, forgetting, scope-away-and-back and mid-read changes. An explicit changed-policy/same-visible-parent case now verifies the exact disputed scenario. |
| Mistral: dependency and work omission reasons are indistinguishable | Rejected as stated: `dependency_limit` differs from byte and current-candidate reasons; VM exhaustion raises a separate no-result exception. The guide and MCP instructions now explain consumer handling. |
| Qwen: omission/continuation may confuse consumers | Accepted UX requirement. Continuations explicitly exclude current bodies; final historical pages stay partial. Actual CLI/MCP tests traverse without duplicates and reject stale continuation. Full StudyLoop startup consumption remains separate acceptance work. |
| Qwen: unsigned cursors may permit malicious reuse | Scope filtering is repeated and the anchor is checked. A cursor conveys no authority. A caller can choose another visible anchor, so a cursor never certifies complete history consumption. HMAC is not needed for this local hint contract. |
| Meta: withholding same-information answer superiority is too cautious | Rejected. The first page returns fewer bodies than the control. Performance alone cannot establish answer quality or equivalent information. |
| Mistral: immediate production goal is met | Rejected. P07 transport, lifecycle, files, setup and other delivery requirements are still open. No model vote changes that checklist. |

The final refinement preflights the whole stored report row, not only its payload,
includes learner-record links in the fanout cap, and preflights legacy values before
loading them. It does not add a new index/cache, alter the current-group rule or
change the evidence into semantic validation. Malformed cursor versions also require
an actual integer rather than accepting a JSON boolean as 1.

Keep this independently runnable increment and proceed to scoped transport/lifecycle.
There is no need to rerun reviewers until they produce desired approval wording.
The unresolved whole-product requirements are carried forward explicitly.
