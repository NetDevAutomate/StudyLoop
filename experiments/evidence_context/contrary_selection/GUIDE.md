# Stage24: keep a disagreement together

Stage23 showed a concrete selection problem: keyword matches could fill the
response before a linked contrary source was considered. All six real-data queries
also reached a bound, although that did not prove any actual disagreement was
omitted. This stage tests allocation policies on controlled evidence and adds the
chosen policy to the actual CLI/MCP path.

The finding is mechanical: complete evidence groups survive better when allocated
together. It is not a finding that unverified relation labels are correct, that
more relationships produce better answers, or that the product is ready to ship.
The complete [production contract](../delivery/GOAL.md) remains active.

## Run the comparison

From the worktree root, use a fresh directory:

```sh
uv run python -m experiments.evidence_context.contrary_selection.runner --output /tmp/evidence-stage-24
open /tmp/evidence-stage-24/walkthrough.html
uv run pytest packages/agent-session-tools/tests/test_context_agent_api.py experiments/evidence_context/tests/test_contrary_selection_lesson.py -q
```

The runner builds twelve fictional databases, obtains each permitted evidence pool
with a generous discovery response, then applies all three packing policies to the
same pool. It writes the measurements, each resulting context document and an
expandable HTML comparison. No owner database, harness configuration or gateway
is involved. Configuration changes are restored when the runner finishes.

The generous response must itself report no bound for these fixtures. This avoids
mistaking an already-truncated pool for the entire constructed case. The policies
are compared at identical source/byte limits with the same response schema. Their
policy-name strings have slightly different byte lengths, so final byte totals
are reported rather than assumed equal. These are policy comparisons, not exact
replays of the complete historical Stage23 implementation; its checkpoint is
preserved separately.

## The three policies

| Policy | Allocation order | Main trade-off |
|---|---|---|
| Lexical first | Keyword matches, then complete relationships | More keyword matches can exclude contrary evidence |
| 20% reserve | At most 80% of bytes/source slots for initial keyword matches, then relationships, then refill | The remaining fraction may still be too small for a complete group |
| Anchor then relations | Strongest keyword match, complete contrary/correction groups, remaining keyword matches | Preserves disagreements at the cost of some other matches |

All policies keep exact citations and reject any group whose dependencies cannot
fit. Caller-specified execution metadata gets first consideration when assessing
explicit checks. The product uses `anchor_then_relations`; the alternatives stay
as internal experimental policies and are not model-selectable tool arguments.

In networking terms, a useful path-failure explanation may need the source route,
the forwarding policy and a contrary observation from the next hop. Allocating
20% of a report to “other devices” does not ensure those related records fit.
Allocating the whole diagnostic group makes that dependency explicit.

## Measurements and what they mean

Twelve constructed cases contain fifteen proposed contrary/correction groups.
They vary source caps, byte caps, quote length, multi-source citations, several
alternatives, no relations and a generous all-fit case.

| Policy | Complete groups returned | Lexical source appearances retained | Strongest match retained |
|---|---:|---:|---:|
| Lexical first | 1 | 40 | 12/12 cases |
| 20% reserve | 7 | 34 | 12/12 cases |
| Anchor then relations | 11 | 26 | 12/12 cases |

The chosen policy retains complete groups in the byte-pressure, long-quote and
multi-source cases where the 20% reserve fails. It does not solve impossible
capacity: a group requiring four distinct sources cannot fit under a three-source
cap while preserving all dependencies. In the five-alternative case with three
source slots, only two alternatives fit alongside the anchor. The response states
that known groups were omitted rather than treating the displayed set as complete.

The case author deliberately created these pressures. The labels are fictional
unverified proposals, not independently judged semantic conflicts. There is no
random representative sample, held-out answer-quality score or human relevance
grade here. More complete groups is a useful implementation metric; it is not an
accuracy claim. The loss of fourteen lexical source appearances is a real trade-off
whose effect on answers still needs evaluation.

## Discover first, then pack

