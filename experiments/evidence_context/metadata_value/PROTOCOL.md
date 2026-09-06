# Stage 10 pre-run protocol

Frozen before any live extractor or answer calls. The initial six-case three-arm
proposal was challenged by all three council reviewers as a fault-handling probe
rather than a utility comparison. This revised protocol is the coordinator's response;
it was not presented to the council as already re-approved.

Eight synthetic sources, including two longer noisy logs, four justified choices and
four required abstentions. Source format remains deliberately narrow. No independently
authored real holdout exists. Labels and verifier share coordinator assumptions.

Eight source-only extraction calls (no target or expected label). Preserve original
extractions. Inject four predeclared faults afterwards: invented missing revision,
a plausible fabricated revision quote against an r1 source, a winner quote taken from
outside the observation block, and selecting one of two contradictory revision lines.
Distinguish natural extraction errors from these seeded mutations.

Two answer samples per condition, temperature zero, no seed, no guarantee of identical
responses. Rotate condition order by case/repeat. All arms receive identical source,
kind, target, question and system prompt. Case IDs, expected labels and fault objects
are excluded. Conditions:

- raw: source only, 16 calls;
- extracted: source plus original unmodified extraction, 16 calls;
- checked: source plus checked candidate metadata (mutated in four cases), 16 calls;
- candidate: source plus unchecked mutated metadata, four fault cases only, 8 calls.

Total cap: 64 calls, including extraction. No answer/extraction retries, no tuning.
Candidate has a smaller denominator. Compare arms on common cases and repeat indices.
The unchecked candidate and checked conditions intentionally test fault recovery;
raw versus extracted estimates a narrow clean-metadata context effect. Checked versus
raw tests whether checking creates any net benefit or harm on the supplied examples.
The contexts are not token-matched: cost/latency comparisons are descriptive only.

Predeclared metrics: exact extracted field/value/quote agreement with the log grammar;
choice matches; unsupported endorsements (wrong A/B, including when abstention is
required); missed justified choices (none when A/B justified); invalid responses;
source-locatable citations. Quote location is not semantic entailment.

Baselines: always-none matches 4/8 cases (50%). A naive follow-metadata-winner policy
chooses the candidate winner when source kind is artifact and that winner is A/B,
otherwise none; it deliberately ignores scope and will be reported as a comparator,
not a recommended policy. Paired outcomes are reported by scenario, not significance.

Usefulness requires more than correct labels: review explanations against sources,
report metadata-induced regressions, and retain no-benefit outcomes. Two repeats can
expose instability but do not establish reliability. No claim of general usefulness,
source authenticity, arbitrary prose verification, token efficiency or production
readiness follows. The Stage 9 release policy is not in this experiment's answer path;
all model responses remain unverified drafts.
