# Lane B — the two rulers and the one established lever

Read-only investigation of `feat/knowledge-proof` @ `464a8cdc` (worktree
`.worktrees/knowledge-proof`); paths worktree-relative unless marked `main:`. The Stage 4
receipts exist on `main` only, not on this branch.

---

## 1. `plan_prose_query` — the +0.142 lever

`packages/learning-memory/src/learning_memory/store.py:229-255`. Five lines of body:

1. `query.split()` on whitespace — no regex, no lowercasing, no stemming (`store.py:251`).
   FTS5's `porter unicode61` tokenizer folds at match time (`schema.py:180`).
2. Strip characters of Unicode category `Cc`/`Cs` (`_UNSAFE`, `store.py:63`) — control chars
   and lone surrogates, because FTS5 parses its expression as a C string so an embedded NUL
   truncates it (`store.py:238-241`).
3. Keep the token only if an alphanumeric survives (`store.py:253`). This is the only filter:
   **no stop-word list at all.**
4. Each token becomes one FTS5 **phrase** — wrap in `"`, double embedded `"` (`store.py:255`).
5. `" OR "`-join. No AND arm, no fallback: "OR is the arm that cannot throw"
   (`store.py:247-248`).

**Pure**: `(str) -> str`, no DB handle, no I/O, no state, one stdlib import (`unicodedata`,
`store.py:22`).

Measured output (worktree venv):

| input | output |
|---|---|
| `How did we decide to handle the retired harness labels?` | `"How" OR "did" OR "we" OR "decide" OR "to" OR "handle" OR "the" OR "retired" OR "harness" OR "labels?"` |
| `Why does \`plan_prose_query\` OR-join every token?` | `"Why" OR "does" OR "\`plan_prose_query\`" OR "OR-join" OR "every" OR "token?"` |
| `What broke the FTS5 search when a question ended with a ?` | `"What" OR "broke" OR "the" OR "FTS5" OR "search" OR "when" OR "a" OR "question" OR "ended" OR "with" OR "a"` |
| `?` / `---` | `''` — callers return no rows (`store.py:243-245`, `store.py:923-925`) |
| `WP-9 AND NOT (foo* bar) 42` | `"WP-9" OR "AND" OR "NOT" OR "(foo*" OR "bar)" OR "42"` |

Rows 2–3 are the point: backtick and trailing `?` survive *inside* the phrase quotes and are
inert — that is the 42/91 crash class on `main`. A bare `?` token is dropped (no alphanumeric).

**Liftable unchanged?** Yes, mechanically. `proof_arms.py:198-238` (`B1_planner`) already
proves the swap against the *shipped* `messages_fts`, shipped bm25, shipped visibility
predicate and shipped 200-row budget, changing only the query text. Two behavioural deltas to
accept deliberately: (a) `main:.../query_planner.py:9-27` drops stop-words and tokens ≤ 2
chars and lowercases — `plan_prose_query` drops none, so recall widens and precision narrows;
(b) `main:.../mcp_server.py:73-93` deliberately passes explicit FTS syntax (` AND `/` OR `/
` NOT `, or a quote) through to `escape_fts_query` verbatim, and the lever neutralises all of
it — so that pre-check must be kept in front of it, or `search_prose_raw`
(`store.py:928-935`) exposed as the deliberate-syntax door.

---

## 2. Paraphrase census — instrument #1

`scripts/knowledge_proof/paraphrase_census.py`. No model, read-only.

**Population.** Every `kind='user'` event in a session whose id is not `agent-*`
(`census:223-227`). Eligibility ≤ 200 words (`census:46`, longer turns are pasted material)
and ≥ 3 content tokens (`census:45`). Questions are **not generated or paraphrased** — each
real learner turn is a question about its own session. v2: 4,710 turns → 466 short, 945
pasted → **3,299 measured**.

