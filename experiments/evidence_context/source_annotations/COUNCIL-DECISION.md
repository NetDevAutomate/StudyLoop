# Stage 16 council arbitration

Decision: do not promote the current annotation pipeline. Preserve it as a completed
learning checkpoint. The next bounded experiment should make capture-derived fields
code-owned and measure whether that recovers useful claims without erasing narrative
interpretation failures. The current prompt, trial code and all forty answers remain
frozen. No production changes or model retraining were performed.

## Design review and amendments

Fable 5.1, Grok 4.6, Qwen3-Coder and Mistral Large 3 all returned usable design reviews.
Their common concern was ambiguity about which information the model receives and
which checks belong to the recorder/adapter. Before execution I published explicit
per-arm expectations, target/state/quote conventions, missing/corrupt-origin behaviour,
decoding settings, separate annotation/release metrics and an adoption criterion.

Accepted: basis/scope stay unknown/null without a verified origin; requested identity
cannot supply source identity; completed denotes command execution rather than pass;
invalid envelopes are removed by code; receipt verification is not model skill.
Fourteen deterministic controls retain correctly sealed but incorrectly interpreted
annotations alongside actual integrity defects. Cases and instructions were frozen
before the first model call.

Not adopted: deleting most adapter cases or marking every raw field unscorable. Raw
hidden origin truth is unscorable, but preservation of unknown origin is a measurable
instruction contract. State/target extraction and adapter behaviour are separate
measurements. Retaining the small control deck helps inspect boundaries; it does not
make the cases a general benchmark. Grok preferred unknown state on the altered body;
our explicit policy extracts the text's stated state while retaining unknown origin
and withholding release. That policy is not a claim that altered text is true.

## Initial full-result review

The full packet contained all forty annotations/releases, receipts, source checks
and controls. Qwen and Mistral returned usable reviews; Fable returned no valid JSON
object and Grok timed out. This round had insufficient provider diversity.

Both usable reviewers suggested promotion of the capture arm. That advice is rejected:
the frozen adoption rule failed on six capture-arm origin assignments. A15/A20 selected
observed against a verified conversation receipt, and missing/rejected-origin cases
also selected observed. Correct behaviour on four straightforward process examples
cannot stand in for the whole arm.

Qwen's statement that capture annotations achieve 100% field match cited only
A03/A11/A21/A28. Whole-arm four-field agreement is 14/20. Its suggestion that failed_exit
conflated task failure with annotation error is unsupported by A21/A28, which correctly
retain completed execution and exit status 3 without claiming success. Its text-origin
count also blurs sixteen observed assignments with two reported assignments.

Mistral's suggestion that first-person scope inference could be legitimate pattern
recognition conflicts with the explicit scope contract. Both A07/A24 inferred personal
scope without metadata. Matching the hidden fixture receipt does not justify that
inference. The adapter's independent check prevents this lucky match from being a
false output claim, but it does not improve the model's evidence discipline.

The full reviews are retained verbatim. A smaller audit isolates six diagnostic
examples (A06, A07, A15, A17, A20, A21), including honest reports and a legitimate failed
process, so reviewers must distinguish successful cases from origin overclaims.

## Focused result audit

All four providers returned usable responses to the same six-example audit. This is
four-provider coverage of selected diagnostics, not four-provider independent review
of all forty outputs. The full result round remains a two-provider round. Qwen was
also the answering model, so not every reviewer was a distinct answering lineage.

Fable and Grok correctly classified A06/A15/A20 as origin breaches, A07 as unsupported
scope/origin inference, and A17/A21 as contract matches. They distinguished an honest
report from observed evidence and completed execution from successful outcome. Their
recommendation to assign provenance fields in code is accepted. Mistral also favored
code-derived origin/scope, but excluding all narrative interpretation would remove
part of the user's intended value; retain and evaluate that separate responsibility.

Qwen again described A07 as acceptable inference and called A17 a text-arm case. Both
are rejected against the saved payload: A07 has no source-scope metadata, and A17 is
capture-arm. Its proposed additional prompt contrast is not the next experiment.
We already have a source authority that can assign origin/scope deterministically.

Some of Fable's cautions also need correction. Text scope 18/20 is agreement with
null under the information-available contract; A07/A24 are scored wrong. That metric
does not count their hidden-receipt matches as successes. Those appear only in the
separate adapter table. A15/A20 are repeated calls on one case, not two independent
cases; the study has always specified ten cases with two repeats. Its prose contrasts
are observable explanations, not proof of distinct internal reasoning mechanisms.

The focused audit suggests stronger new cases (negation, conditional execution,
body/envelope identity conflict). Those are useful for the next predeclared deck.
The current 20/20 target matches on simple fixture identities do not establish broad
semantic skill. A locked entailment rubric and independently reviewed new cases are
needed before claiming that narrative interpretation is dependable.

## Proposed next experiment and its evaluator

Replay the frozen forty drafts through two separate candidate paths:

1. The current compare-and-reject adapter, preserved unchanged.
2. A new adapter that derives origin and scope from verified receipts. Process
   execution state and invocation target can also be derived from the actual capture;
   narrative state/target remain model proposals requiring semantic support.

Keep each original draft intact. Record which fields code derived, the supporting
source reference and any model disagreement. Do not silently turn an incorrect model
annotation into a correct-looking model response.

The primary measurement is useful justified output retained with no unsupported
origin, missing-identity promotion or cross-scope release. It is plausible that source
ownership can recover the two spoofed-report claims that this stage unnecessarily
withheld, but this is a hypothesis for the next experiment, not a result already run.
Retain all integrity controls and the two known narrative-semantic failures.

An evaluator change is necessary before that comparison: judge the final released
field values against sources. A rederiving adapter may repair a wrong proposal rather
than reject it. Reusing a Boolean “bad input must be rejected” label would incorrectly
score a properly attributed repaired output as a false acceptance. Conversely, an
output with correct origin but incorrect narrative state must remain a false semantic
release. Keep repair, withholding and residual error counts distinct.

Use a few new independent cases to test the policy after the diagnostic replay. The
existing deck is development evidence, and a source-owned origin field is correct
by construction under the trusted-recorder assumptions. It is not new proof of
narrative entailment or general answer quality. Richer explanation/outcome fields
remain a separate question; changing them simultaneously would obscure what helped.

## Limits that continue to apply

A source receipt proves origin only under the recorder/manifest trust model. It does
not prove application success, Git revision identity, a correct natural-language
interpretation, or that installed coding harnesses export equivalent metadata. The
work-labelled case is synthetic and deliberately model-visible; production scope
filtering belongs before model retrieval, not merely after answer generation.

The result favors clearer ownership and preservation of evidence metadata. It does
not favor a different database engine. Keep SQLite canonical with replaceable derived
indexes while measuring which assertions are justified and useful. Prior stages and
the saved learning exercise remain unchanged.
