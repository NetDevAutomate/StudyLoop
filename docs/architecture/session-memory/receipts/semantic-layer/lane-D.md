# Lane D — the agent-facing interface to session memory (`main`, read-only)

Scope: every surface an AI agent in the six admitted harnesses uses to reach session
memory, how each interprets the query text, and which tests pin it. All citations are
`main` @ `b42f334e`.

## 1. Surface inventory

| Surface | Entry point | Query-text interpretation | Filters | Output shape | Consumers |
|---|---|---|---|---|---|
| MCP `session_search` | `packages/agent-session-tools/src/agent_session_tools/mcp_server.py:334` | **Planner, two arms.** `_session_search_queries` (`mcp_server.py:73`) passes through verbatim (via `escape_fts_query`) if the text contains ` AND `/` OR `/` NOT ` or any `"`/wrapping `'`; otherwise `query_planner.plan` (`query_planner.py:52`) tokenises on `[a-zA-Z0-9_./-]+`, lowercases, drops a 62-word stop list and tokens ≤2 chars, quotes each survivor, and yields `and_query` then `or_query`. Loop at `mcp_server.py:356` tries AND, falls back to OR only when AND returns **zero rows**. `ORDER BY bm25(messages_fts), m.timestamp DESC` (`:382`) | `source` (`:377`), `project` via `build_project_filter` (`:380`), scope via `visibility_sql` (`:368`). No date filter | `list[dict]`: `session_id, source, project_path, updated_at, role, timestamp, preview` (300 chars, `:360`) | `agents/skills/studyloop-session-memory/SKILL.md:16`; `agents/shared/session-db-mandate.md:4`; `agents/shared/session-protocol.md:72` |
| CLI `session-query search` | `query_sessions.py:86` → `query_logic.search:121` → `_search_rows:161` | **Strict phrase only.** `fts_query = escape_fts_query(query)` (`query_logic.py:166`). Multi-word ⇒ wrapped in `"…"` = adjacency phrase. No planner, no OR fallback. Federated across the attached full-history schema (`_search_schema:66`) | `--since/--before` (`build_date_filter`), `--project`, `--local-only`, scope | table/json rows + `tier: local|full` | Same skill as the "deterministic fallback" (`SKILL.md:22-29`); `docs/session-memory.md:87`; `docs/cli-reference.md:537` |
| MCP `memory_search` | `mcp_server.py:146` → `context/public.py:408` → `context/collection.py:15` | **OR of per-word quoted terms** over `context_evidence_fts` — `re.findall(r"\w+")`, dedup, first 16, `" OR ".join('"'+t+'"')` (`collection.py:26-32`). No stop-list, no AND arm, no phrase mode, no operator pass-through. `ORDER BY bm25(context_evidence_fts), e.id LIMIT 101` | `project`, `as_of` cutoff, scope `store._where` | dict: `sources[]` with exact offsets + `reason.method`, `assertions[]`, `relationships[]`, `coverage`, `snapshot_id` | `SKILL.md:31-41`; mandate `:6`; protocol `:72` |
| CLI `session-context search` | `context/cli.py:181` | Identical to `memory_search` (same `context.search`) | same | JSON | `SKILL.md:41` (CLI fallback) |
| MCP `session_context` / `session_show` | `mcp_server.py:484` / `:452` | No query text — `resolve_session_id` exact-then-prefix | — | formatted excerpt / full transcript | `SKILL.md:19` |
| MCP `session_list`, `session_stats`, `session_hotspots`, `session_clean`, `session_annotations` | `mcp_server.py:396, 558, 713, 631, 212` | No free-text query | source/project/days | rows / dicts | protocol, docs |
| MCP `memory_propose/relate/review/reviews/assess/decide/source` | `mcp_server.py:170-330` | `assess`/`decide` re-enter `context.search` with the same OR-of-terms (`public.py:459`, `:692`) | project, `as_of` | evidence packs | `SKILL.md:31-41` |
| studyloop MCP `get_study_history` | `packages/studyloop/src/studyloop/mcp/tools.py:397` | **Python substring, not FTS**: `topic.lower() in s.get("course","").lower()` (`:426, :435, :440`). Reads `study_sessions`/`teach_back_scores`/practice — **not** `messages`/`messages_fts` | `days` | dict of stats/struggles/wins | protocol `:72` |
| studyloop MCP `get_concept_context` | `tools.py:666` → `learning/mastery.py:670` | Topic string into `mastery_graph_json`; graph lookup, not text search | `limit`, byte budget | edges/nodes + `semantic_arbitration: "not_performed"` | `SKILL.md:43-53`; mandate `:7` |
| studyloop MCP `get_topic_suggestions` | `tools.py:337` | No query text; algorithmic 60/40 importance-frequency score | — | ranked list | protocol |
| studyloop MCP `log_struggle` | `tools.py:820` | Write path | — | — | mandate `:24` |

