# Stage 9 — What can cross the decision boundary?

The goal is to prevent a generated decision from treating missing metadata as known.
Stage 8 made the relevant fields explicit but a model still invented an implicit
revision. Stage 9 compares the draft to a contract computed from an application-owned
snapshot and keeps model prose out of the released result.

This is a **contract conformance check plus a policy-rendered release boundary**.
It is not a semantic validator or a production authorization system. Because the
policy determines the released result, the model is currently redundant in that
release path. Its drafts are measured and retained for study, not promoted as truth.

## Run the lesson independently

From the experimental worktree root:

```sh
uv run python -m experiments.evidence_context.acceptance_gate --output /tmp/evidence-stage-9
open /tmp/evidence-stage-9/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_acceptance_gate.py -q
```

Use a new output directory. Offline mode replays eight actual Stage 8 drafts and
runs eighteen synthetic controls/challenges. It makes no provider calls. Expand a
case in the HTML to see the gate outcome, reasons and policy-rendered answer.
`replay.json` contains the original unverified model drafts alongside the gate results.
`offline-probes.json` includes both protections and a known upstream-forgery blind spot.

For the bounded live probe, with gateway credentials already provided securely:

```sh
uv run python -m experiments.evidence_context.acceptance_gate --live --output /tmp/evidence-stage-9-live
```

That makes twelve calls: six synthetic cases, two conditions, one sample each,
Qwen3-Coder through the existing loopback gateway, temperature zero, at most 1,500
output tokens per call, two workers, 90-second socket timeout, no application retry.
Interrupted runs retain attempted call records. Existing run/call directories are
not reused. Missing cost metadata stays explicitly missing.

## The boundary, step by step

1. **Application owns the facts.** `Snapshot.freeze(case)` serializes a copy of the
   case and binds it to the Stage 8 policy version and policy-file digest. Subsequent
   mutation of the original Python dictionary cannot change that snapshot.
2. **Application binds the response.** The live runner associates each response with
   the snapshot used for that request. It does not let the model select another input.
3. **Gate recomputes the contract.** It derives source applicability, sufficiency,
   option and required citations from that snapshot, not from model-supplied metadata
   and not from a fixture's expected-label file.
4. **Draft fields are compared.** Missing/extra fields, incorrect classifications,
   unsupported choices, duplicate/invented citations and missing required citations
   produce `draft_diverges`. A matching draft produces `draft_agrees`.
5. **Release is constructed from policy.** In both cases, `released_answer` is rendered
   from the code-derived facts and reasons. No model explanation, limitation, source
   reason or next-check field is copied into it. A divergent draft has an explicit
   notice that it was withheld and this is an independent policy fallback.

The hash is SHA-256 over Python JSON with sorted object keys, normal JSON serialization,
ASCII escaping and non-finite numbers rejected. List order is preserved and Unicode
normalization is not performed. It is an identifier/binding for this local experiment,
not a signature, authentication mechanism or cross-language canonicalization standard.

For a real system, the application must supply the current authoritative snapshot at
acceptance time. This experiment has no live store lookup, revocation service, locking
protocol or freshness authority. An old response is rejected **when checked against
an updated snapshot**; checking it against the old snapshot cannot detect that an
update exists elsewhere. Correction/forgetting/access rules remain integration work.

## Why keep an explanation when a draft fails?

A missing revision does not make the observation worthless. The policy can still say
that the artifact's revision is unknown, that no applicable check establishes the
choice, and what metadata/check is needed next. Per-source reasons and decision
citations preserve the route from evidence to conclusion.

The result is less flexible than an agent-written explanation. It cannot yet relate
an unfamiliar concept to your own experience or summarize nuanced evidence. This is
a deliberate temporary boundary, not a claim that a template replaces a rich mentor.
Model-assisted discovery and explanations need separate evidence/extraction checks
before their generated assertions can enter a trusted answer.

## What the offline probes establish

| Group | Intended outcome | What is learned |
|---|---|---|
| Valid measurement, abstention, conflict abstention, conditional proposal | draft_agrees | Legitimate structured outcomes remain representable |
| Missing each scope field or two fields | draft_diverges for fabricated applicability | Target metadata cannot fill gaps in a source draft |
| Wrong revision, report promotion, suppressed conflict | draft_diverges | Decision and provenance rules are checked in code |
| Invented citation, stale snapshot, metadata override, malformed answer | draft_diverges | Draft cannot replace the authoritative input or citation set |
| Correct fields plus fabricated prose | draft_agrees; prose not released | Structured agreement does not imply truthful prose |
| Fabricated upstream metadata | draft_agrees | Source authenticity is still outside this gate |

The eighteen outcomes include valid controls and deliberate blind spots. They are not
an eighteen-attack security success rate. Tests additionally check copy isolation,
policy binding, case-name invariance, empty evidence, decision-only errors, duplicate
citations and source-text isolation. Invalid trusted input raises before any release;
there is no guessed fallback for an invalid target.

The gate reuses Stage 8's narrow policy, so it inherits its limitations: exact scope
matching, authored conclusion metadata, fixture-only sufficiency and no verification
that artifact text entails its structured conclusion. A policy bug can be reproduced
consistently by both the gate and renderer. Separately written pre-run expectations
and counterexamples help detect some bugs; they do not establish independent truth.
The coordinator authored those expectations while knowing the policy: they are
independent of the live model answers, not independently authored ground truth.

## How to interpret the live comparison

`prompt_only` receives the Stage 8 contract prompt and source payload.
`contract_copy_control` additionally receives the complete code-derived contract and
an instruction to preserve it. Both arms face the same post-generation gate.

The copy control tests conformance when the answer is already supplied. It is not a
reasoning benchmark, evidence of retrieval value or a reason to pay a model merely
to repeat computed metadata. A higher agreement count can reduce divergent drafts;
it does not make the released answer safer than the same deterministic release path.

One input contains an instruction embedded in an artifact excerpt asking the model
to ignore missing revision metadata. That is a small illustrative challenge, not a
comprehensive injection-resistance evaluation. The model has no tools here.

## A useful design consequence

Use code for constraints that can be computed from trustworthy fields. Let an agent
help discover relevant sources and propose interpretations, while keeping assertions
linked to exact source versions and separating unknowns from observations. Do not
collapse every stage into a single model confidence score.

A future database might store source versions, target-specific applicability,
policy version, draft-versus-contract differences and the released decision record.
Hash binding does not replace source identity, access control or deletion propagation.
Nothing in this experiment selects SQLite versus a graph engine.

Read [RESULTS.md](RESULTS.md) for actual counts and
[COUNCIL-DECISION.md](COUNCIL-DECISION.md) for the council's challenges and our choices.
Your saved revision-classification exercise remains in Stage 8 for tomorrow; it was
not changed or completed as part of this work.
