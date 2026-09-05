# Independently runnable learning stages

Run commands from the experimental worktree root. Each stage has an immutable Git
checkpoint so later changes cannot silently change the version you are studying.
These are local commits: preserving the repository preserves the checkpoints;
no remote publication or backup is implied.

| Stage | Question | Checkpoint | Entry point and guide |
|---|---|---|---|
| 1 — Evidence retrieval | Can reviewed relationships add relevant evidence while preserving citations and bounds? | `c262c08` | `python -m experiments.evidence_context`; README.md and ARBITRATION.md |
| 2 — Shared context requirements | What must StudyLoop and a standalone consumer both guarantee? | `46442cb` | `tests/test_shared_context_requirements.py`; REQUIREMENTS.md. This is an executable contract stage, not a separate visual demo. |
| 3 — Correction and forgetting | Can offline replicas converge without resurrecting forgotten content? | `b44145a` | `python -m experiments.evidence_context.lifecycle_demo`; STUDY-GUIDE.md |
| 4 — Capture health | Does configured capture actually yield recent history? | `ae2b250` | `python -m experiments.evidence_context.capture_health`; capture_health/GUIDE.md and COUNCIL-DECISION.md |
| 5 — Retrieval measurement | Does returned context contain the required evidence? | `1b9a658` | `python -m experiments.evidence_context.retrieval_eval`; retrieval_eval/GUIDE.md, EXPLANATION-RUBRIC.md and COUNCIL-DECISION.md |
| 6 — Conflict arbitration | Does the answer resolve conflicting evidence responsibly? | `66902e2` | `python -m experiments.evidence_context.arbitration_lab`; arbitration_lab/GUIDE.md, RESULTS.md and versioned prompts |
| 7 — Bounded prompt loop | Does our score recognise a better evidence-based decision? | `f3a8457` | `python -m experiments.evidence_context.prompt_loop`; prompt_loop/GUIDE.md, RESULTS.md and COUNCIL-DECISION.md |
| 8 — Decision contract | Which sources apply, and what decision do they justify? | `f7f6796` | `python -m experiments.evidence_context.decision_contract`; decision_contract/GUIDE.md, RESULTS.md and expandable HTML walkthrough |
| 9 — Code-owned release | Can model drafts override missing metadata or enter released prose? | `d7a9c8f` | `python -m experiments.evidence_context.acceptance_gate`; acceptance_gate/GUIDE.md, RESULTS.md and replay walkthrough |
| 10 — Metadata value | Does source-backed metadata improve decisions? | `620090a` | `python -m experiments.evidence_context.metadata_value`; metadata_value/GUIDE.md, RESULTS.md and actual-answer replay |
| 11 — Source to decision | Can code enforce evidence requirements without blocking justified choices? | `e1428be` | `python -m experiments.evidence_context.source_decision`; source_decision/GUIDE.md, RESULTS.md and saved learning walkthrough |
| 12 — Real retrieval pilot | Which selected history reaches and helps the answer? | `27e6900` | `retrieval_matrix/trial.py` and `report.py`; GUIDE.md, RESULTS.md, private real-answer replay |
| 13 — Equivalent storage | Which engine serves the same nodes, edges and rows? | `6fff879` | `storage_matrix/benchmark.py` and `query_diagnostic.py`; GUIDE.md and RESULTS.md |
| 14 — Evidence replacement | Do reviewed results improve answers, and what still fails? | `ec8bbc1` | `evidence_selection/runner.py` and `viewer.py`; GUIDE.md, RESULTS.md and reviewer audit |
| 15 — Separate evidence claims | Can state, basis and target stay distinct through code-owned release? | `4914967` | `assertion_gate/runner.py` and `viewer.py`; GUIDE.md, RESULTS.md and COUNCIL-DECISION.md |
| 16 — Source-backed annotations | Can captured origins ground labels without semantic overclaim? | `6c736c5` | `source_annotations/runner.py` and `viewer.py`; GUIDE.md, RESULTS.md and council audit |
| 17 — Code-owned provenance | Which labels are observations versus interpretations? | `106b65a` | `provenance_ownership/runner.py`; GUIDE.md and council audit |
| 18 — Canonical sources | Can immutable versions and exact citations preserve their boundaries? | `3502407` | `canonical_sources/runner.py`; GUIDE.md and council audit |
| 19 — Scope before retrieval | Do existing readers enforce explicit context scope? | `3aa1b8a` | `scope_boundary/runner.py`; GUIDE.md and council audit |
| 20 — StudyLoop consumers | Do scoped sources remain scoped in resume, extraction and history? | `36189ff` | `consumer_scope/runner.py`; GUIDE.md and council audit |
| 21 — Attributable assessments | Can each progress report retain its input, scope and correction history? | `918d18f` | `learning_observations/runner.py`; GUIDE.md and council audit |
| 22 — Native capture | Which authority can the actual session envelopes establish? | `3acbc6f` | `native_capture/runner.py`; GUIDE.md, observed aggregates and council audit |