Two distinct FTS corpora: `messages_fts` (transcripts, 132,439 visible messages) and
`context_evidence_fts` (109,633 evidence rows). No surface searches both.

## 2. What the steering actually instructs

`agents/shared/session-db-mandate.md:3-8`:

> "At the **start** of each session, follow the `studyloop-session-memory` skill.
> Prefer the `session_search` MCP tool with the current project path; if that MCP
> tool is unavailable, run the installed `session-query` CLI instead."

`agents/skills/studyloop-session-memory/SKILL.md:16-29`:

> "Prefer the `session_search` MCP tool when it is connected: - Query with the
> current project path plus the user's topic. … If the MCP tool is unavailable, use
> the installed CLI: `session-query search "<topic or error>" --project "$PWD"` …
> A missing MCP server is not a reason to skip retrieval; the CLI is the
> deterministic fallback."

`agents/shared/session-protocol.md:71-75`:

> "Then query memory for the topic, following the `studyloop-session-memory` skill:
> `session_search` for where it was discussed, `memory_search` for what was
> previously decided or disputed about it, and `get_concept_context` for its
> prerequisite edges."

Does this imply exact phrasing? **Not in the wording — but the fallback path enforces
it.** "the user's topic" and `"<topic or error>"` read as natural language, and the MCP
planner tolerates that. The CLI the same skill designates as the *deterministic*
fallback does not: any multi-word natural question becomes a strict adjacency phrase and
returns nothing (§6). The skill therefore instructs agents to degrade from a
tolerant surface to an exact-phrase surface, and calls that degradation deterministic.
Nothing anywhere tells the agent to reduce a question to keywords before falling back.

## 3. Tests that pin each behaviour

- **(a) Tool list/count** — `packages/agent-session-tools/tests/test_mcp_server.py::TestServerCreation::test_server_has_all_tools` (`:300-330`, exact set equality of the 16 names). Registration of both servers across harnesses: `packages/studyloop/tests/test_mcp_registration.py::test_install_agents_registers_both_servers_idempotently_for_three_harnesses` (`:80`).
- **(b) `session_search` result shape** — `test_mcp_server.py::TestSessionSearch::{test_search_returns_results, test_search_no_results, test_search_with_source_filter, test_search_with_project_filter, test_search_respects_limit}` (`:175-206`); row-key and 300-char preview equality in `tests/test_session_search_planner.py::test_session_search_preserves_every_non_widened_golden_case` (`:128-142`) against the frozen `tests/golden/session_search_pre_planner.json`.
- **(c) Query semantics** — `tests/test_session_search_planner.py`: `test_session_search_falls_back_to_or_when_implicit_and_is_empty` (`:145`), `test_session_search_does_not_widen_nonempty_implicit_and` (`:250`), `test_session_search_stops_after_and_fills_the_limit` (`:173`), `test_session_search_preserves_explicit_phrase_adjacency` (`:187` — pins that `"exact phrase"` must match adjacently and excludes `"exact unrelated phrase"`), `test_session_search_preserves_explicit_not_exclusion` (`:194`), `test_session_search_preserves_explicit_and_or_controls` (`:201`), `test_session_search_safely_plans_adversarial_plain_text_punctuation` (`:235`). The CLI's exact-phrase rule is pinned only indirectly, at unit level: `tests/test_query_utils_extended.py::TestEscapeFtsQuery::test_multi_word_wraps_in_quotes` (`:16`). **No test exercises `session-query search` end-to-end with a natural-language question**, and no test pins `memory_search`'s OR-of-terms matching as a contract.

## 4. The `memory_*` family

Its own store, not `sessions.db` transcripts — `context_evidence` / `context_evidence_fts`
(`collection.py:34-41`), in the *same* SQLite file (schema `user_version` 47).
Matching is a flat OR of up to 16 quoted single words with BM25 ordering and a
100-candidate cap; `reason.method = "lexical_match"` and `"ordering": "BM25 relevance;
not a truth ranking"` are returned verbatim (`collection.py:83-88`). It is lexical
recall over evidence bodies plus a graph walk over assertions/relations — the graph is
the added value, not the retrieval. Live store: 109,633 evidence rows but **1**
assertion, so today `memory_search` returns sources with `assertions: 0`.

## 5. Docs vs reality

**Drift 1 — the vector/semantic layer is unreachable.** `semantic_search.py:78`
`hybrid_search(..., fts_weight=0.4, semantic_weight=0.6)` and `embeddings.py:386`
`embed_message` exist and are tested (`tests/test_semantic_search.py`), but no
production module imports them: the only importers repo-wide are three test files.
`docs/cli-reference.md:653` still sells the capability:

