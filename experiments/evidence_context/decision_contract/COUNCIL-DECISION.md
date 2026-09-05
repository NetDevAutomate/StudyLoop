# Stage 8 coordinator decision

## Pre-run council

Three providers returned valid structured responses: Claude Fable 5.1, Grok 4.6 and
Qwen3-Coder. Fable and Grok explicitly labelled all eight cases; Qwen approved the
concept without supplying the requested individual labels. Do not describe that as
three independent sets of matching labels.

Accepted before the answer run:

- Separate supplied source kind from validation applicability and decision sufficiency.
- Add reason codes distinguishing no applicable observation from conflicting observations.
- Explicitly prioritize applicable artifacts over requirement-fit reports, including conflicts.
- Define required minimum citation coverage while permitting additional contextual citations.
- Test missing/mismatched scope, normalization choices, empty/dual fits, conflicting
  measurements, invalid combinations and evidence/text blind spots.
- Clarify one report's text so its recommendation of A and its admission of poor fit
  are explicit rather than confusing the meaning of its conclusion field.

Kept deliberately narrow: exact four-field scope matching; authored synthetic facts;
one fixture observation can support a fixture-only conclusion. This is not a real
verification policy. Source extraction/authenticity, independent reproduction and
statistical sufficiency are explicitly outside the measured behavior.

## Result review

The review packet included all sixteen actual answers and their full supplied inputs,
with shuffled IDs and arm/expected labels withheld. Schemas remained visible, making
blinding partial. Reviewers received the same decision contract. No reviewer votes
were used to change frozen labels or model outputs.

Fable identified the two unknown-revision failures and the legacy wrong-revision
endorsement. It marked the legacy requirement-fit abstention needs_review: the answer
was cautious and correctly explained the evidence gap, even though the declared mode
permitted a conditional proposal. I accept that distinction. A label mismatch is not
automatically bad reasoning or a harmful choice. The question's generic wording about
correctness leaves room for caution despite the structured requirement-fit mode.

Qwen's review is not reliable as a grade set here. For example, J02 correctly abstained
because its reports were unmeasured, yet Qwen called that answer unsupported because
there were no applicable artifacts. It also accepted J01's invented implicit revision.
Those grades confuse unsupported underlying claims with a well-supported decision to
abstain, and are rejected against the packet. Qwen is also the answer provider, so its
review is not independent provider validation. All raw readable judgments are retained.

The first result round had only two valid providers because Grok returned invalid JSON.
One retry used the identical brief and was treated as a single-provider retry, not
as a separate council. Grok also returned invalid JSON on that retry. We stopped there: result review
therefore has two successful providers, insufficient diversity for a strong
three-provider council. Both valid reviewers supplied all sixteen distinct grades,
but only Fable's grade set was consistent with the evidence on the disputed items.

## What the evidence supports

The contract exposed where a decision went wrong, and in one observed paired case
changed an unsafe wrong-revision choice into abstention. It also made a conditional
proposal explicit. It did not prevent the model inventing a missing revision. The
7/8 versus 5/8 choice match counts are smoke-test observations, not answer-quality
scores or evidence of reliable improvement across projects.

The deterministic reference correctly retains unknown scope. The LLM answer does not
always obey it. This supports separating enforceable metadata checks from explanatory
generation, rather than relying on longer prompt instructions to perform both.

## Next discriminating experiment

Freeze this stage. Next, test a boundary that keeps unknown source metadata unknown
and computes applicability from supplied fields in code before an answer is accepted.
It must not read a target revision into an artifact that lacks one. A blocked decision
should preserve the reason and request the missing check, not silently repair metadata.

Use new missing-field and near-match variants plus metadata/text contradictions. A
scope gate can enforce known facts, but cannot make extracted metadata trustworthy:
source-text entailment and original-artifact inspection need a separate test. Compare
failure types (unsafe endorsement, correct abstention, cautious deviation), rather
than treating all category mismatches equally.

Fable suggested five samples per variant and zero missing-scope inferences before
adoption. Repeated samples would characterize behavior, but zero observed failures in
a small sample is not proof of reliability. Prefer tests of the deterministic boundary
plus a pre-labelled, disjoint real-question pilot and independent explanation review
before product claims. Learner usefulness still needs actual user feedback.

No database engine or production prompt is selected. The design implication is to
store source provenance, target-specific applicability and decision derivations as
separate versioned records/relationships, with lifecycle and scope controls supplied
by earlier stages. SQLite can represent them; graph traversal value remains a separate
retrieval question.