**Measures.** *Vocab overlap* = share of the question's stemmed content tokens appearing in
some **other** prose event of the same session, own row and byte-identical re-asks excluded
(`census:275-282`); tokeniser `[a-z0-9_][a-z0-9_./-]{1,}` (`census:191`), ~150-word stop list
(`census:48-190`), hand-rolled suffix stemmer (`census:194-204`) used only for this statistic,
never for retrieval. *Self-retrieval@5* = `plan_prose_query(text)` → `prose_fts`, `ORDER BY
bm25(prose_fts), e.id LIMIT 200`, own/re-ask rows dropped, dedup to distinct sessions, hit =
own session in first 5 (`census:284-301`). *Miss class* = `vocabulary_gap` if overlap == 0.0
else `ranking` (`census:305-316`).

**Retriever seam: there is none.** `score.py` has `Arm =
Callable[[sqlite3.Connection, str], list[str]]` (`score.py:36`) and `--feature
module:callable` (`score.py:243`); the census **inlines** planner and SQL at
`census:284-299`. Extracting ~15 lines into an arm-shaped callable is prerequisite refactor
work, not incidental.

**v2 numbers** (`paraphrase-census-v2.md`, `-v2.json`): hit 2,015/3,299 = **61.08 %**;
vocabulary-gap 188 = **5.70 %**; ranking 1,096 = **33.22 %**. Store
`…/knowledge-proof/learning-memory-v2.db`, sha256 `e0d507fe…`, ingested scoped to the seven
supported sources. `paraphrase_census_pair.py` decomposes the +3.79 pt over v1 honestly:
composition **+3.09 pt**, genuine retrieval **+0.70 pt**; 32 miss→hit, 9 hit→miss.
`paraphrase-census-duplicates-v2.json`: 475/3,299 (14.4 %) of eligible questions have
byte-identical text in another session, so part of the 33.2 % "ranking" bucket is
structurally unwinnable rather than badly ranked.

**Run it against `sessions.db` via `agent-session-tools` instead?** Yes, and it would be the
more honest measurement — that is the corpus the product serves. Three adapter pieces:
(1) questions from `messages WHERE role='user'`, and a prose predicate, since the store's
`kind IN ('user','assistant_prose')` filter has no archive equivalent and 53 % of archive rows
are tool echo (ADR-0011:34); (2) self-exclusion by `messages.rowid` rather than `events.id`;
(3) scope via `agent_session_tools.context.public.visibility_sql` (as `score.py:73-76` does),
or the 1,279 hidden sessions re-enter the competitor pool and v2's numbers stop comparing.

---

## 3. Gold DEV set — instrument #2

`docs/architecture/session-memory/receipts/gold-v2-dev.json`: 91 items, 57 clusters, sha256
`5632cd2b…`. SEALED (84 items) is outside the repo; only its sha is committed
(`gold-v2-receipt-r2.json`). Item schema: `id`, `question`, `stratum` (K keyword / P
paraphrase / R relational, `validation-ruler.md:47-48`), `cluster` (= source session, ≤ 2
questions each, the resampling unit), `gold_session_ids`, `expected_answer`,
`evidence[{session_id, message_id, quote}]`, `admitted_by`. Strata K 33 / P 29 / R 29.

**Correction to the brief: `score_stage4.py` does not use FastMCP `call_tool`.** No
`call_tool`/`FastMCP` reference exists anywhere in `scripts/` or `packages/learning-memory/`
(grepped). It imports the private `mcp_server._session_search_queries` and re-issues the
shipped SQL by hand plus the shipped `visibility_sql` (`score.py:45-86`,
`score_stage4.py:37-79`). The wrapper exists because today's `main` lacks
`_session_search_queries`, so it substitutes `escape_fts_query` and prints which shape it
scored (`score_stage4.py:44-56`). It also purges `sys.modules['agent_session_tools*']` on
**every** arm build (`score_stage4.py:39-42`) — the committed harness purged only when a pin
was given, so the second arm silently reused the first arm's modules and both arms scored one
codebase.