> "`uv pip install agent-session-tools[semantic]  # Vector embeddings search`"

and the shipped default config claims it runs automatically
(`config_loader.py:75-88`):

> `"semantic_search": { "model": "all-mpnet-base-v2", "fts_weight": 0.4, "semantic_weight": 0.6, … "auto_embed": True }`

Reality: `auto_embed` is read by nothing (grep finds it only in its own definition and
one docstring at `config_loader.py:404`), and the live DB holds `message_embeddings = 0`,
`session_embeddings = 0`.

**Drift 2 — "deterministic fallback".** `SKILL.md:29` — "the CLI is the deterministic
fallback" — versus `query_logic.py:166`, which makes every multi-word query an
adjacency phrase. Deterministic, but deterministically empty for natural questions.

**Non-drift, worth crediting.** `docs/context-memory.md:82` is honest about
`memory_search`: "Search uses literal query words with SQLite FTS/BM25", and every
response carries `semantic_completeness: "not_established"`. The one docs surface that
describes matching accurately is the one describing the non-semantic tool.

## 6. Behavioural probe (read-only, live DB, `mcp.call_tool`)

`_get_db_path() = /Users/ataylor/.config/studyloop/sessions.db`; 16 tools listed;
4,600 visible sessions / 132,439 visible messages. `and_hits`/`or_hits` are candidate
message counts for each planner arm; `cli_phrase_hits` is `escape_fts_query`'s single
phrase query (the CLI path) against the same corpus.

| Question | MCP result | Top hit | AND arm | OR arm | CLI phrase |
|---|---|---|---|---|---|
| how did I fix the tmux socket problem? | 4 rows | `grok_01a05ed7-91b8-72a1-ae18-2f7a32af3dee` | 4 | 8,109 | **0** |
| what did we decide about the ontology? | 5 rows | `ddae6300-4460-4fb3-9848-bccc26601585` | 64 | 1,399 | **0** |
| sessions where Python decorators came up | 5 rows | `agent-a9b6256671b4fd753` | 14 | 11,691 | **0** |
| the FTS5 syntax error with backticks \`like this\` | 5 rows | `kiro_e5d353db-a6cd-4941-9f81-c63eb1b1f841` | **0** (fell through) | 8,921 | **0** |
| why did the export fail? | 5 rows | `b573a6c5-cd30-4e61-9154-b97cef84251b` | 772 | 6,517 | **0** |

No errors on any of the five; the backtick query did not raise an FTS5 syntax error
because the planner quotes each token. `memory_search` on questions 1-2 returned 5
sources each, `assertions: 0`, `coverage.limits_reached: ["lexical_candidates","sources"]`.

Reading: the MCP surface already accepts natural language and never returns empty here;
the CLI surface returns empty for all five. The remaining weakness on the MCP side is
selection, not tolerance — when AND misses entirely, the fallback is a 8,921-candidate
OR pool ranked by BM25 with no semantic reordering, so relevance rests on lexical
overlap alone.

## Numbers measured

- 16 MCP tools on `session-db`; 4 free-text query entry points reaching two FTS corpora.
- Live DB: 4,600 visible sessions, 132,439 visible messages, 109,633 evidence rows, 1 assertion, 0 embeddings, `user_version` 47.
- 5/5 natural questions answered by MCP `session_search`; 0/5 by the CLI path.
- 1/5 questions needed the OR fallback; its candidate pool was 8,921 messages.
- Planner stop-list: 62 words (`query_planner.py:14`); tokens ≤2 chars dropped.
- `semantic_search.py` (581 lines) + `embeddings.py` (593 lines): 0 production importers, 3 test importers.
- 9 test node ids pin planner semantics; 1 pins the CLI phrase rule at unit level; 0 pin `memory_search` matching.

## Open questions

1. Should the CLI adopt `_session_search_queries` so the designated fallback matches the MCP surface? Today the two disagree on every multi-word query, and `golden/session_search_pre_planner.json` shows the planner was retrofitted to MCP only.
2. Is the OR fallback's 8,921-candidate BM25 pool the intended semantic layer, or the placeholder for it? The owner's requirement is met for *tolerance* but not for *ranking*.
3. Do we revive the vector layer (embed 132k messages, wire `hybrid_search`) or delete it and the `[semantic]` extra? Keeping unreachable code that docs advertise is the current worst option.
4. Should `session_search` and `memory_search` become one call? An agent today must issue two queries with two different matching rules over two corpora, and the skill's ordering ("after `session_search`") is prose, not enforced.
5. `get_study_history` uses substring matching on course names — does a natural topic phrase ever match, and should it route through FTS instead?
