# Stage29: where a graph label gets its meaning

The product now projects concept relationships from owned contributions. This stage
keeps SQLite and tests a data-model change: preserve where an edge came from,
which scope owns it, and what the edge is allowed to imply. It remains an increment
of the full [production contract](../delivery/GOAL.md).

## The concrete defect

The old bridge migration copied a label into a globally unique concept row and
mapped `effective` to confidence 1.0, or `validated` to 0.7. The dependency reader
then read global edges. An analogy could enter the weak-prerequisite recommendation
path even though nobody had established a prerequisite relationship.

In networking terms, an interface description saying “backup link” is useful
context; it does not establish the forwarding path. We need the source record and
the meaning of its label before acting on it.

## The representation we chose

| Choice | Benefit | Cost | Decision |
|---|---|---|---|
| Extend old global graph tables | Familiar SQL joins and indexes | Rework global uniqueness, old IDs and parent foreign keys without inventing ownership | Preserve old data, do not use for new classified reports |
| Add a second scoped graph schema | Explicit graph identities and traversal | More copied state, sync and deletion machinery before traversal value is established | Defer |
| Owned observations plus live bridge projection | Existing provenance, retirement and scope checks; no stale copied bridge edge | Recompute projections; large graph cost needs measurement | Implement this increment |

Explicit concept/dependency reports use the independent memory package's immutable
observations. Their owner is the configured project or explicit request scope;
updates supersede only the same adapter, subject and owner. A lower revised weight
can replace an earlier higher weight: `MAX(confidence)` is no longer an accidental
rule that prevents correction. Independent projects retain separate contributions.

Bridge edges are read directly from the currently visible `knowledge_bridges` row.
The result includes its record/owner IDs, a hash of the selected snapshot, the
structural mapping, the original quality report and explicit `not_established`
semantic validation. This hash binds the returned snapshot; it is not an immutable
historical archive of every past bridge version. The finite response guard from
Stage28 checks scope/revocation before delivery.

Deleting a bridge therefore removes its edge on the next read. Deleting one of two
same-label bridges preserves the independent contribution. A source-owned bridge
also follows its native parent's scope and local forgetting cascade. Complete
cross-machine deletion/restore remains a separate production requirement.

## What the agent may infer

An analogy is useful explanatory context. It cannot establish a prerequisite.
The weak-link recommendation path now accepts only the explicit `prerequisite` relation
type (source is prerequisite of target) and calls them reported links. Its metadata retains the observation ID,
binding hash and validation status. A report still does not prove the prerequisite
is correct. The graph's display groups labels; edge provenance retains contribution
identity and bridge domains so grouping is not an entity-resolution claim.

Old unowned concepts/dependencies remain on disk. Only the existing strict
unclassified compatibility policy can display them. A modern report or content-free
retirement marker prevents a same-subject legacy aggregate from reappearing as a
fallback after correction/forgetting.

## Boundaries deliberately still visible

A globally loaded config tag or arbitrary markdown heading has no file ownership
contract yet. Classified config imports fail before loading topics. Modern graph
reads do not silently import markdown/old global edges; the old minimal-schema
compatibility importer remains restricted to unclassified inspection. File capture,
lineage and invalidation are still required before this becomes a production-complete
file integration. Unknown does not mean personal.

The existing alias/message-concept tables remain unchanged and unclassified through
the existing legacy boundary. Static source search found no active StudyLoop readers
other than the paths addressed here, but sync/tiering still know these tables. This
is not evidence that every external consumer or transport has been audited.

## Run the lesson

Use the pinned checkpoint in [STAGES.md](../STAGES.md) for historical behavior.
Choose fresh output paths:

```sh
uv run python -m experiments.evidence_context.concept_context.runner --output /tmp/stage29-demo
open /tmp/stage29-demo/walkthrough.html
uv run pytest packages/studyloop/tests/test_graph_context_scope.py experiments/evidence_context/tests/test_concept_context_lesson.py -q
```

For installed-package verification:

```sh
uv build --package agent-session-tools --wheel --out-dir /tmp/stage29-wheels
uv build --package studyloop --wheel --out-dir /tmp/stage29-wheels
uv venv /tmp/stage29-runtime --python 3.13
uv pip install --python /tmp/stage29-runtime/bin/python /tmp/stage29-wheels/agent_session_tools-0.1.0-py3-none-any.whl '/tmp/stage29-wheels/studyloop-0.2.1-py3-none-any.whl[web]'
uv run python -m experiments.evidence_context.concept_context.runner --python /tmp/stage29-runtime/bin/python --require-installed --output /tmp/stage29-installed
```

The lesson uses fictional data and actual HTTP route modules via ASGI transport;
it does not exercise full web lifespan/startup. See OBSERVED-RESULTS.json for the
measured run and COUNCIL-DECISION.md for arbitration. This stage does not compare
storage engines or claim semantic answer-quality improvement from its mechanical
checks. The measurable gain is stronger lineage and more faithful decision roles.

## Observed scale and its design implication

The installed helper returned 37–38 complete short bridge contributions under 32 KiB.
At 100, 1,000 and 5,000 visible bridges, with the same number excluded by scope, five
sequential runs measured median 17.647,34.158and110.561 ms respectively. This is a
small synthetic diagnostic. It includes projection and packing, excludes HTTP/MCP
transport/startup, and does not compare engines. The output cap is working; the
query still examines all permitted contributions. Selective retrieval and query
work budgets are the next performance question.

```sh
/tmp/stage29-runtime/bin/python -I experiments/evidence_context/concept_context/benchmark.py --output /tmp/stage29-scale
```

The final installed walkthrough passed10 checks. Full StudyLoop passed3,816 tests
before the final direction-rule and reported-legend refinements; final168 focused tests and workspace
types passed. Memory/experiment regression passed1,584 tests with one optional skip.
See the observed JSON for timings, exact scope and limitations.

The graph legend also describes mastery colours as reported categories. A stored
“mastered” label alone cannot establish that a full review occurred. The agent
response includes this assessment limitation explicitly.