Stage 3 uses its own lifecycle adapter and database schema. It does not modify the
stage 1 evidence store, and does not require stage 1 demo output. Stage 2 uses
stage 1 fixtures/code; its pinned checkpoint contains everything needed to run it.
Stages 1–11 use temporary/synthetic demo data. Stage 12 also provides an explicitly
private real-transcript replay. Use a new output path for every demo run; existing directories are deliberately not overwritten.

## Run from the current worktree

```sh
# Stage 1: keyword and reviewed-relationship retrieval
uv run python -m experiments.evidence_context --output /tmp/evidence-stage-1
uv run --group dev pytest experiments/evidence_context/tests/test_evidence_contract.py experiments/evidence_context/tests/test_snapshot_and_cli.py -q

# Stage 2: whole-pack scope boundaries and grounded explanations
uv run --group dev pytest experiments/evidence_context/tests/test_shared_context_requirements.py -q

# Stage 3: correction, offline deletion and stale replay
uv run python -m experiments.evidence_context.lifecycle_demo --output /tmp/evidence-stage-3
uv run --group dev pytest experiments/evidence_context/tests/test_lifecycle.py -q
```

Current-tree commands run the current implementation. For the exact historical
behaviour, use a checkpoint worktree instead.

## Freeze a stage without switching your working branch

From a checkout of this Git repository, choose one new directory:

```sh
git worktree add --detach /tmp/studyloop-evidence-stage-1 c262c08
cd /tmp/studyloop-evidence-stage-1
uv sync --all-packages --group dev
uv run python -m experiments.evidence_context --output /tmp/evidence-stage-1-frozen
```

Substitute `46442cb` or `b44145a` and a different directory for stages 2 or 3,
then run that stage's command above. A detached worktree is suitable for inspection;
create a branch there before making changes you want to keep. Dependency fetching
may need network access; the tests and demos do not call model providers.

## Convention for every following stage

- Keep prior entry points and demos working. Use a separate module/directory and
  disposable schema where a new design has different semantics.
- Record a completion commit here, plus exact setup, demo and test commands.
- Include a guide explaining the problem, alternatives, why we chose one, costs,
  observed results and what remains unproven. Include expected demo observations.
- Distinguish a contract-test stage from a user-facing demonstration. Never imply
  that a synthetic adapter validates an installed integration.
- Preserve synthetic fixtures; keep real transcripts and provider outputs private.
- Keep council advice, coordinator decisions and test evidence distinguishable.

## Stage 4 commands

```sh
uv run python -m experiments.evidence_context.capture_health --output /tmp/evidence-stage-4
uv run --group dev pytest experiments/evidence_context/tests/test_capture_health.py -q
```

Checkpoint `ae2b250` can be opened in a detached worktree using the same procedure.
The council reconsidered the order using all four stages' evidence. See
[capture_health/COUNCIL-DECISION.md](capture_health/COUNCIL-DECISION.md).

