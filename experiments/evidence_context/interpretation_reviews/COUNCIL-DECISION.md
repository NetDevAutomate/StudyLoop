# Stage25 council arbitration

Two separate rounds used the same neutral brief within each round and the local
LiteLLM gateway. Meta Llama4 Maverick, Qwen3 Coder and Mistral Large3 responded in
both rounds. The result round received implementation code and measured results.
This is provider diversity, not proof of independent training, reasoning or humans.

Private request/response artifacts are in the Stage25 directory under the existing
`studyloop-private/reviews` workspace. They contain synthetic examples and code.
No private conversation text was needed for this increment. The three-case live
pilot is a separate experiment; its plain-JSON acceptance was one provider out of
three and must not be confused with the council helper's three valid responses.

## Design decision

Retain immutable observation payloads and add a typed review-target table. Keep
native source metadata separate from attributed review verdicts. Reuse source
dependency/purge and supersession/retirement behavior. Expose disputed and uncertain
reviews as evidence for the agent, without an independent-approval or truth flag.

Meta requested evidence against authority laundering. Qwen favoured the direction
conditionally and requested clearer producer/dispute semantics. Mistral preferred
dedicated payload tables and enforced reviewer independence. The useful concerns
became explicit adapter-owned fields, same-producer supersession restrictions,
all-dependency scope checks, atomic packing, coverage status and negative tests.

Separate payload tables do not establish independence or semantic correctness.
Typed foreign-key targets plus immutable, explicitly `model_interpretation` bodies
provide a structural boundary while avoiding duplicate lifecycle machinery. This
is a maintainability choice, not a benchmark proving superior scalability.

## Result review: accept the limits, test alleged defects

Qwen approved further internal integration testing subject to full release work.
Meta and Mistral rejected shipping. We also do not claim this increment alone is
shippable: the full P01–P15 contract remains open. Their implementation allegations
still need individual evidence; a majority recommendation cannot replace that.

| Concern | Arbitration and evidence |
|---|---|
| Adapter labels do not establish independent reviewers | Accepted. Every returned review/assessment says independence is not established. Same-label clients can revise each other; this is not authenticated multi-user authorization. |
| Model support might be mistaken for semantic validation | Accepted as a consumer risk. `attributed_support_available` explicitly retains semantic validation and validation of change as not established. Native fields are immutable and forbidden in submitted review documents. |
| Target hash is not recomputed during `get()` | Rejected against `ReviewStore.get`, which recomputes `_hash(_json(target[0]))`. The corruption test changes the stored binding outside the supported writer and proves direct rejection plus `incomplete_evidence` in assessment. |
| Target might mutate between append/read | Supported writers reject assertion, citation and relation updates; append and binding share the transaction. Public writes begin immediately and reads hold a snapshot. General concurrent-load benchmarking remains unperformed. |
| Deleting observations leaves dangling review-target rows | Rejected against the observation foreign key's `ON DELETE CASCADE`, target deletion triggers, and assertion/source/relation dependency tests with `foreign_key_check`. Full sync/restore lifecycle remains open. |
| `ValueError` in review retrieval silently hides coverage gaps | Rejected against `ReviewStore.list`, which marks the result incomplete. The corrupted-binding assessment test verifies the propagated incomplete status. |
| Reusing the cutoff value twice permits future evidence | Rejected. The two parameters implement the optional-time predicate `cutoff IS NOT NULL AND recorded_at > cutoff`. Six future-dependent reviews cannot consume the limit or hide one permitted current review in the targeted test. |
| Markdown-fenced JSON rejection creates operational failures | Accepted. Strict acceptance is one of three batches. No format-normalized result was stored. A future normalization policy needs separate tests and explicit measurement. Format compliance does not grant native or human authority. |
| The tiny pilot represents real-world reasoning quality | Rejected as an assumption. The brief explicitly identifies three simple synthetic cases, no human grade and no representativeness claim. |
| Cross-producer supersession evidence is missing | Already tested through unit tests and actual installed CLI/MCP stdio. Same-adapter identity limitations remain explicit. |
| Larger-scale performance and human usefulness evidence are missing | Accepted. These remain part of the full delivery/evaluation work. |

No further council calls were used to obtain an approval. The final two integrity
tests and the synthetic transport rollback test check the disputed mechanisms
locally. The result round saw 18 review tests and earlier regressions; the final
suite now has 20 review tests plus two lesson/pilot tests, all passing.

## What changes next

The experiment supports keeping attributed assessments and their exact dependencies
available to the context consumer. It does not show that a graph database improves
answers. SQLite stays canonical; relationships remain typed rows with rebuildable
projections. The semantic next test should distinguish source attribution, actual
entailment, revision applicability and decision sufficiency on harder examples.

Continue the full production work: remaining learner-data ownership, per-peer
scoped sync, managed forgetting/restore/reimport, shared setup/doctor/skills and
installed StudyLoop startup. Keep each stage independently runnable and retain the
unsuccessful strict pilot as part of the learning record.
