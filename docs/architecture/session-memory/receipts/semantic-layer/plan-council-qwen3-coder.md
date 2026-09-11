<!-- verified_model: qwen3-coder -->
<!-- finish_reason: stop · 18.6s · usage: {"completion_tokens": 1257, "prompt_tokens": 6189, "total_tokens": 7446, "completion_tokens_details": {"reasoning_tokens": 0, "text_tokens": 1257}, "prompt_tokens_details": {"cached_tokens": 0, "text_tokens": 6189, "cache_write_tokens": 0, "cache_creation_tokens": 0}, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0} -->

VERDICT: APPROVE-WITH-CHANGES

## Findings

| id | severity | plan item | claim | check | proposed change |
|----|----------|-----------|-------|-------|-----------------|
| F1 | MAJOR | Stage 11 baseline metrics | "crash count on the 91 through `call_tool`" implies 42/91 currently crash | Lane A §4 shows 4/4 Stage 4 crashes reproduced from raw `AND`/`OR`/`NOT` handling; lane D §5: 5/5 real MCP queries succeeded because they lacked those words — implies *not all* Stage 4 crashes reproducible this way | Clarify "crash count" means specifically the 4 Stage 4 syntactic classes (now reproducible under call_tool), not latent crashes broadly |
| F2 | BLOCKING | R2 embedding alignment | Plan omits content hashing for staleness detection in Stage 13 (§5.3 says “DELETE”) | §2.3 states clearly `messages.content_hash` is 0/143,908 and proposes a `content_sha256` column; lane C §1: scrub/redact leaves stale vector (violates R2) unless hash checked post-scrub | Require content-hash field on message_embeddings table; add `stale` to doctor's checks based on current-content SHA vs stored hash |
| F3 | MAJOR | Stage 14 acceptance | Plan uses self-retrieval@5 for hybrid validation (§4) | Self-retrieval@5 has a theoretical ceiling <1 due to unanswerables and duplicates; §2.4: census shows 14.4% twin-duplicates render ranking part partially unwinnable | Add guardrail: self-retrieval ≥ 0.70 of computed winnable ceiling, reject global % targets like “61.08%” |
| F4 | MAJOR | Harness seam definition | §4 defines `search(query, k) -> [session_id]`, but §4 also requires optional per-hit message IDs | Seam definition must support optional message IDs for fusion aggregation | Amend seam signature: `-> list[tuple[session_id, Optional[list[message_id]]]]` |
| F5 | MINOR | Test coverage gap – CLI | §2.5: CLI path skips planner; §4 lists "CLI end-to-end with 5 natural questions" | None of the 9 test-pinned nodes cover natural-language CLI input or assert equivalence to MCP | Expand §4 tier integration tests to require CLI natural-question equivalence to MCP |

## Answers

**Q1**
R1–R4 covers robust paraphrase retrieval (semantic), alignment (triggers), unified agent surface, and metrics harness. Missing emphasis on **doctor repair pathways** (§2.3) and **degraded modes** (offline model → `unavailable` method status). Otherwise, complete.

**Q2**
Yes, because the crash class (4/4 Stage 4) is a fatal SQL defect (§A.4), blocking any semantic arm. The semantic arm can't fix syntactic query tokenization. Conversely, the lexical layer cannot meet R1’s paraphrase requirement alone. Fix delivers baseline; then extend.

**Q3**
It is the strongest. Triggers handle deletions and content updates directly. Scrub remains a risk — requires post-scrub embedding deletion or content-hash comparison. The §2.3 “redacted secret survives” issue is closed by DELETE-on-scrub. Merge misrepresentation is closed by dropping session vectors. Design is sound.

**Q4**
D3: §2.1 states 57k messages embeddable; lane A §6 shows mpnet cost = 140ms/query, MiniLM = 30ms. Measure length distribution and query latency: truncate unless >5% over limit justify chunking.
D4: Bake-off models using macro recall@5 (gold/dev) under equal N; prefer best lift at lowest latency * cost factor. Default = fastest viable unless lift establishes premium cost justification.

**Q5**
Yes, gold ensures functional stability; census exposes generalization. However, global % like “61%” from past runs invalid without twin-filtering. Guardrail missing: enforce twin-aware winnable ceiling calculation. Report delta, not global %. Better: self-retrieval ≥ 0.70 of filtered ceiling.

**Q6**
Under-specified: **doctor repair behavior** (trigger vs backfill paths) and **sync-import lag effects**. Missing: integration test where `session-sync` receives exported rows → asserts `doctor` reports stale backlog. Also: scrub → no vector left test needed.

**Q7**
Yes. Lane D §5 notes real `call_tool` avoids crashing. It routes through actual skill text and real parser paths — unlike inlined planners in Stage 4 rulers. It’s the only interface enforcing mandate consistency (SKILL.md:16–29).

**Q8**
Fold. Stage 6 (orphaned obj DROP) fits within VACUUM context of Stage 13. Stage 8 (openspec) and 10 (gates) logically follow unified retrieval completion. No inversion detected. Clean consolidation at no extra migration cost.

**Q9**
If hybrid lifts aren’t established and it ships disabled (§5), yet the API presents method=`semantic`, response fields imply active use. Or if CLI/MCP diverges in method semantics post-Stage 12. Must ensure all exposed interfaces report consistent statuses.

**Q10**
F1 above (define crash class precisely). Plus: verify whether `uv` resolves or stubs `sqlite-vec` load reliably (§2.1). If stubbed, embedding layers won't integrate — BLOCKING before Stage 11. Confirm `sentence_transformers` downloads are cached enough for CI.