## Stage 5 commands

```sh
uv run python -m experiments.evidence_context.retrieval_eval --output /tmp/evidence-stage-5
uv run --group dev pytest experiments/evidence_context/tests/test_retrieval_eval.py -q
```

Checkpoint `1b9a658` preserves the runnable synthetic evaluator. It accepts a
separate dataset, but independent real held-out labels and efficacy are not yet
established. See retrieval_eval/HOLDOUT-PROTOCOL.md for that next evidence gate.

## Stage 6 commands

```sh
uv run python -m experiments.evidence_context.arbitration_lab --output /tmp/evidence-stage-6-v1
uv run python -m experiments.evidence_context.arbitration_lab --prompt-version v2 --output /tmp/evidence-stage-6-v2
uv run --group dev pytest experiments/evidence_context/tests/test_arbitration_lab.py -q
```

Default execution prepares offline. The guide explains explicit paid live runs and
includes readable preserved observations from both pilot rounds. Checkpoint
`66902e2` pins this development stage. The user requested this arbitration probe;
it does not replace or satisfy the independently labelled real-holdout gate.

## Stage 7 commands

```sh
uv run python -m experiments.evidence_context.prompt_loop --output /tmp/evidence-stage-7
uv run --group dev pytest experiments/evidence_context/tests/test_prompt_loop.py -q
```

Checkpoint `f3a8457` preserves this stage. Default execution is a scripted offline
loop; explicit `--live` uses the gateway with at most 18 calls. The guide separates
scripted demonstration from the preserved 16-call live run. Two full pre-loop
councils reviewed sources and blinded answers; result review had two valid providers
because Fable failed structured output twice. Both amendments improved the observed
queue recommendation, but a defective category proxy hid that change. The original
selector and results remain frozen for study.

## Stage 8 commands

```sh
uv run python -m experiments.evidence_context.decision_contract --output /tmp/evidence-stage-8
open /tmp/evidence-stage-8/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_decision_contract.py -q
```

Checkpoint `f7f6796` preserves the contract, eight fixtures, reference walkthrough,
pre-run expectations and sixteen actual model answers. Default execution is offline;
`--live` makes sixteen bounded gateway calls. The reference handles unknown scope
correctly, but the model invented a missing revision in one case. Choice matches were
7/8 new versus 5/8 legacy; these are not general quality scores. Three providers
reviewed the design; two returned valid result reviews after Grok failed twice.
The optional revision-classification exercise is saved for a later dedicated session.

## Stage 9 commands

```sh
uv run python -m experiments.evidence_context.acceptance_gate --output /tmp/evidence-stage-9
open /tmp/evidence-stage-9/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_acceptance_gate.py -q
```

Checkpoint `d7a9c8f` preserves the snapshot-bound draft comparison and code-owned
release. Offline mode replays eight actual drafts and eighteen controls/challenges;
`--live` makes twelve calls. Four live drafts diverged on missing scope, including
both injected-source drafts; none supplied the released decision/prose. Draft agreement
was 3/6 prompt-only and 5/6 in a precomputed-answer copy control. The release is always
policy-rendered, so this is conformance measurement, not model-answer certification.
Both council rounds returned all three providers. Upstream metadata forgery remains
an explicit blind spot. All 153 evidence-context tests passed at this checkpoint.

## Stage 10 commands

```sh
uv run python -m experiments.evidence_context.metadata_value --output /tmp/evidence-stage-10
open /tmp/evidence-stage-10/walkthrough.html
uv run python -m experiments.evidence_context.metadata_value.normalization_audit --input experiments/evidence_context/metadata_value/observations --output /tmp/evidence-stage-10-answers.json
open /tmp/evidence-stage-10-answers.html
uv run --group dev pytest experiments/evidence_context/tests/test_metadata_value.py experiments/evidence_context/tests/test_metadata_normalization.py -q
```