**Metric** recall@5 per question, macro-averaged over K/P/R, never micro (`score.py:88-92`,
`:124-130`, `validation-ruler.md:76-83`). MRR@5 reported, never gated. Inference: paired
cluster bootstrap, 10,000 draws, seed 20260910, 95 % percentile interval; "established lift" =
lower bound ≥ +0.05 (`score.py:38-40`, `:132-158`).

**Three unwinnable items.** 2 of 60 gold sessions are `litellm-proxy`, hidden by the
six-source scope, so `A1-13`, `A1-70`, `A1-71` (all verified present in DEV) have no visible
gold session for any arm. The denominator stays 91 for comparability, capping macro recall
below 1.0 (`main:stage4-pr18-keep-half-2026-09-10.md`, "Gold scope").

**B0 = 0.000 / B1 = 0.1066** (`main:stage4-keep-half-dev-rescore.json`). B0 = `main` @
`9235ab79` (pre-planner `escape_fts_query`): 0.000 on K, P and R. B1 =
`integrate/pr18-keep-half` @ `4ab13499`: 0.10658307210031348 (K .182 / P .034 / R .103),
identical to 17 digits to PR #18's own pinned receipt. `B1_vs_B0` = **+0.107, CI95 [+0.0426,
+0.1819]**, 57 clusters — **not** established. I re-ran `score.cluster_bootstrap` over the
receipt's per-question data and reproduced +0.10658 / [+0.04262, +0.18194] exactly. Both arms
error on the same **42 of 91** questions (`syntax error near "\`"` ×31, `near "?"` ×8, `no
such column: 9` ×1) — F-B0-1's crash half, live on `main`, unfixed by the keep-half. The
plan's "+0.142 from `fb33e2ce`" was a misattribution: the +0.142 is what you gain by
**replacing** that planner with `plan_prose_query` (ADR-0011:333; `proof_arms.py:198-210`).

---

## 4. The learning-memory store

**Tables** (`schema.py:_DDL`): `schema_version`, `sessions`, `events`, `evidence`, `lineage`,
`lineage_pending`, `exchanges`, `concepts`, `concept_aliases`, `concept_tags`,
`concept_occurrences`, `claims`, `claim_citations`, `claim_relations`, `review_items`; plus
VIEW `prose_events` (`kind IN ('user','assistant_prose')`) and `prose_fts` as FTS5
external-content **over the view**, so FTS5's own `'rebuild'` cannot pull tool output into the
index (`schema.py:20-24`, `:175-186`). Invariants are triggers, not conventions:
`claim_citation_bound_proof` re-checks in SQLite that the quote *is* the bytes at the
code-point offsets; `claims_need_citation`; `claims_immutable`; `evidence_immutable_*`.

**"Hidden" is a read-path scope, not a store state.** `ArchiveAdapter.sources` defaults to the
seven `SUPPORTED_SOURCES` (`adapters/archive.py:68-96`); every *enumerating* method is scoped,
while `parse`/`parse_id`/`session_metadata` still answer by id — "explicit access to a row
that exists is not a scope question" (`archive.py:262-273`). `hidden_source_counts()`
(`archive.py:306-323`) names **1,279** rows: repoprompt 440, aider 422, kilocode_cli 131,
litellm-proxy 124, gemini_cli 87, bedrock_proxy 71, omp 4. Nothing deleted — the archive is
the only surviving copy of ~89 % of that history.

**Relation to `sessions.db`: derived, one-way, read-only.** `open_readonly` is "the ONLY way
this module opens that file", `mode=ro` enforced by SQLite (`archive.py:229-238`). One
transaction per session, failures stepped over (`ingest_archive.py:16-17`). v2 ingest
(`ingest-archive-v2.json`): 4,600 in scope → 4,580 ingested, 20 rejected (all
`NoEvidenceError`, nothing citable), 95,010 events (42,305 assistant_prose / 39,624 tool_call
/ 8,156 user / 4,691 system / 234 tool_result), 47,449 evidence rows, 0 native captures,
37,314 exporter dupes collapsed, FTS integrity `ok`, 20.68 s, 230 MB. No write path back.

