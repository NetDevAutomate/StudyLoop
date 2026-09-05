# Stage 10 results — Metadata helped one case and exposed another failure

The completed pilot does not establish a general increase in answer value. Original
extracted metadata made the missing revision explicit and improved choice matches on
that one case in both repeats. Checked metadata recovered that case too, but introduced
unsupported recommendations for a report. Ambiguous revisions defeated every condition.

## First finding: formatting contaminated the original metric

All 64 gateway calls returned text with finish reason `stop`. All eight extractions
parsed. Only 9/56 answer drafts parsed as strict JSON; the other 47 were complete
Markdown-fenced JSON. They were not transport failures or truncated answers.

The original frozen scorer counted these parser failures as nonmatching choices.
Its raw condition therefore showed 0/16 matches. That is not evidence of 16 wrong
reasoning decisions. The original responses and scores remain unchanged in
[observations/results.json](observations/results.json).

After observing this defect, we added a separately labelled diagnostic. It removes
only a complete JSON code fence, then uses the original schema and choice checks.
It does not rewrite strings, repair malformed JSON, extract JSON from surrounding
prose, or call a model. All 47 fenced answers became schema-valid. This is a **post-hoc
formatting diagnostic**, not the preregistered score or a new model run.

| Condition | Answer drafts | Strict JSON parsed | Diagnostic choice matches | Unsupported choices | All quotes locatable |
|---|---:|---:|---:|---:|---:|
| Source only | 16 | 0 | 12 | 4 | 16 |
| Original extraction | 16 | 7 | 14 | 2 | 14 |
| Faulty candidate, four cases only | 8 | 1 | 4 | 4 | 7 |
| Checked candidate | 16 | 1 | 12 | 4 | 15 |

There were no missed supported choices after diagnostic parsing. These are category
matches against development labels, not validated-answer or learner-value scores.
The always-none baseline matches 8/16 on the eight-case/two-repeat set. Following
the extracted winner without scope checks also matches 8/16; following the faulty
candidate winner on its four-case subset matches 0/8. These simple baselines explain
why selecting a winner is insufficient.

## Which decisions changed?

Both repeats gave the same recommendation within every case/condition. They are
repeated calls on eight sources, not sixteen independent scenarios.

| Case | Expected | Source only | Extracted | Faulty candidate | Checked |
|---|---|---|---|---|---|
| Clean matching log | B | B | B | — | B |
| Missing revision | none | B | none | B | none |
| Wrong revision | none | none | none | none | none |
| Wrong winner outside observed block | A | A | A | A | A |
| Duplicate revision | none | B | B | B | B |
| Report only | none | none | none | — | B |
| Noisy matching A | A | A | A | — | A |
| Noisy matching B | B | B | B | — | B |

On the same four fault cases, diagnostic matches were raw 4/8, extracted 6/8,
faulty candidate 4/8 and checked 6/8. Comparing candidate 4/8 to checked 12/16 would
confound different case sets. The useful comparison is candidate 4/8 versus checked
6/8: the missing-revision case accounts for the entire observed recovery.

There was no observed advantage on the two longer noisy sources. All conditions
already answered them correctly. The fixtures may be too easy to expose search benefit.

## What the evidence supports

**Extraction:** all 40 original field/value/quote pairs matched the narrow reference
grammar. This includes null for missing/ambiguous revision. That is a successful
synthetic extraction observation, not evidence of authentic tests or arbitrary prose
understanding. The four controlled corruptions were added after extraction.

**Source checking:** the verifier rejected all four seeded field faults, including
a quote outside the observed block and an exact quote hiding duplicate revisions.
Yet rejecting metadata did not reliably change the model's answer. The agent still
reads the original text and may select a convenient conflicting declaration.

**Applicability:** the wrong-revision case remained an abstention in every arm,
even with faulty metadata. This is a useful control, not an observed metadata gain.

**Evidence kind:** in the checked report case the model recommended B, then put
checking whether a report qualifies as an artifact into `next_check`. That reverses
the dependency: a required prerequisite was deferred until after recommendation.
A false sense of authority from checked metadata is a plausible explanation, but
this experiment does not isolate the effect of the label from field/reason rendering.

**Citations:** two correct extracted abstentions cited target revision `r2` as if it
were in the source, which actually contained `r1`. A checked missing-revision answer
also cited the absent revision. This motivates explicit source-versus-target locators.
All duplicate-revision answers had locatable quotes despite unsupported choices.
No automatic metric here establishes explanation entailment or teaching value.

## Cost and limits

The 64 experiment calls cost a gateway-reported **$0.03279036**, with no missing cost
fields; council reviews are additional. Recorded usage was 54,678 prompt tokens and
11,534 completion tokens, with zero reported cached tokens. These provider counters
do not independently audit gateway caching. One model, eight synthetic development cases,
two repeats, unequal context lengths, and no independently authored pre-result labels
cannot support a general effectiveness or efficiency claim. Repeats do not prove
independence; cache behavior was not separately verified.

The frozen original runner is preserved as observations/executed-runner.txt. The
current runner differs only by formatting. Private original artifacts retain hashes;
the readable frozen copy omits fingerprint values. No source text or model answer was
rewritten. Source authenticity, cross-session retrieval and real learner understanding
remain outside this pilot.

## Replay without provider calls

```sh
uv run python -m experiments.evidence_context.metadata_value.normalization_audit \
  --input experiments/evidence_context/metadata_value/observations \
  --output /tmp/stage-10-answer-audit.json
open /tmp/stage-10-answer-audit.html
```

Choose a fresh output filename. The saved [answer replay](observations/answer-replay.html)
contains every diagnostic answer, explanation, citation, strict status and check.
The [source walkthrough](observations/walkthrough.html) shows the log-to-field checks.
Read them together: a matched decision category does not certify its explanation.