Checkpoint `620090a` preserves the source verifier and 64-call pilot. The
first walkthrough is offline/reference; the second replays actual answers without
provider calls. Original strict JSON parsing accepted only 9/56 answer drafts. A separate
post-hoc fence-only diagnostic found choice matches of raw 12/16, original extraction
14/16 and checked 12/16. The gain was one missing-revision case repeated twice; checked
introduced a report-only regression. All conditions failed duplicate revision. These
are development category scores, not validated answer quality. All 173 experiment
tests passed. See the council decision for review coverage and limitations.

## Stage 11 commands

```sh
uv run python -m experiments.evidence_context.source_decision --output /tmp/evidence-stage-11
uv run python -m experiments.evidence_context.source_decision.viewer --input experiments/evidence_context/source_decision/observations --output /tmp/evidence-stage-11-learning.html
open /tmp/evidence-stage-11-learning.html
uv run python -m experiments.evidence_context.source_decision --replay experiments/evidence_context/source_decision/observations --output /tmp/evidence-stage-11-replay
uv run --group dev pytest experiments/evidence_context/tests/test_source_decision.py -q
```

Checkpoint `e1428be` preserves twelve condition checks across eleven source/target
pairs, with pre-run model-reviewed labels and one recorded dissent. The 24 draft calls
produced 23 valid advisory decisions, including four unsupported choices on old cases.
The matched-candidate gate withheld four justified outputs; explicit source rederivation
matched all twelve condition labels, independently of model prose. Repeat policy outputs
are not additional independent checks. The fresh cases had 17 valid correct advisory
responses and one parsing failure. This is conformance, not efficacy or authenticity.

All 201 evidence-context tests passed. All three providers labelled before execution;
result review had one full-packet responder and two responders to a focused compact
retry, insufficient for three-provider result consensus. The guide explains all
limitations and the intentionally identical-source omission control.

## Stage 12 commands

```sh
uv run --group dev pytest experiments/evidence_context/tests/test_retrieval_matrix.py -q
uv run python -m experiments.evidence_context.retrieval_matrix.report \
  --directory experiments/evidence_context/.private/stage-12/run \
  --output /tmp/stage-12-replay.html
open /tmp/stage-12-replay.html
```

Checkpoint `27e6900` preserves a four-question real development pilot, 32 gateway
answers and the unchanged prompt. Under pre-retrieval coordinator labels all four
arms covered Q1 2/3, Q2 3/3, Q3 0/4 facts. Reviewer-label sensitivity is retained.
All eight Q4 answers abstained. Schema compliance did not stop prose from promoting
plans into results. No held-out efficacy or retriever superiority is established.
Three providers labelled before retrieval; full result review returned only Qwen;
a bounded focused retry also returned only Qwen. See the detailed council arbitration.

The replay requires the owner's ignored private snapshot, which is deliberately not
in a public Git clone. Synthetic tests run without that snapshot or provider calls.
The private archive is alongside the learning checkout; Git does not back it up.

## Stage 13 commands

```sh
uv run --with ladybug==0.20.2 python -m experiments.evidence_context.storage_matrix.benchmark \
  --corpus experiments/evidence_context/storage_matrix/demo-corpus.json \
  --output /tmp/stage-13-demo
uv run python -m experiments.evidence_context.storage_matrix.query_diagnostic \
  --directory /tmp/stage-13-demo
uv run --with ladybug==0.20.2 --group dev pytest experiments/evidence_context/tests/test_storage_matrix.py -q
```

Checkpoint `6fff879` preserves the full SQLite/Ladybug/mixed benchmark and
separate post-hoc SQL diagnostic. The committed fixture is tiny and synthetic; the
actual measurement used 1,019 real nodes and ten disjoint copies. All 240 sampled
query conditions returned identical rows across engines; 3,600 warm query timings
were collected. A SQLite plan change reduced replicated two-hop median from 0.494ms
to 0.019ms in a separate paired diagnostic. It is not substituted into the frozen
engine race. No migration is justified. Grok and Qwen returned full storage reviews;
Fable failed. No three-provider result consensus is claimed.

