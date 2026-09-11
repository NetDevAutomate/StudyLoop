<!-- verified_model: kimi-k2-thinking -->
<!-- finish_reason: stop · 92.0s · usage: {"completion_tokens": 9511, "prompt_tokens": 5847, "total_tokens": 15358, "completion_tokens_details": {"reasoning_tokens": 7709, "text_tokens": 1802}, "prompt_tokens_details": {"cached_tokens": 0, "text_tokens": 5847, "cache_write_tokens": 0, "cache_creation_tokens": 0}, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0} -->

 VERDICT: APPROVE-WITH-CHANGES

## Findings

| id | severity | plan item | claim | check | proposed change |
|----|----------|-----------|-------|-------|-----------------|
| F1 | BLOCKING | D2/D5 – sqlite‑vec | “sqlite‑vec in‑DB is transactional with the rows it describes” (§4.2) | No evidence that the sqlite‑vec virtual table respects SQLite transaction rollbacks; virtual tables often bypass the journal, so a rollback may leave orphaned vectors. **UNVERIFIED** | Before Stage 13, write a unit test that inserts a message + vector, rolls back the transaction, and asserts the vector is gone. If it fails, abandon sqlite‑vec for a plain table + manual KNN index or a numpy sidecar with explicit locking. |
| F2 | MAJOR | Stage 14 acceptance – census | “census self‑retrieval@5 non‑inferior on every stratum” (§5) | The census baseline in lane B was run on the learning‑memory store, not `sessions.db`. No `sessions.db` baseline exists, so “non‑inferior per stratum” is undefined. **UNVERIFIED** | Replace per‑stratum non‑inferiority with a single macro recall@5 on the `sessions.db` census; keep per‑stratum numbers for diagnostic plots only. |
| F3 | MAJOR | R3 – “the interface for the agent is the semantic layer” (Stage 15) | If semantic arm fails to show lift, it ships *off by default*, leaving the lexical arm as the primary interface, contradicting R3. | The plan’s own acceptance rule (Stage 14) says semantic may be off by default; R3 requires the semantic layer to be the interface. **UNVERIFIED** | Revise the claim: the semantic layer becomes the *default* interface only when lift is established; otherwise the lexical‑fixed service remains primary and semantic is a re‑ranker. Update skill/mandate text to reflect this. |
| F4 | MAJOR | D6 – prune_hot eviction (tiering.py:850‑860) | “Exclude embeddings from `_archive_context_complete`; prune_hot still evicts” (§3.13) | The original condition requires both embedding tables row‑identical before eviction; removing it may allow eviction of a tier whose vectors are not yet regenerated, breaking the archive integrity guarantee. **UNVERIFIED** | Add an integration test: run a full‑tier evict + re‑import and verify that re‑embedding restores vectors without loss. If unsafe, keep the check but trigger a doctor‑backfill before prune. |
| F5 | MINOR | Stage 14 latency target | “p95 warm hybrid latency ≤ 250 ms” (§5) | Measured warm query embedding ~140 ms (lane A §6); KNN search overhead not measured on 57 k vectors. No evidence total ≤ 250 ms. **UNVERIFIED** | Measure p95 hybrid latency in Stage 11 on the live‑size clone; set target based on measured baseline + 50 ms slack (e.g., 200 ms). |
| F6 | MINOR | D4 – model bake‑off | “Model bake‑off on gold; pin one after lift” (§3.14) | No measurement of throughput (msgs/s) or storage size for mpnet (768‑d) vs MiniLM (384‑d) on the full 57 k messages. **UNVERIFIED** | Add throughput and storage metrics to Stage 11; only consider mpnet if lift ≥ +0.05 and latency ≤ 250 ms. |
| F7 | MINOR | Stage 12 crash fix | “Fix eliminates the crash class” (R1‑lexical) | The fix removes the escape_fts_query bug (lane A §4) but introduces a fallback for all‑stop‑word queries that may return empty results – not a crash but a silent degrade. **UNVERIFIED** | Add an integration test for an all‑stop‑word query; assert non‑empty fallback results. |
| F8 | MINOR | D3 – chunking threshold | “Chunk messages only if share > 2 KB is material” (§3.3) | Stage 11 will measure length distribution, but “material” is undefined. **UNVERIFIED** | Define “material” in Stage 11 acceptance rule (e.g., > 5 % of embeddable messages exceed token limit). |
| F9 | MINOR | Test harness integration tier | “Covers all lifecycle paths” (§4) | No explicit test that hidden sessions are excluded from semantic results; no test that scrub removes vectors; no test that export UPDATE leaves vectors stale. **UNVERIFIED** | Add three integration tests: (1) hidden session → embed → search → assert not returned; (2) scrub message with vector → assert vector gone; (3) export UPDATE → doctor → assert missing count > 0. |
| F10 | MINOR | R4 – committed receipts | “Receipts exist and are byte‑stable” (§4) | No spec for receipt format, versioning, or CI integration; “byte‑stable” not defined. **UNVERIFIED** | Define a receipt schema (JSON with DB fingerprint, model id, metrics) and store in git; add CI check that regenerating receipts yields identical bytes. |

