# Stage21: where did this assessment come from?

This stage replaces new writes to StudyLoop's unowned progress aggregate with
immutable observations. The memory component owns source access and observation
history. StudyLoop derives its progress view from the observations visible in
the current scope. SQLite remains the canonical database.

The improvement is **traceability and control of individual contributions**.
It is not a measured improvement in semantic answer accuracy. A model can still
misread a correctly captured input. The result therefore says
`source_relationship: captured_input` and `unverified_interpretation`, rather
than implying the input proves the assessment.

## Run the lesson

From this worktree, choose an output directory that does not already exist:

```sh
uv run python -m experiments.evidence_context.learning_observations.runner --output /tmp/evidence-stage-21
open /tmp/evidence-stage-21/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_observations.py packages/studyloop/tests/test_context_consumer_scope.py experiments/evidence_context/tests/test_learning_observations.py -q
```

The runner creates its own database and scope configuration. Its child process
uses the actual workspace extractor pipeline, observation store and StudyLoop
projection. The injected extractor is deterministic and makes no network call.
All conversations are fictional. The owner's database and configuration are not
read or changed. `results.json` contains the observed results; the HTML explains
eight successive views. Both work and personal views are deliberately shown in
this synthetic lesson, each obtained under its own explicit request scope.

Use the checkpoint recorded in [STAGES.md](../STAGES.md) to preserve these exact
semantics. Stage20's original refusal experiment remains runnable at `36189ff`.
Its runner on newer code recognizes that v33 supports source-linked writes; a
no-result extractor now reaches the provider but creates no progress observation.
That compatibility path does not change the historical checkpoint.

## Start with the row that could not explain itself

The old `study_progress` row is keyed by topic and concept. A newer update can
replace confidence and the source pointer while retaining older notes when the
new call omits them. That last source pointer cannot establish the ownership of
every retained field. Labelling the entire row from it would manufacture lineage.

The original Stage20 guide said notes were appended. Inspection of the writer
showed `COALESCE(excluded.notes, notes)`: replacement when supplied, retention
when omitted. The current guide corrects that mechanism. The ownership problem
remains, but an accurate explanation matters as much as a plausible conclusion.

This migration preserves old rows. It does not invent work/personal ownership
for them. Explicit unclassified inspection is available only when there are no
source project assignments. New writes use observations and do not mirror bodies
back into the old unowned table.

## Three things that must remain separate

| Concern | Stored representation | What it establishes |
|---|---|---|
| Captured input | Immutable evidence versions, hashes, locator, ordered input manifest | Which captured bytes and message order the trusted adapter supplied |
| Interpretation | Immutable observation payload, producer and authority | What was reported or inferred, without certifying correctness |
| Access | Source project assignment, or explicit manual scope/project owner | Whether the current request may see the observation now |

The ordered manifest includes each evidence ID, role and null-content shape,
plus a fingerprint of the input message sequence. Identical messages in another
order can lead to another interpretation; hashing only a set of messages would
miss that distinction. Exact repeat input and output deduplicate, while a changed
input or changed assessment remains a separate observation.

Legacy database rows are not original native harness receipts. Even an assistant
message saying “all tests passed” retains `origin: unknown`. A model's confidence
label cannot turn that prose into an observed command result or a validated skill.

Whole-input linkage is deliberately weaker than claim-specific support. The next
retrieval/decision interface must distinguish “this was in the input” from “this
particular passage supports this claim” and from “a relevant check established
this claim for the requested target and revision.” This increment proves only the
first of those relationships.

Observation time means when the assessment was recorded, not necessarily when
the learner studied or demonstrated the concept. The projection exposes
`time_basis: assessment_recorded_at` and separate known source timestamps. A
backfilled assessment must not be presented as proof of learning today. Existing
review/win terminology still needs the wider temporal/applicability integration;
the `get_wins` API means recent confident reports, not measured improvement.

## Follow the eight views

1. **One personal report.** Its current summary carries an observation ID and
   evidence IDs. The report remains an unverified interpretation.
2. **A work report about the same concept.** It uses the same harness, but project
   configuration keeps its notes outside the personal view.
3. **Two personal reports disagree.** Both remain current. The projection exposes
   `reported_confidences` and `conflicting_reports`. The lower confidence guides
   cautious review scheduling; it is not an arbitration winner.
4. **One dependency is removed.** Its dependent observation is purged and the view
   is rebuilt from the remaining report. Counts and notes change together.
5. **An explicit correction.** A manual update supersedes the visible current
   heads. Earlier observations remain inspectable as history. Independent model
   reports never infer supersession just because they are newer.
6. **That correction is forgotten locally.** No old report silently becomes
   current again. An empty current view is more honest than reviving advice that
   was explicitly superseded.
7. **Historical inspection.** Retained history still exposes its authority,
   input lineage and limits. “Historical” does not mean “currently endorsed.”
8. **Source reclassification.** Moving the source changes which scope can see its
   historical observation without rewriting the observation's content.

