# Stage 12 prospective real-data development pilot

Freeze before retrieval: corpus selection, questions, review pools, structural graph,
chunking, model/tokenizer, prompt and settings. Real conversation bodies remain in
private artifacts. User explicitly authorized selected excerpts through the configured
gateway. Production sessions.db is opened read-only in one read transaction.

Scope: an explicit allowlist of personal StudyLoop/MailGraph root paths, Codex sessions
with at least ten user/assistant messages before 2026-08-21. Exclude exact previous demo
sessions, instruction envelopes, short passages and potential sensitive chunks. This
is not an all-harness/cross-machine efficacy test. A MailGraph continuation is related
to an earlier development lineage, so label the entire pilot development, not held-out.

Three questions are retrospective derivatives of actual historical requests; one is a
constructed unanswerable control. Reviewer pools are chosen from fixed episode ranges
before retrieval, not from any arm's top results. Model reviewers mark required groups,
alternatives, limitations and uncertainty independently of arm outputs. Pool labels are
incomplete for corpus-wide relevance; do not report global precision or recall. Preserve
reviewer disagreement and distinguish analyst arbitration from independent human truth.

Use all-mpnet-base-v2 locally, 280 tokenizer-token chunks stepped by 240 with exact
original-message offsets. All passages are conversation reports, not authenticated test
artifacts. Graph edges are deterministic sequence and shared-file-reference links,
created before labels/queries; they are structural relationships, not inferred truth.

Four arms share corpus, project/time eligibility, candidate text and formatting:
keyword SQLite FTS5/BM25; local embedding cosine; keyword plus structural expansion;
reciprocal-rank fusion of keyword, semantic and structural candidates (constant 60).
Use top three keyword seeds, one-hop expansion, at most six passages and 1400 context
tokens using the answering model family's tokenizer. Same ceiling, not padding to equal
length. No prompt optimization or settings changes after retrieval output inspection.

Answer model: qwen3-coder through gateway, same prompt for all arms, max1500 output
tokens, temperature zero. Two calls per question/arm,32 calls maximum, randomized fixed
order, no application retries. Parse strict JSON first; predeclared single complete
Markdown JSON fence removal allowed separately. Record invalid responses and raw text.
Blind arm names for result review; model judges are fallible and do not measure learner
understanding. Report quote origin/locatability separately from semantic support.

Primary development outcomes: coverage of reviewed evidence groups (with alternatives),
unsupported validation claims, answering correctness against the reviewed source pool,
appropriate insufficient-evidence response, and explanation weaknesses. Report per-case
wins/ties/losses; context tokens, embedding cost and answer cost alongside quality.
Review-pool incompleteness and duplicate/related histories limit generalization.

Storage experiment is separate: freeze identical nodes, edges and query roots; compare
SQLite, LadybugDB and SQLite+Ladybug edge projection on output equality, repeated warm
lookup/traversal latency, build/open time and size. A quality difference from changing
engines would be a correctness discrepancy, not evidence of more intelligent storage.
Do not infer throughput, cold-cache, concurrent sync or production-scale suitability
from small single-process benchmarks. Never mix engine latency with model-answer time.

Pre-retrieval label amendment: remove the initial reviewer-brief three-group cap.
Q3 needs four separate facets; partial facts must not be mislabeled as alternatives.
The private labels ledger retains the three reviewers and coordinator arbitration.
