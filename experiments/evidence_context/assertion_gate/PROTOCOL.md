# Stage 15: typed evidence claims (frozen before live execution)

Question: can an agent select useful claims while code prevents their event state,
evidence basis or target identity from being overstated relative to reviewed labels?

## Design and pre-run expectations

Eight development cases, raw/annotated arms, two repeats each: 32 calls maximum.
Qwen3-Coder, temperature zero, unchanged Stage 15 prompt for every call. The prompt
is new relative to Stage 14; no direct causal comparison with that stage is valid.
Two workers; randomized request order with fixed seed 1505. No answer regeneration.
Bundle, prompt and executing source hashes are frozen before calls; malformed answers,
provider errors and omitted useful claims stay in the denominator. No live retry.

The public demo uses eight synthetic cases. The actual run substitutes one manually
annotated historical two-passage StudyLoop anchor from the saved Stage 12 snapshot.
It uses seven synthetic cases plus that anchor. Neither collection is human-labelled
held-out evaluation. The simulated observed fixtures declare a tool-observation
basis; they do not contain independently authenticated tool artifacts.

| Case | Expected released assertion IDs | Purpose |
|---|---|---|
| separate_events | E1, E2 | Cleanup reported completed; separate correction still in progress |
| reported_pass | E1 | Preserve a useful report without calling it observation |
| observed_pass | E1 | Scoped simulated observation |
| identical_report | E1 | Same visible text as observation, different hidden basis |
| unknown_state | E1 | Unknown execution state is useful information |
| wrong_revision | none | r7 cannot establish r8 |
| unknown_target | none | Missing component/revision stays missing |
| explicit_correction | E2 | Old completion report yields to explicit unknown-state correction |

Raw inputs for observed_pass and identical_report are exactly identical. Their hidden
basis differs. This is an information-omission control, not a fair test of guessing
provenance. Report raw ledger conformance descriptively; do not score basis inference
as reasoning accuracy. Conservative abstention on missing provenance is appropriate.
Annotated inputs disclose the reviewed labels, so copying them is sufficient. High
conformance in that arm does not demonstrate independent evidence interpretation.

## Code gate and trust boundary

Claims must match assertion ID, scope, project, requested target/revision, state and
basis, with exact excerpt hash/span. Superseded claims are withheld; a malformed,
self-referential, cross-target or dangling correction is an explicit metadata error.
It fails closed and may withhold useful content until annotations are repaired.
This structural check does not establish that a correction is semantically justified,
resolve multi-step cycles, or authenticate either endpoint.

Code renders accepted claims independently from reviewed ledger values. Model prose
is retained only as advisory material in the replay. The gate is not semantic
extraction, general answer certification, or evidence authenticity verification.
Source hashes bind saved excerpts, not whole original messages or event truth.

Twenty offline controls include two deliberate ledger forgeries (state and basis)
that keep the text/hash intact. Expected semantic rejection is compared to actual
release. These known failures must remain visible, not counted as successful guards.
Eighteen other controls test release, selective blocking and malformed metadata.

Measure: response/parse failures; per-case selected and released IDs; blocked reasons;
omitted justified claims; unexpected released IDs; code-prose leakage controls.
Keep counts by condition and repeat. Repeats are not independent new questions.
Raw/annotated comparisons measure information availability plus label exposure.

## Council amendments before freeze

Fable approved the eight expected ID sets and requested explicit raw-input caveats,
a basis-forgery control, a dangling-correction check and stronger trust qualification.
Qwen supported the conditional contract test. Mistral objected to unauthenticated
observed labels: retained as a boundary warning, not grounds to remove a synthetic
fixture. Grok returned no usable response. Source scope/project/type guards and
these extra controls were completed before freezing; the initial review packet is
preserved unchanged. Results will receive a separate bounded council review.
