# Stage 10 council arbitration

## Design review and the coordinator's changes

Fable 5.1 (Anthropic), Grok 4.6 (xAI), and Qwen3-Coder (Qwen) all returned valid
reviews of the initial six-case proposal. Their identical brief and raw responses are
preserved under observations/design-brief.md and observations/design-review/.

Accepted before the run: separate original extraction from seeded faults, add two
longer noisy positive examples, balance four justified choices with four abstentions,
keep source kind available to all conditions, use repeated answers, preserve fault
reasons, and add trivial baselines. The resulting eight-case protocol was frozen
before the live calls. It was not separately approved by the council before execution.

Not implemented: Fable's suggestion of at least five repeats per condition. We used
two within the 64-call pilot budget, retaining the limitation. Repeats do not replace
independent cases. We also did not introduce token-matched controls or human-authored
labels. Qwen's suggestion that fault isolation ensures clear causality was too strong:
checked fields, reasons and representation differ together.

## Result review

The identical result brief includes the revised protocol, source cases, metadata,
all 56 diagnostic answers with original strict statuses, scoring code, normalization
code and raw formatting examples. It is preserved as observations/result-brief.md.
Grok and Qwen returned valid structured reviews on the first attempt. Fable failed
its JSON response contract; that failed record is preserved. A bounded same-brief
retry also failed the JSON contract. Result review therefore has only two successful
provider buckets and is explicitly **insufficient diversity**, not a three-provider
consensus. No further retries were made. Both failed records are preserved.

Both usable first-round reviews caution against promoting metadata based on these
scores. Grok emphasizes that checked metadata adds no net choice matches and that
choice matches conceal quote-origin errors. Qwen recommends independently labelled
cases and better fault isolation. Their agreement is advisory, not independent
measurement of learner value. Qwen also reviewed its own provider's answer drafts;
this is not an independent model-performance audit.

## Coordinator decision

1. Preserve the strict results as operational failures; add the fence-only replay as
   an explicit post-hoc diagnostic. Neither replaces the other. No answer prompt was
   tuned and no experiment answer was rerun.
2. Treat explicit unknown metadata as a promising local observation, not established
   general utility. The entire gain is one missing-revision source repeated twice.
3. Do not use matched fields as permission to recommend. All fields can match a
   report without turning it into test evidence; an ambiguous field cannot be resolved
   by choosing the declaration that fits the target.
4. Keep citation origin and entailment separate. A locatable quote can support a bad
   inference; target metadata also needs a different locator from source text.
5. Keep the database choice open. These failures concern evidence semantics and
   acceptance policy, and neither SQLite nor a graph database resolves them by itself.

Accepted reviewer qualifications: the clean-extraction condition means uncorrupted
extraction, not complete source metadata; checked is not uniquely responsible for
fixing missing revision; formatting normalization is not original contract compliance;
and apparent authority from status wording remains an untested explanation.

Rejected as conclusions: Qwen's assumption of stable model behavior from two repeats,
and any implication that these labels are independent or that minimal observed gain
establishes minimal metadata value generally. Grok requested token/cache information;
per-call usage was already preserved, although independent cache verification and
request tracing were not done. Reported cached token counts were zero.

## One bounded next stage

First independently annotate the frozen missing/duplicate-revision and report answers:
choice permission, quote origin, and what the explanation actually claims. Reviewers
should receive source/target/policy and blinded condition names. Preserve disagreements
instead of treating a vote as ground truth.

Then connect narrow source checks to the Stage 9 code-owned acceptance boundary as
an independently runnable adapter experiment. Separate source kind, unique scope
match and permitted decision, and retain original evidence locators. Challenge the
adapter with these failures and clean positive controls. Measure blocked unsupported
decisions and incorrectly blocked justified decisions separately. The model may explain
a decision but cannot override a failed prerequisite or supply released prose unchecked.

Grok's suggested source-hidden probe is a useful alternative diagnostic, but hiding
source changes the available evidence and does not validate provenance. A wrapper-only
ablation could isolate apparent authority later. Neither is required to demonstrate
that the current answer path fails its policy. No additional experiment has been run
as part of this recommendation; no DSPy tuning or database migration is justified yet.

Readable council copies normalize trailing whitespace and final newlines only; private
original artifacts retain the exact bytes. Model-answer text inside JSON is unchanged.
