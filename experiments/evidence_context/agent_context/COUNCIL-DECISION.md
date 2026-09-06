# Stage23 council arbitration

Two rounds completed through the configured LiteLLM gateway on 2026-09-06. Each
received three successful provider buckets: Meta (`llama4-maverick`), Qwen
(`qwen3-coder`) and Mistral (`mistral-large-3`). Each round used one common brief
and response schema, bounded concurrency and timeouts. Source code, fixture
results and body-free local aggregates were supplied; no real transcript bodies
were included. Private requests and responses remain outside the tracked tree.

These are independent model reviews, not human usefulness grades or release
approval. The full P01–P15 contract remains active.

## First review: interface and authority

Meta conditionally accepted the foundation; Qwen requested boundary/completeness
clarification; Mistral rejected production shipping without interpretation,
health, forgetting and actual StudyLoop startup evidence.

Accepted concerns:

- Stored proposed relationships can be mistaken for verified facts. The reference
  now explains exact binding versus entailment, `corrects` versus an accepted
  correction, and captured metadata versus agent-provided interpretation fields.
- `not_established` health must not look like a healthy signal. The interface
  guide defines it and distinguishes visible context health from operator receipts.
- Installed interfaces needed proof beyond calling Python functions. The built
  wheel ran in a separate environment without StudyLoop, using its actual console
  script and MCP over stdio; all eight journey checks passed.
- The production contract still needs complete ownership, sync/forget/restore,
  installer/doctor/skills and StudyLoop startup. Those requirements were retained.

Claims checked against implementation rather than accepted by vote:

- Source/citation checks and endpoint scope checks were already present and tested.
  Repeating a request for them does not establish a missing check.
- Search already reported byte/source/candidate/relationship limits. The unresolved
  question is how conspicuous and useful that signal is, not whether it exists.
- A recency rule cannot safely resolve contradictory advice or execution outcomes.
  No such rule was added.
- A matching process receipt and semantic validation are genuinely different
  claims. Their distinction remains explicit, even if wording needs user testing.

## Results review: retrieval under pressure

The second brief included the 1,264-test package result, 27 public-interface cases,
installed CLI/MCP results and six local queries. All 60 returned source citations
were checked against full stored hashes and offsets. Every query hit a bound;
none of the selected sources supplied a native revision. The brief also disclosed
the unmeasured semantic quality and the current lexical-first packing limitation.

Meta recommended a contrary-evidence reserve or clearer documentation. Qwen
supported integration conditional on clearer sufficiency signals and handling
contrary evidence under budget pressure. Mistral called for a minimum 20% reserve
and stronger conflict indicators before release.

Decision:

1. Preserve this increment as a runnable checkpoint with its measured limits.
   It is not production release acceptance.
2. Test contrary-evidence selection under constrained budgets before making a
   fixed allocation policy. A lexical-first pack can omit a linked contrary source
   even when replacing a lower-priority lexical result would allow both endpoints.
3. Make incomplete/conflict coverage conspicuous in the next interface increment.
   A guarantee to show every relevant semantic conflict is not supportable; bounded
   discovery and explicit unknowns must remain part of the contract.
4. Keep the full delivery requirements active while doing this targeted retrieval
   improvement. Better selection does not finish sync, forgetting or integration.

The proposed 20% allocation has no measurement behind it in the reviews. It is a
candidate experiment, not a proven requirement. The real sample's bounds also do
not measure the frequency of omitted contradictions: its stored relationships
were not independently labelled. Mistral described the maximum of 40 sources as
having been hit by all queries; the actual probe requested 12 and often reached
the byte bound before 12. Its cited count of 24 tests was stale; the final suite
contained 27. Neither discrepancy changes the concrete selection concern.

No reviewer supplied user-interpretation evidence or semantic entailment grades.
The observed source grounding is stronger than before; improved answer quality
remains a separate measurement.