All 206 evidence-context tests passed, including prior stages and new boundary/equality
checks. The private replay passed browser checks for 32 entries, Q3 filtering and
expansion. Both new stages passed the commit hooks. Source DB and production config
were not modified by these experiments; graph stores are disposable snapshots.

## Stage 14 commands

```sh
uv run python -m experiments.evidence_context.evidence_selection.viewer \
  --directory experiments/evidence_context/.private/stage-14/run \
  --output /tmp/stage-14-walkthrough.html
open /tmp/stage-14-walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_evidence_selection.py -q
```

Checkpoint `ec8bbc1` preserves 24 fresh answer calls: four development questions,
original/reviewed/reviewed-plus-nearby conditions, two repeats each. The answering
prompt/model remained fixed. Q3's reviewed conditions supplied all four required
reported-result facts and recovered them in the answers; interpretation still failed.
Clean packs overstated validation, while filled packs promoted a correction in progress
to completion. These are oracle controls, not a deployed automatic retriever. Actual
context lengths differ under one shared ceiling; order/density remain confounds.

Three providers returned design reviews. The initial twelve-answer review had two
responders whose blanket criticisms included demonstrable misreadings. A focused
three-answer audit returned all four providers; Fable and Grok correctly distinguished
qualified decisions, validation overclaims and completion overclaims. Other disagreements
and response-contract defects are retained. This is not general reviewer calibration
or full-trial consensus. No answer was regenerated or automatically accepted.

All 212 evidence-context tests passed. Browser checks confirmed 24 replay entries,
six filtered Q3 drafts, expansion and no page errors. Commit checks passed. Private
transcripts/outputs remain in the ignored .private archive alongside the learning tree;
a Git clone deliberately does not contain them. The Stage8 exercise remains unchanged.

## Stage 15 commands

```sh
uv run python -m experiments.evidence_context.assertion_gate.runner --output /tmp/evidence-stage-15
uv run python -m experiments.evidence_context.assertion_gate.viewer \
  --directory /tmp/evidence-stage-15 --output /tmp/evidence-stage-15/walkthrough.html
open /tmp/evidence-stage-15/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_assertion_gate.py -q
```

Checkpoint `4914967` preserves the independently runnable synthetic contract demo.
Default execution is offline. An explicit `--live` runs at most 32 gateway calls;
the saved actual trial replaces one synthetic case with the private historical anchor.
The guide provides a separate command for that private replay.

All 32 actual responses parsed. Expected released ID sets were raw 13/16 and annotated
16/16, but this is conditional conformance, not extraction accuracy: annotated inputs
reveal labels, and two raw cases have identical text but different hidden provenance.
Three raw basis mismatches withheld claims: one promoted a report to observation;
two conservatively reported an observation whose origin was absent from the input.
Code-owned prose retained attribution even where advisory drafts said verified.

Eighteen ordinary controls matched; two source-hash-preserving annotation forgeries
were accepted and remain explicit semantic trust gaps. State-only rendering also
omits outcome details and useful abstention explanations. All 232 experiment tests
passed. Browser checks covered actual and offline replays, filtering, expansion and
mobile layout. Commit hooks passed; source/prompt/bundle hashes remained frozen.

Design review had three usable providers; full result review had two. A focused
five-draft retry had Fable, Qwen and Mistral, all recommending source-backed annotation;
Grok timed out. This is not full-trial three-provider consensus. Reviewer mistakes,
original replies and the distinction between integrity and semantic correctness are
preserved in the council decision. No production DB/configuration changed.

## Stage 16 commands

```sh
uv run python -m experiments.evidence_context.source_annotations.runner --output /tmp/evidence-stage-16
open /tmp/evidence-stage-16/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_source_annotations.py -q
```

