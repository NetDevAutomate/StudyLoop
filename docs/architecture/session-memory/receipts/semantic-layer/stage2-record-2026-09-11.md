# Stage 2 record — one lexical service; the crash class dies

**Date:** 2026-09-11 · **Commits:** `79425cbe` (service), `d060d3f2` (surfaces + harness + pins),
receipts commit (this file) · **Council:** single seat, `openai.gpt-6-astra` — see the addendum
at the foot once the review returns.

## What shipped

`agent_session_tools/retrieval.py` is the one lexical retrieval service. `session_search` (MCP)
and `session-query search` (CLI) both call `retrieval.search()` and return the same document —
`{"rows": [...], "retrieval_status": {...}}` — with a real `message_id` on every row and query-time
exclusion (`exclude_message_ids`) on the tool. The CLI's own SQL is gone.

The crash class dies by construction: FTS5 operators are uppercase by definition, so a query is
explicit FTS5 only when it carries an uppercase `AND`/`OR`/`NOT`/`NEAR` or the `fts:` prefix.
Everything else is planned into quoted terms that cannot fail to parse (AND first, widened to OR
when empty — the shipped semantics, kept). Double-quoted spans survive as phrases. An explicit
query FTS5 rejects is re-run as natural language with the rejection in `retrieval_status.note`.
An empty result is never silent: `plan="none"` plus a note says nothing was searched.

## Gates (freeze §5), measured — `stage2-gold.json`, `stage2-census-mcp.json`

| gate | required | measured |
|---|---|---|
| crashes through the real MCP tool | 0/91 | **0/91** (frozen control still 42/91) |
| crashes through the CLI | 0/91 | **0/91** (was 42/91 + zero rows on the other 49) |
| CLI ≡ MCP, ordered session lists | 91/91 | **91/91**, paired delta exactly 0 |
| K-stratum paired delta vs frozen | not negative | K **0.182 → 0.303**; P 0.034 → 0.034; R 0.103 → 0.138 |
| planner golden | unchanged | **cases byte-identical**; row shape extended additively — see deviation |
| macro recall@5 (reported, not gated) | — | **0.1066 → 0.1585**, paired +0.052, CI95 [+0.011, +0.100] (57 clusters) |
| latency | — | mcp p50 20.8 ms / p95 92 ms (was 18.5 / 94.5) |

Honest detail: of the 42 former crashers only **5** become hits at K=5. The crash class is dead;
those questions now have the same ranking problem as everything else. That is Stage 4's problem,
and the K/P/R shape says so: K and R moved, P did not.

## Deviation from the freeze wording — recorded, not hidden

The freeze said "golden file unchanged". The golden's `row_keys` gained `"message_id"` and each
case result gained its id; every case's query, ordering and preview is byte-identical (verified
by diff: five added lines, nothing removed). The gate's purpose — the explicit-syntax and simple
cases must not move while the planner changes — held. Real message ids were a stated Stage 2
requirement (the agent's interface had no citation handle and the census could not gate the tool
without them), so the additive change is the requirement, not drift.

## Census through the real tool — first time possible

`stage2-census-mcp.json`: 5,434 eligible · hits **3,345** · hit@5 **0.6156** (Stage 1 frozen
0.1305) · crash **0** (was 2,349) · vocabulary 257 · ranking 1,832 (untied 1,546) · tied hits 0.

A jump that size was not accepted on sight. A 400-question paired probe (seed 11, both arms,
same self-exclusion, session lists compared) attributes all of it to two shipped defects and
finds **zero regressions**:

| class | n | frozen own-session hits | live own-session hits |
|---|---|---|---|
| identical ranked lists (planner ran in both) | 140 | 54 | 54 |
| frozen **crash** (the and/or/not class) | 189 | 0 | 129 |
| frozen **empty**, live rows — **70 of 71 texts contain a `"`** | 71 | 0 | 57 |

The second defect the gold set could not see: the shipped code treated any question containing
a double-quote character as "explicitly quoted" and searched its *entire text* as one exact
phrase — which matches nothing but the question itself. Learner turns quote error messages,
file names and code constantly (71 of 400 = 18%). The planner now lifts quoted spans out as
phrases and plans the rest.

Sample hit@5 frozen 0.135 / live 0.600 — both within 0.02 of their full-census receipts.

Per source (Stage 1 → Stage 2): claude_code 0.016 → 0.806 (its turns are the quote-heavy,
punctuation-heavy ones), kiro_cli 0.202 → 0.520, codex 0.168 → 0.475, grok 0.221 → 0.588.

## Verification

- `ruff check`, `ruff format --check`, `pyright` (src + tests): clean; pre-commit hooks green on
  both commits (the first attempt at a surfaces-only commit was refused by the pyright hook
  because the harness still imported the deleted planner — the two were then landed together,
  which is the correct unit).
- `agent-session-tools`: **1,833 passed** on the final tree (1,805 before Stage 2, +28).
- `studyloop` package: 3,912 passed; 166 failed / 147 errors, none caused by Stage 2 — 157 are
  one leaked event loop (`asyncio.run() cannot be called from a running event loop`) that also
  hits `memory_search`/`get_active_topics`/`log_struggle` tests; the rest are sandbox conditions
  (no PyPI, no `tmux`, PTY spawn timeouts, journey-root guard). The only file whose failures name
  `session_search` passes 10/11 in isolation, the one red being `tmux`.
- Toy corpus (CI validation tier): 7/7 on measured values.

## Deferred, with reason

- `memory_search` (R3 "ideally"): it already plans safely over a different index
  (`context_evidence_fts`, OR of quoted terms in `context/collection.py`). Unifying its planner
  with `retrieval.plan_query` is a refactor with no behaviour change today; deferred to Stage 4
  where the shared service changes shape for the hybrid arm.
- Lexical tuning (the `len(token) > 2` filter, stop-word list, AND-first vs OR-first): Stage 2
  preserved the shipped semantics on purpose so the change is attributable. The planner is now
  one function with a receipt behind it; Stage 4 tunes it against the toy set and confirms once
  on SEALED.

## What Stage 3 and Stage 4 inherit

- The service is the seam the semantic arm plugs into: `RetrievalStatus.mode` is `"lexical"`
  and becomes `"hybrid"` only when the arm is established.
- The census can now gate the real tool (`supports_exclusion` read from the tool's schema).
- Ranking, not vocabulary and not crashes, is the dominant miss on the corpus the product serves:
  1,832 ranking misses vs 257 vocabulary misses.

## Council addendum

_(appended when the single-seat review returns)_
