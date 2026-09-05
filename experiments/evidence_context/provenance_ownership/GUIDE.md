# Stage 17: who owns the labels?

A model can quote the right source while assigning it the wrong meaning. Stage16
also showed a simpler error: a model sometimes called conversation prose a tool
observation, even when the capture receipt said `conversation_message`.

This stage separates those problems. Code derives origin and scope from verified
capture/configuration. It derives command completion and invocation identity only
from a process receipt. The original model interpretation remains available for
inspection. Narrative state and target remain unverified proposals.

## Run it

From the learning checkout:

```sh
uv run python -m experiments.evidence_context.provenance_ownership.runner --output /tmp/evidence-stage-17
open /tmp/evidence-stage-17/walkthrough.html
uv run --group dev pytest experiments/evidence_context/tests/test_provenance_ownership.py packages/agent-session-tools/tests/test_context_provenance.py -q
```

Choose a new output directory each time. Default mode runs the previous stage's six
disposable fixture processes and four conversation fixtures, then compares ten
reference proposals. It makes no model calls and writes no production database.
The eight fresh cases are constructed envelopes, not new executions.

The owner's actual forty-draft replay is separate:

```sh
uv run python -m experiments.evidence_context.provenance_ownership.runner \
  --previous experiments/evidence_context/.private/stage-16/run \
  --output /tmp/evidence-stage-17-saved-drafts
open /tmp/evidence-stage-17-saved-drafts/walkthrough.html
```

That command needs the ignored private archive alongside this learning checkout.
Git does not contain or back up that archive. It verifies the frozen input bundle
hash and preserves the old answers. No prompts or answers are regenerated.

## Read the result in three layers

1. **Source-owned fields:** captured origin, explicitly assigned scope, command
   completion, exit code and invocation target. The production helper lives in
   `agent_session_tools.context.provenance`, without importing StudyLoop.
2. **Interpretation:** the original proposed state/target and exact quote. A genuine
   quote proves neither that the proposed meaning follows nor that the claim is true.
3. **Decision applicability:** whether the evidence supports this requested decision.
   This stage still calls the legacy Stage16 renderer to expose its limitations.
   It is not a production decision endpoint.

For a network analogy, distinguish a device's recorded interface counter from a
comment in a ticket saying the link is healthy. Both belong in the investigation;
they carry different authority. A captured command exit likewise records a process
ending. Exit zero does not establish that the intended application behavior was tested.

## What changed in the measurements?

| Saved proposals | Old adapter: eligible instances released | Source-owned adapter | Wrong final fields among released instances |
|---|---:|---:|---:|
| Capture condition | 8/10 | 10/10 | 0 |
| Text-only condition | 2/10 | 10/10 | 0 |

Each condition contains twenty saved responses, ten of which are eligible for release.
The new adapter has access to capture records in both conditions. This is a deterministic
policy comparison, not a fair new model-information trial or forty new independent cases.
The text-only gain comes from supplying facts in code that its model never received.

Eight explicit controls retain **two semantic false releases**: wrong narrative state
and wrong narrative target. Origin/scope and captured execution errors are repaired;
invented missing invocation targets and post-seal corruption are withheld. We score
final fields after repair: rejecting every proposal would look safe but lose useful context.

Eight fresh cases cover negation, conditional execution, quoted receipt syntax,
body/invocation disagreement, unclassified scope, generic tool progress, failed process
with PASS text, and unknown origin. Source facts and unverified interpretations are
shown separately. This measures conformance to an explicit contract, not extraction
accuracy. The council reviewed these cases before they were executed; reviewers are
not independent human gold. See [COUNCIL-DECISION.md](COUNCIL-DECISION.md).

## Why these choices?

**Derive instead of repeatedly asking the model.** The importer already knows the
native event type; configuration already owns scope. Regenerating those fields adds
avoidable error. A native receipt is still only as trustworthy as its parser and
source binding, which require production tests.

**Retain both completion and exit status.** The council identified a presentation
risk in `completed` alone. The contract now carries `process_exit_code` independently.
A negative subprocess return code can represent signal termination. Neither zero nor
nonzero is silently converted into an application-validation result.

**Keep interpretations as proposals.** For a conversation, the code-owned execution
state is unknown even when the proposal says completed. The internal comparison
object has convenience properties for replay, but those must not become unqualified
public facts. A production reader must show captured facts and interpretations separately.

**Retain SQLite.** This experiment changes who may supply a field, not the storage
workload. A graph engine cannot decide whether a quoted sentence means a check ran.
Canonical relational evidence, assertions and relationships can express these distinctions.

## What this does not prove

No installed exporter, scope-filtered query, deletion propagation or production sync
path is exercised here. The fresh envelopes are synthetic. Wrong narrative meaning
remains unresolved by this adapter. No prompt was tuned and no semantic quality score
was earned. The Stage8 learning exercise remains saved for its dedicated session.

The full production goal and acceptance requirements live in
[../delivery/GOAL.md](../delivery/GOAL.md). The next implementation step binds this
contract to immutable stored sources, explicit project scope and exact citations,
then closes the legacy read/sync paths before any production readiness claim.