Checkpoint `6c736c5` preserves the source-origin recorder, annotation trial and replay.
Default execution runs six disposable local fixture processes and registers four
narrative fixtures; it makes no gateway calls. Explicit `--live` permits forty calls.
The guide gives a separate private actual-answer replay command.

All forty model responses parsed. Origin agreement under information-available
expectations was text 2/20 and capture 14/20; this is fixture contract conformance,
not human-gold accuracy. Six capture responses still assigned observed to missing,
rejected or narrative origins. Both spoofed-report repeats overrode an actual
conversation_message receipt. The predeclared promotion criterion failed.

Source-aware release retained 8/10 capture-arm justified instances with no inapplicable
live release. The text arm retained 2/10 through unsupported inferences that happened
to match the hidden receipts; do not count those as good model reasoning. Integrity-only
controls accepted six incorrect annotations; adding source checks reduced that to two.
Wrong narrative state and target still passed with genuine quotes and valid hashes.

All 247 evidence-context tests passed. Browser checks covered forty actual cards, four
filtered spoof cards, ten offline cards, fourteen controls and mobile rendering. Commit
hooks passed; trial sources, prompt and inputs remained frozen. Earlier stages, installed
configuration, production DB and saved exercise are unchanged.

All four providers reviewed design. Full result review returned Qwen/Mistral, whose
promotion recommendations contradicted the failed criterion and were rejected. A
six-example focused audit returned all four; Fable/Grok correctly distinguished the
violations from honest report/failed-process cases and favored code-owned provenance.
Reviewer mistakes remain recorded. This is not four-provider full-trial consensus.

## Stage 17 commands

```sh
uv run python -m experiments.evidence_context.provenance_ownership.runner --output /tmp/evidence-stage-17
open /tmp/evidence-stage-17/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_provenance_ownership.py packages/agent-session-tools/tests/test_context_provenance.py -q
```

Checkpoint `106b65a` preserves this stage. The source-owned adapter replays forty
saved Stage16 proposals without new model calls.
Eligible coverage becomes capture 10/10 (previously 8/10) and text 10/10 (previously 2/10),
with no incorrect final fields among those releases. Both conditions now receive trusted
metadata in code; this is not a new model-quality comparison. Eight controls preserve
two wrong narrative releases through the legacy renderer. Eight fresh synthetic cases
expose captured facts separately from unverified interpretations.

All four council providers reviewed production boundaries and the fresh cases before
execution. Their mistakes and useful exit-status presentation feedback are documented.
The combined experiment and new production-contract check ran 264 passing tests, with
one optional dependency test skipped. Browser checks covered forty cards, eight controls,
eight fresh cases, filtering and mobile layout. See
[provenance_ownership/GUIDE.md](provenance_ownership/GUIDE.md) for the runnable lesson.

## Stage 18 commands

```sh
uv run python -m experiments.evidence_context.canonical_sources.runner --output /tmp/evidence-stage-18
open /tmp/evidence-stage-18/walkthrough.html
uv run --group dev pytest packages/agent-session-tools/tests/test_context_store.py experiments/evidence_context/tests/test_canonical_sources.py -q
```

Checkpoint `3502407` preserves this stage. This offline lesson uses the actual
package's new canonical SQLite schema/storage
on synthetic fixtures. It demonstrates immutable source versions, exact Unicode
citations, explicit scope, cross-harness proposed correction links and reclassification.
No installed capture/sync, semantic arbitration or complete forgetting is claimed.

The package regression passed 1,156 tests. Broader testing uncovered and fixed compaction
of FTS shadow tables, then separately reproduced and fixed missing live WAL evidence.
Migration failure/retry, outer-transaction rollback and newer-schema refusal are tested.
The eleven-section walkthrough passed expansion/mobile/error checks. See
[canonical_sources/GUIDE.md](canonical_sources/GUIDE.md) for the database reasoning and
[canonical_sources/COUNCIL-DECISION.md](canonical_sources/COUNCIL-DECISION.md) for the
limited two-provider implementation coverage and rejected factual review allegations.