The production `collection.py` separates bounded candidate discovery from the
response budget. It can inspect a relation attached to a lexical candidate below
the initial output limit. It finds at most 100 lexical candidates, 24 root
assertions and 24 distinct proposed relationship groups. Caps remain explicit.

Both relationship endpoints and all their supporting sources must satisfy scope
and time constraints in SQL **before LIMIT**. This matters for more than privacy:
otherwise many hidden relationships could consume the visible discovery capacity.
A test adds 36 hidden proposals plus one visible relation; only the visible one
contributes to the returned count and capacity.

Exact duplicate endpoint/label proposals are collapsed before the relation cap.
The database retains every producer's record; the projection selects one stable
identity without declaring it more trustworthy. Repetition cannot increase the
number of displayed groups or crowd out a different group merely by adding
producers. Distinct assertions are not automatically treated as synonymous, so
this is structural deduplication, not a complete defence against misleading labels.

`selection.py` tries a group containing its sources, both assertions and the edge.
If any count or the whole-document byte budget fails, it rolls back that group.
Independently useful source text or an assertion can still appear without a
relationship; a displayed relationship can never have a missing endpoint or citation.

## Make uncertainty visible

The response adds `context_status` and `conflict_review` at the top level. They
distinguish retrieved context requiring interpretation, proposed conflicts needing
review, incomplete discovery and known proposed groups omitted by packing.
`semantic_conflict_absence_established` is always false. “No proposed relation
found” does not mean “no disagreement exists.”

Known/returned/omitted counts concern this permitted, bounded discovery only.
They are not a count of all relationships or semantic conflicts in the archive.
Native execution decisions still refuse a positive overall sufficiency result if
any relevant retrieval bound was reached. An exit record still cannot validate
software behaviour or authorize release.

The council correctly identified an unresolved hazard: a wrong `contradicts`
label can receive inspection priority. Priority is not endorsement, but it affects
what the agent sees. The full production design therefore still needs explicit
review lineage and treatment of disputed/rejected interpretations before StudyLoop
uses these proposals to derive advice. Merely adding more selection heuristics
would not establish their meaning.

## Actual interfaces and local data

The new wheel passed nine acceptance checks through its actual console script
and a real MCP stdio connection in an environment without StudyLoop installed.
Twenty distracting keyword matches were added; a two-source, 8KiB MCP request
still returned the complete proposed disagreement. Reclassification while the
server remained connected revoked the dependent relationship on the next request.

To repeat that installed journey, build a fresh memory wheel and install it into
an isolated environment as in [Stage23](../agent_context/GUIDE.md), then run:

```sh
uv run python -m experiments.evidence_context.agent_context.runner --python /tmp/stage23-runtime/bin/python --require-installed --pressure --output /tmp/stage24-installed
```

The optional local probe re-imported eight real archives into a disposable database.
Its six CLI queries again verified all 60 exact citations, with responses below
32KiB and approximately 0.092–0.109 seconds per invocation including Python
startup. All queries remained bounded and none of the returned records supplied
revision metadata. The run had no manually reviewed real relationships, so it
cannot measure the new relation policy's semantic benefit. These small timings
also do not validate a large relationship graph's query plan or memory ceiling.

The full session-tools suite passed 1,270 tests before the final duplicate-producer
guard. That guard and all public-interface/lesson cases then passed 35 focused
checks. The experiment suite plus focused StudyLoop compatibility checks passed
302 cases with one optional dependency skip. The final wheel was rebuilt and its
nine installed checks passed after the guard. Type/lint/security commit checks
are recorded at the checkpoint; no full-release claim follows from these counts.

## Direction from this stage

SQLite still stores the sources and typed relationships. The improvement changes
candidate collection and allocation, not the storage engine. A second database
would not decide whether a proposed label was correct or how much context to
allocate to its supporting records.

The next delivery work must finish review/decision treatment of competing
interpretations and ownership of the remaining StudyLoop learner records, then
carry those boundaries through sync, forgetting/restore and shared installation.
Large-graph performance and real answer usefulness remain acceptance work. The
[council arbitration](COUNCIL-DECISION.md) records both valid concerns and review
claims contradicted by the supplied code and measurements.
