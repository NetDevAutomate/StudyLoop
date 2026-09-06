# Stage25: who assessed this claim, and why?

Stage24 made proposed contrary evidence harder to crowd out. That solved an
inspection problem. It did not tell us whether a `contradicts` label accurately
described its sources. Stage25 adds source-bound review history and tests what an
agent can inspect before accepting an interpretation.

This is an implementation increment inside the complete production delivery goal.
It is not release acceptance or a claim that general semantic arbitration is solved.
The [full shipping contract](../delivery/GOAL.md) remains authoritative.

## Run the lesson

From the repository root at this stage's checkpoint:

```sh
uv run python -m experiments.evidence_context.interpretation_reviews.runner --output /tmp/evidence-stage-25
open /tmp/evidence-stage-25/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_reviews.py experiments/evidence_context/tests/test_interpretation_reviews_lesson.py -q
```

Use a new output directory for each run. No gateway calls are needed. The fixture
and reviews are fictional, but the process calls the real CLI and MCP over stdio.
The lesson explicitly loads the preserved Stage23 fixture helper; the checkpoint
contains both. It does not depend on the user's real database or configuration.

To exercise an independently installed memory package:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage25-dist
uv venv /tmp/stage25-runtime
uv pip install --python /tmp/stage25-runtime/bin/python /tmp/stage25-dist/agent_session_tools-0.1.0-py3-none-any.whl
uv run python -m experiments.evidence_context.interpretation_reviews.runner --python /tmp/stage25-runtime/bin/python --require-installed --output /tmp/stage25-installed
```

The probe requires the package to resolve from `site-packages`, checks the actual
console entry point, and verifies StudyLoop is absent from that runtime. The parent
lesson renderer remains in the learning repository.

## Follow the six steps

1. The source says SQLite was chosen for atomic writes. The assertion says SQLite
   was proven faster than every graph database. Its quote is exact; its conclusion
   goes beyond that evidence.
2. A fictional MCP review cites a second source saying no benchmark was run. The
   available assessment becomes unsupported. Code has recorded an interpretation,
   not independently established the semantic verdict.
3. A fictional CLI review supports the overclaim. Both assessments remain visible,
   and the result reports dispute. Neither the newest review nor the larger tally
   automatically wins.
4. The CLI explicitly revises its own review. The old body remains inspectable as
   retired. The MCP adapter cannot retire the CLI adapter's review.
5. The revised review is forgotten. A content-free retirement link remains, so the
   old favourable review does not silently become current again.
6. The second source moves from personal into work scope. Its dependent review is
   withheld on the next request to the already-running MCP server. The retired
   favourable review still stays retired.

An analogy: a packet capture and an engineer's incident assessment are different
records. The capture shows traffic; the assessment explains what it might mean.
An exact packet reference does not prove the engineer's diagnosis. If a diagnosis
uses restricted captures, its explanation inherits that restriction.

## Why this database structure?

We retain SQLite. This experiment changes what information we represent and
validate; it does not supply evidence that a different engine improves answers.

| Design choice | Why chosen | Cost or limitation |
|---|---|---|
| Immutable reviews, not one mutable `validated` flag | Keeps attribution, disagreement and explicit revision history | More rows and joins; bounded history is necessary |
| Reuse immutable observation bodies | Reuses exact source binding, retirement and purge behavior already implemented | Review kind and payload validation must stay explicit |
| A dedicated typed target-link table | Foreign keys distinguish assertion versus relationship; a hash binds the exact target version | Another schema migration and integrity path to test |
| Include all target and review sources | Prevents a permissive extra quote from hiding restricted target dependencies | Larger response groups and possible omissions |
| Adapter-owned producer and authority | Prevents the submitted review document from upgrading itself to native or human authority | Adapter labels do not identify independent people/models |
| No majority rule | Repeated correlated opinions cannot establish truth through popularity | Conflicts require further interpretation and evidence |

Schema35 adds `context_review_targets` with exactly one assertion or relationship
foreign key. Its observation foreign key cascades when the review body is removed.
Target-deletion triggers remove dependent observation bodies; existing tombstone
and retirement machinery prevents old assessments from reappearing as current.
Target links and proposed relationship versions reject updates. Review append and
target binding share a transaction; reading recomputes the target hash.

Dedicated duplicate review-payload tables would not by themselves prove independent
reasoning or semantic correctness. We chose typed links plus existing immutable
storage to avoid maintaining a second deletion/retirement implementation. The
council challenged this choice; the [arbitration record](COUNCIL-DECISION.md) explains
which concerns survived inspection.

## How the agent gets the explanation

`memory_review` records a verdict, rationale, exact citations and limitations for
one returned assertion or relationship ID. `memory_reviews` retrieves bounded
history. `memory_assess` retrieves requested claims, sources, proposed contrary
groups and current assessments together, with a conservative status and reason.
CLI equivalents are documented in the [public contract](../../../docs/context-memory.md).

The code decides whether citations bind, the target is unchanged, scope permits
every dependency, reviews disagree, and coverage is incomplete. It does not decide
semantic truth from a keyword or upgrade a model verdict into observed validation.
Even `attributed_support_available` retains `semantic_validation: not_established`.

Reviews travel with their dependencies as whole groups. A large group may displace
other context or fail to fit. Coverage then reports the bound. More metadata is
useful only when the context consumer can inspect its meaning and limitations.

All MCP clients share one adapter label; all CLI clients share another. A model
using the same adapter can revise another same-label submission. This is a local
application boundary, not authenticated multi-user review. Identity and independent
reasoning are different properties; neither is inferred from the label.

`as_of` filters later reviews and known later native times. It never revives a
retired head, even if the retirement happened after the requested date. This
deliberately prioritizes non-reactivation over full historical reconstruction.

## The frozen model pilot

The separate opt-in run made exactly three calls through the configured local
gateway, one each to Meta Llama4 Maverick, Qwen3 Coder and Mistral Large3. Each got
the same three synthetic cases and the same [prompt](PROMPT.md). The prompt did not
include expected verdicts. It was not tuned after the run.

```sh
uv run python -m experiments.evidence_context.interpretation_reviews.live --live --output /tmp/stage25-live
uv run python -m experiments.evidence_context.interpretation_reviews.audit_transport /tmp/stage25-live
```

The first command makes up to three billable requests using the configured gateway.
The second reads saved synthetic responses only, with no gateway or database writes.

| Case | Meta | Qwen | Mistral |
|---|---|---|---|
| Attribute the SQLite choice to the earlier session | supported | supported | supported |
| Claim SQLite was proven faster than every graph DB | unsupported | unsupported | unsupported |
| Claim a passing process validates the current unknown revision | unsupported | uncertain | uncertain |
| Strict plain-JSON batch stored | **No: Markdown fence** | **Yes** | **No: Markdown fence** |

The strict end-to-end result is **one of three accepted provider batches**, yielding
three stored reviews. Two providers returned complete JSON wrapped in Markdown,
which the frozen parser rejected. No partial batch was stored.

Afterwards, an explicitly post-hoc diagnostic removed exactly one complete JSON
fence where present. All nine inspected labels were within the predeclared ranges,
and all nine citation sets matched the supplied cases. This did not change the
original database or acceptance results and did not require another model call.
It demonstrates why transport compliance and reasoning should be measured separately.

The applicability case allowed both unsupported and uncertain. Agreement with that
range does not establish calibration between them. Three deliberately simple cases
cannot estimate real-world accuracy, provider rankings, answer usefulness or human
trust. A strict parser may reduce availability; any future normalization policy must
be specified and tested separately, without hiding failed original runs.

## Observed validation and next decisions

The full session-tools suite passed 1,287 tests before four additional targeted
cases. The final review suite covers twenty cases. The experiment/selected StudyLoop
suite passed 303 tests with one optional skip before the additional pilot failure
test. The installed wheel and source journeys each passed all eight checks.
The browser verified six sections, expansion, viewport fit and no console errors.
The machine-readable [results](OBSERVED-RESULTS.json) distinguish these runs.

The council returned all three providers in both design and implementation review.
It identified real limits in independence, format reliability and usefulness
measurement; several alleged code defects were contradicted by code and targeted
tests. Reviews themselves need arbitration against evidence.

Next complete the remaining StudyLoop data ownership and scoped sync/forget/restore
paths, then shared installation/doctor/skills and actual installed StudyLoop startup.
For semantic evaluation, use harder source-grounding cases and separately measure
transport acceptance, exact bindings, entailment, applicability and answer sufficiency.
Do not keep adjusting this prompt until these nine labels look better. Saved Stage8
and DSPy learning exercises remain available for a dedicated session.