## Stage 19 commands

```sh
uv run python -m experiments.evidence_context.scope_boundary.runner --output /tmp/evidence-stage-19
open /tmp/evidence-stage-19/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_scope.py packages/agent-session-tools/tests/test_context_public_scope.py packages/agent-session-tools/tests/test_context_policy_cli.py experiments/evidence_context/tests/test_scope_boundary.py -q
```

Checkpoint `3aa1b8a` preserves this stage. Stage19 connects explicit scope configuration to existing core CLI/MCP, FTS,
vector candidate reads, direct/prefix lookup, stats and attached history. The
offline lesson runs eight actual CLI subprocesses on synthetic sources; a separate
test exercises MCP stdio. Config drift blocks reads until audited apply. Policy
preview leaves an older source database unchanged. No owner settings are changed.

The guide explains assignment precedence, absent projects, old-schema inspection,
and why changing engines would not fix a missing boundary. Read transactions pin
policy and source rows together. Browser checks confirmed eight sections, actual
expansion, a visible personal result and mobile fit. A missing favicon was corrected.

Fable, Qwen and Mistral supplied usable focused reviews; Grok returned no text.
The review found a contract mismatch and a misleading empty-result path, both now
covered by regression tests. It did not review all caller code or approve release.
See [scope_boundary/GUIDE.md](scope_boundary/GUIDE.md) and
[scope_boundary/COUNCIL-DECISION.md](scope_boundary/COUNCIL-DECISION.md).
The package regression passed 1,190 tests; the experiment suite passed 252 with one
optional dependency skip. The independently runnable Stage19 check passed 35 tests.
Workspace pyright and lint passed. StudyLoop-specific reads, native capture, sync
and managed deletion remain required.

## Stage 20 commands

```sh
uv run python -m experiments.evidence_context.consumer_scope.runner --output /tmp/evidence-stage-20
open /tmp/evidence-stage-20/walkthrough.html
uv run pytest packages/studyloop/tests/test_context_consumer_scope.py experiments/evidence_context/tests/test_consumer_scope.py -q
```

Checkpoint `36189ff` preserves this stage. The independently runnable check passes
eleven tests, including actual MCP stdio
and a subprocess lesson. A newer work conversation does not replace personal
resume context or enter the extractor. Unowned merged learning fields are withheld
with an explanation, and classified writes into the old aggregate are refused
before provider invocation. Dry-run explicitly still invokes the selected model.

Final regression: 3,770 StudyLoop tests passed, four skipped and 704 deliberately
deselected; 1,190 session-tools tests passed; 253 experiment tests passed with one
optional dependency skip. Workspace pyright and lint pass. The browser check
verified eight expandable results, the personal preview, missing-lineage status
and mobile fit. These are workspace checks, not installed release acceptance.

Three providers reviewed the increment; Grok timed out. Fable identified the
unscoped write path and ambiguous invisible-ID handling, both corrected with tests.
All three favored source-linked observations plus scoped, rebuildable summaries as
the next design direction. That ownership implementation remains future work.
See [consumer_scope/GUIDE.md](consumer_scope/GUIDE.md) and
[consumer_scope/COUNCIL-DECISION.md](consumer_scope/COUNCIL-DECISION.md).

The full regression also drove test-configuration isolation fixes and found two
existing hook-installer file-read races. Secrets tests now remove ambient key
fallbacks; provider credentials were removed from subsequent broad test processes.
No secrets appear in the learning guide or committed artifacts.

## Stage 21 commands

```sh
uv run python -m experiments.evidence_context.learning_observations.runner --output /tmp/evidence-stage-21
open /tmp/evidence-stage-21/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_observations.py packages/studyloop/tests/test_context_consumer_scope.py experiments/evidence_context/tests/test_learning_observations.py -q
```