**ADR-0011 does not name the store a prerequisite for a semantic layer.** Status "measured —
not established" (ADR-0011:3); G1 recall NOT ESTABLISHED (fused claims arm 0.129 SEALED vs bar
0.64, *worse* than the prose control by −0.154); G2 NOT ESTABLISHED — INSTRUMENT; G3–G6 not
reached; the composite "the knowledge layers improve agent decisions" **may not be written**
(ADR-0011:316-330). The document's single "prerequisite" is unrelated and narrow: a
redaction/scrub policy is "a Stage E prerequisite" for shipping claims (ADR-0011:227). Whether
embeddings clear G4 sits under *Open questions* — "to be settled by measurement, not debate"
(ADR-0011:311-313). What **is** established is a product finding: `B1_clean` (prose-only FTS +
`plan_prose_query`) beat the shipped path by **+0.168** on SEALED (CI95 lower +0.076),
replicating DEV +0.184, with +0.142 attributed to the planner (ADR-0011:331-335).

---

## 5. Runtime

| run | time | source |
|---|---|---|
| Census, 3,299 questions, v2 store | **4 m 50 s** | `paraphrase-census-v2.md` |
| Archive ingest → store (4,580 sessions) | **20.68 s** | `ingest-archive-v2.json:wall_seconds` |
| Gold DEV, shipped arm, 91 q | **0.73 s** (p50 3.2 ms, p95 35.7 ms) | measured |
| Gold DEV, `B1_clean` arm, 91 q | **3.00 s** (p50 29.2 ms, p95 41.5 ms) | measured |
| `corpus_digest`, 91 DEV items | **0.01 s** | measured |
| One 10,000-draw cluster bootstrap | **0.09 s** | measured |

A two-arm `score.py` DEV run is therefore **≈ 5 s**; three feature arms plus the full pairwise
matrix stays inside ~20 s. The census is ~350× more expensive — iterate on gold, confirm on
census.

---

## Numbers measured

- Census v2: 4,710 turns → **3,299** measured; self-retrieval@5 **61.08 %** (2,015);
  vocab-gap **5.70 %** (188); ranking **33.22 %** (1,096); overlap mean 0.647 / median 0.700.
  Composition +3.09 pt vs retrieval +0.70 pt; 32 miss→hit, 9 hit→miss; 14.4 % duplicate twins.
- Gold DEV: 91 items / 57 clusters / K 33 P 29 R 29, sha256 `5632cd2b…`, corpus_digest
  `9aa2b495…` reproduced. B0 **0.000**, B1 **0.10658307210031348**, Δ **+0.107** CI95
  [+0.0426, +0.1819], `established=false`; 42/91 errors both arms; 3 items unwinnable.
- Store: 15 tables + 1 view + 1 FTS5 table; 4,580 sessions, 95,010 events, 47,449 evidence
  rows, 0 native captures; 1,279 hidden across 7 labels; ingest 20.68 s, 230 MB.
- Runtime: census 4 m 50 s; gold arm 0.73–3.00 s; bootstrap 0.09 s.

## Open questions

1. **The census has no arm seam** (`census:284-299` inlines planner + SQL). Extract a
   `Callable[[str], list[str]]` when — and does extracting it re-void the v2 receipt?
2. **Which corpus should the semantic layer be censused on?** The store keeps comparability
   with 61.08 %; `sessions.db` is what the product serves but needs the three §2 adapter
   pieces and yields an incomparable number.
3. **Does lifting the lever keep the explicit-syntax escape hatch?** Keeping both means a
   pre-check that was never measured.
4. **The 42/91 crash class is live on `main`.** Fix it here (free with the lever) or ship
   separately?
5. **How much of the 33.2 % ranking bucket is winnable?** Nobody has intersected *duplicate*
   with *ranking-miss*, so the headroom on this ruler is unknown.
6. **ADR-0011 does not authorise a semantic layer as settled.** G4 sits under *Open questions*
   and the claims arm failed as a peer list — a non-lexical arm must be pre-registered as a
   re-ranker or precision-gated candidate source (ADR-0011:337-344). Whose fusion-spec, before
   which look?