The networking analogy is a set of route announcements and withdrawals. The
current routing table is a projection. A withdrawal should remove its contribution;
deleting a newer update should not quietly endorse an older withdrawn route.
The analogy explains lifecycle mechanics, not how semantic truth is decided.

## Why typed relationships inside SQLite?

| Option | What we gain | What we would lose or take on |
|---|---|---|
| Add scope to the old aggregate | Small migration | Still cannot attribute or remove individual contributions |
| Immutable observations plus typed dependency/revision tables | Per-source ownership, explicit history, atomic lifecycle changes | More rows, joins and binding checks; projections must be maintained carefully |
| A second graph engine immediately | Another graph traversal interface | Cross-store consistency and deletion work before showing a traversal requirement it serves better |

The selected design already represents a small graph: observation → captured
source, observation → prior observation, source → project. A relational database
can store these relationships explicitly. A graph engine might later improve
particular traversals, but this experiment provides no comparison demonstrating
that advantage. We first need correct relationships and usable evidence.

Foreign keys require each dependency to exist. Triggers prevent mutation of
recorded versions and purge observations when their evidence is removed. Read-time
bindings detect unexpected payload/reference changes. Hashes establish local
integrity, not authenticity against an attacker who controls the database file.

The summary is currently rebuilt on demand; there is no new persistent summary
cache to invalidate after a scope change. This simplifies correctness while
leaving a performance question: the internal projection reads all visible progress
observations and verifies their sources. Public context retrieval still needs
budgets, pagination and measured scaling before release. No large-corpus latency
or storage-overhead benchmark is claimed for this increment.

## Why the model call runs outside the write transaction

The pipeline has three phases:

```text
read permitted input → release read snapshot → call provider
    → BEGIN IMMEDIATE → recheck current access → save input + observations → commit
```

SQLite permits one writer at a time. Starting an immediate transaction reserves
that writer; retaining it for a network call would block unrelated exporters or
writers. Its transaction documentation also explains that an existing read
transaction continues to see its earlier snapshot. We end that snapshot before
the provider call, then start a fresh transaction for access checks and persistence.
See [SQLite transaction control](https://www.sqlite.org/lang_transaction.html) and
[SQLite isolation](https://www.sqlite.org/isolation.html).

If another process edits a source while the model runs, the stored observation
still points to the earlier bytes actually supplied. If it changes scope or marks
the session forgotten, the new write fails. A failure anywhere in the result
batch rolls back its observations and newly captured evidence together. The
pipeline refuses an already active caller transaction, preserving the caller's
uncommitted work instead of committing or rolling it back unexpectedly.

This is not one atomic transaction spanning a remote provider. Data already sent
cannot be recalled when the user later changes scope. Access is checked before
delivery and again before persistence; subsequent reads enforce the current
configured policy. A SQLite lock cannot make edits to an external configuration
file atomic with a remote request.

## Corrections and forgetting: precise limits

Local observation deletion retains identifiers, retirement links and a subject
digest. These prevent exact replay and fallback to a retired legacy aggregate.
They do not retain the deleted observation body, but should not be described as
anonymous or devoid of identifying information. Supersession references to hidden
history are withheld from returned details, with `history_incomplete` instead.

Deleting a source dependency purges all observations that used it, including a
multi-source observation. Partial notes are not kept without their full lineage.
This can remove a useful report; preserving an unattributable fragment would
violate this stage's contract.

This is **not complete session forgetting**. Reimport suppression, scoped peer
sync, backup restoration, original external transcripts and all other derived
tables remain required work. A new assessment with changed input/output is a new
identity; exact-observation tombstones alone cannot prevent all regeneration.
The production lifecycle must operate on source sessions and propagate deletion
metadata through every managed path.

## Evidence and review

The tests exercise source visibility, policy drift, immutable bindings, exact
replay, two concurrent correction heads, one/all contribution removal, manual
ownership, source reclassification, captured message order, provider-time edits,
provider-time scope/deletion changes, caller transaction preservation and atomic
batch rollback. The lesson uses the real workspace components in a subprocess.

Downstream progress readers now use this projection: resume, wins, reviews,
struggle recommendations, focus suggestions, mastery confidence and struggle
content selection. Unowned study-session statistics remain withheld for classified
requests. Teach-back and other learner-state ownership still require integration;
this does not certify every StudyLoop data path.

The full regression revealed older fixture assumptions: subprocess fixtures needed
an explicit scope; migrated web fixtures needed foreign keys enabled and assertions
against the new persisted observations/projection. Product defaults were not
weakened to satisfy those tests. Final counts and checkpoint are recorded in the
stage index after verification.

See [council arbitration](COUNCIL-DECISION.md) for what the reviewers said, which
claims were supported by the code and tests, and why recommendations were accepted
or rejected. A review is evidence to evaluate, not a vote that overrides the code.

The saved Stage8 revision exercise remains unchanged. It can be revisited in the
dedicated learning session without rushing this delivery run.