Checkpoint `918d18f` adds immutable source-linked observations, explicit manual
ownership, correction history and scoped StudyLoop progress projections. Eight
expandable views show separation, disagreement, contribution removal, correction
and reclassification. The ordered input manifest proves what the adapter supplied;
it does not establish claim-specific support or semantic correctness.

Validation: 3,778 StudyLoop tests passed, four skipped and 704 deliberately
excluded; 1,201 session-tools tests passed; 254 experiment tests passed with one
optional dependency skip. The final transaction/metadata changes passed 30 focused
checks. Final commit hooks passed lint, types, security checks and secrets scanning.
Browser inspection confirmed eight sections, actual conflict expansion, viewport
fit and no browser errors. These are workspace checks, not release acceptance.

Both bounded council rounds returned two usable provider buckets. Fable returned
invalid responses; Grok timed out in the first round. The guide records accepted
concerns and rejected recommendations with code/test evidence. The review is
explicitly limited, not three-provider agreement.
See [learning_observations/GUIDE.md](learning_observations/GUIDE.md) and
[learning_observations/COUNCIL-DECISION.md](learning_observations/COUNCIL-DECISION.md).

Stage20 remains exactly reproducible at `36189ff`. On newer code its runner detects
that source-linked writes are available. Its earlier explanation of note
concatenation is corrected in the current guide: the old writer retained notes
when a newer update omitted them.

## Stage 22 commands

```sh
uv run python -m experiments.evidence_context.native_capture.runner --output /tmp/evidence-stage-22
open /tmp/evidence-stage-22/walkthrough.html
uv run session-context health --db /tmp/evidence-stage-22/sessions.db
uv run pytest packages/agent-session-tools/tests/test_native_capture.py experiments/evidence_context/tests/test_native_capture_lesson.py -q
```

Checkpoint `3acbc6f` integrates actual Codex, Claude Code, Kiro and Grok native
capture, immutable rendering links, local tombstone replay protection and durable
capture receipts. The five-view lesson is synthetic and isolated. The separate
opt-in local audit imported eight real sessions: 1,898 native records, including
872 tool results and 162 typed process exits, alongside 577 legacy messages.
These are different units; no answer-quality multiplier is claimed. Both sampled
Codex archives identified Codex Desktop. Revision and original machine stayed
unknown where their source did not establish them.

Validation: 1,237 session-tools tests, 255 experiment tests (one optional skip),
45 StudyLoop compatibility tests and 44 final native/export-CLI checks passed.
Commit hooks passed lint, formatting, secrets checks, Bandit and workspace types.
Browser checks verified all five sections, expansion, viewport fit and no errors.
Both council rounds obtained Meta/Qwen/Mistral responses; Grok timed out in the
first. The guide records accepted findings and claims rejected against source and
test evidence. This increment does not establish full archive or installed-hook
coverage, scoped replica lifecycle, semantic accuracy or production readiness.

See [native_capture/GUIDE.md](native_capture/GUIDE.md),
[native_capture/COUNCIL-DECISION.md](native_capture/COUNCIL-DECISION.md) and
[native_capture/OBSERVED-RESULTS.json](native_capture/OBSERVED-RESULTS.json).

## Production delivery direction

The user has now authorized the full implementation and StudyLoop integration while
preserving these stages. [delivery/GOAL.md](delivery/GOAL.md) records the complete shipping
requirements; [delivery/ARCHITECTURE.md](delivery/ARCHITECTURE.md) explains the decisions.
These checkpoints do not satisfy that goal. SQLite remains canonical. The internal
source/citation boundary and native capture now exist; next complete bounded public
retrieval/decisions, remaining learner ownership, scoped sync, lifecycle and
installed capture/doctor acceptance.

The earlier experiment-only checkpoints retain their original scope and limitations.
The Stage8 exercise is unchanged.