## Answers

**Q1.**
The decomposition covers R1 (paraphrase robustness via hybrid), R2 (triggers + doctor for alignment), R3 (unified lexical service), and R4 (three‑tier harness). Minor gaps: no explicit test that hidden sessions vanish from semantic results (lane C §1) and no integration test for scrub‑vector removal (lane C §1). Overall faithful.

**Q2.**
Yes, lexical fix first. It cures the root cause—bypassing the planner (lane A §4). Semantic cannot fix FTS syntax errors; lexical cannot match synonyms or paraphrase. Hybrid adds paraphrase robustness after lexical is stable.

**Q3.**
Mostly strong: delete‑on‑change eliminates stale vectors for UPDATE/DELETE and scrub. Remaining risk: `exporters/base.py:167‑175` UPDATE may not fire the trigger (raw SQL), leaving vectors stale until doctor runs. Also, if `foreign_keys=OFF`, CASCADE fails (lane A §2). So not fully by construction.

**Q4.**
D3: Measure share of embeddable messages > 2 KB (or model token cap) in Stage 11; if > 5 % → chunk. D4: Run gold macro recall@5 for MiniLM/bge‑small/mpnet; pick the model with highest established lift (CI95 lower ≥ +0.05) and p95 latency ≤ 250 ms (lane B gold, lane A perf).

**Q5.**
Macro recall@5 on gold is correct for primary goal; census self‑retrieval@5 on `sessions.db` (new) is a valid paraphrase probe. The 0.70 winnable ceiling is sound if ceiling per stratum accounts for dup twins (lane B §4). Missing guardrail: explicit check that hidden sessions never appear in any arm (tier 4).

**Q6.**
Integration tier is under‑specified: lacks tests for hidden‑session exclusion, scrub‑vector deletion, and export‑UPDATE staleness. Add three tests: hidden session → embed → search (assert not returned); scrub message → vector gone; export UPDATE → doctor reports missing.

**Q7.**
Yes. `call_tool` exercises the real MCP server, planner, and tool schema—identical to the agent’s runtime (lane D §5). CLI equivalence test ensures parity. Direct SQL arm bypasses server logic and is not representative.

**Q8.**
Fold is correct. Stage 6 (DROP orphaned ontology) is independent and can co‑migrate with Stage 13’s VACUUM INTO backup. Stage 8 (doc retirement) and Stage 10 (sign‑off) are close‑out tasks fitting Stage 15. No dependency inversion.

**Q9.**
If semantic arm fails lift (CI95 lower < +0.05) and ships off by default, the agent’s primary interface remains lexical, contradicting “the interface is the semantic layer.” Also, if semantic is not the default retrieval path, the claim is false. Evidence: Stage 14 acceptance rule, R3 wording.

**Q10.**
Yes: verify sqlite‑vec transaction semantics—if not atomic with main DB, alignment by construction fails. Also confirm the 5‑question probe (lane D §5) is representative of the 91 gold questions (coverage). Run a dry‑run of the harness on `main` to ensure baseline metrics are reproducible.
